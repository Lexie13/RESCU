import boto3
import os
import time
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table_users = dynamodb.Table("users")
sns_client = boto3.client("sns")

SNS_TOPIC_ARN = os.environ.get("EMERGENCY_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:RESCU_Alerts")

def trigger_emergency_email_loop(user_id, location_data="Location Unavailable"):
    """
    Retrieves the user profile, extracts emergency contacts (handling DynamoDB Type Tags),
    and sends an SNS email. Stops the loop upon the first successful send.
    """
    try:
        response = table_users.get_item(Key={"user_id": user_id})
        user_profile = response.get("Item")
        
        if not user_profile:
            return {"success": False, "error": "User profile not found in database."}
            
        contacts = user_profile.get("emergency_contacts", [])
        if not contacts:
            return {"success": False, "error": "No emergency contacts found for this user."}
        
        parsed_contacts = []
        
        # 1. Safely extract data, unwrapping the 'M', 'S', and 'N' DynamoDB tags if present
        for item in contacts:
            contact_map = item.get("M", item) if isinstance(item, dict) else item
            
            raw_email = contact_map.get("email")
            contact_email = raw_email.get("S") if isinstance(raw_email, dict) else raw_email
            
            raw_name = contact_map.get("name")
            contact_name = raw_name.get("S") if isinstance(raw_name, dict) else raw_name
            
            raw_priority = contact_map.get("priority", 99)
            priority = int(raw_priority.get("N", 99)) if isinstance(raw_priority, dict) else int(raw_priority)
            
            if contact_email:
                parsed_contacts.append({
                    "name": contact_name,
                    "email": contact_email,
                    "priority": priority
                })
        
        # Sort contacts by priority (1 being highest)
        parsed_contacts.sort(key=lambda x: x.get("priority", 99))
        notified_contacts = []

        # 2. Iterate and send
        for contact in parsed_contacts:
            contact_email = contact["email"]
            contact_name = contact["name"] or "Emergency Contact"
            
            subject = "URGENT: RESCU Fall Detected"
            message = (
                f"Hello {contact_name},\n\n"
                f"This is an automated emergency alert from RESCU. "
                f"A fall has been detected for the user you are monitoring.\n\n"
                f"Last Known Location: {location_data}\n\n"
                f"Please check on them immediately or contact emergency services."
            )
            
            try:
                sns_response = sns_client.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=subject,
                    Message=message,
                    MessageAttributes={
                        'target_email': {
                            'DataType': 'String',
                            'StringValue': contact_email
                        }
                    }
                )
                
                notified_contacts.append({
                    "email": contact_email,
                    "message_id": sns_response.get("MessageId")
                })
                
                print(f"Alert sent successfully to {contact_email}")
                
                # 3. END THE LOOP ON SUCCESS
                # Once an email is successfully accepted by SNS, exit the loop so we don't 
                # wait 60 seconds or message the lower-priority contacts.
                break 

            except ClientError as sns_err:
                print(f"Failed to send SNS to {contact_email}: {sns_err}")
                
                # If this specific contact fails, wait 60 seconds then try the next one
                time.sleep(60) 
                continue 
                
        if not notified_contacts:
             return {"success": False, "error": "Loop finished, but no valid emails could be notified."}
             
        return {"success": True, "notified": notified_contacts}

    except ClientError as e:
        print(f"DynamoDB Error: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}