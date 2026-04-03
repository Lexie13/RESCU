import boto3
import os
import time
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table_users = dynamodb.Table("users")
sns_client = boto3.client("sns")

# The ARN of the SNS Topic your emergency contacts are subscribed to
SNS_TOPIC_ARN = os.environ.get("EMERGENCY_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:RESCU_Alerts")

def trigger_emergency_email_loop(user_id, location_data="Location Unavailable"):
    """
    Retrieves the emergency contacts for a given user, loops through them in 
    priority order, and sends an email via AWS SNS notifying them of a fall.
    """
    try:
        # 1. Fetch all emergency contacts for the primary user
        response = table_users.query(
            KeyConditionExpression=Key("user_id").eq(user_id)
        )
        contacts = response.get("Items", [])
        
        if not contacts:
            return {"success": False, "error": "No emergency contacts found for this user."}
        
        # 2. Sort contacts by priority (1 being highest priority)
        # Assumes your database stores a numeric 'priority' field
        contacts.sort(key=lambda x: x.get("priority", 99))
        
        notified_contacts = []

        # 3. Iterate through contacts to find the email and send the alert
        for contact in contacts:
            contact_email = contact.get("email")
            contact_name = contact.get("name", "Emergency Contact")
            
            if not contact_email:
                continue # Skip if this contact only has a phone number
                
            subject = "URGENT: RESCU Fall Detected"
            message = (
                f"Hello {contact_name},\n\n"
                f"This is an automated emergency alert from RESCU. "
                f"A fall has been detected for the user you are monitoring.\n\n"
                f"Last Known Location: {location_data}\n\n"
                f"Please check on them immediately or contact emergency services."
            )
            
            try:
                # 4. Publish the email alert to the SNS Topic
                # The subscriber filter policies in AWS would route it to the specific email
                sns_response = sns_client.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=subject,
                    Message=message,
                    # MessageAttributes can be used if you set up SNS Filter Policies 
                    # so only the specific contact's email gets this specific message
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
                
                # Based on your design doc: Wait 60 seconds before escalating to the next contact.
                # NOTE: For AWS Lambda, long time.sleep() calls consume billable execution time. 
                # For production, consider using AWS Step Functions to manage this 60-second wait state.
                time.sleep(10)

            except ClientError as sns_err:
                print(f"Failed to send SNS to {contact_email}: {sns_err}")
                continue # Try the next contact if this one fails
                
        if not notified_contacts:
             return {"success": False, "error": "Loop finished, but no valid emails could be notified."}
             
        return {"success": True, "notified": notified_contacts}

    except ClientError as e:
        print(f"DynamoDB Query Error: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}