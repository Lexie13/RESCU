import boto3
import os
import time
import uuid
import datetime
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table_users = dynamodb.Table("users")
table_alerts = dynamodb.Table("alerts")
sns_client = boto3.client("sns")

SNS_TOPIC_ARN = os.environ.get(
    "EMERGENCY_SNS_TOPIC_ARN", 
    "arn:aws:sns:us-east-1:123456789012:RESCU_Alerts"
)
API_GATEWAY_URL = os.environ.get(
    "API_GATEWAY_URL", "https://mi8iapyuya.execute-api.us-east-1.amazonaws.com"
)


def trigger_emergency_email_loop(user_id, location_data="No Location"):
    try:
        response = table_users.get_item(Key={"user_id": user_id})
        user_profile = response.get("Item")

        if not user_profile:
            return {"success": False, 
                    "error": "User profile not found in database."}

        contacts = user_profile.get("emergency_contacts", [])
        if not contacts:
            return {
                "success": False,
                "error": "No emergency contacts found for this user.",
            }

        parsed_contacts = []
        for item in contacts:
            contact_map = (
                item.get("M", item) if isinstance(item, dict) else item
            )

            raw_email = contact_map.get("email")
            contact_email = (
                raw_email.get("S") if 
                isinstance(raw_email, dict) else raw_email
            )

            raw_name = contact_map.get("name")
            contact_name = (
                raw_name.get("S") if isinstance(raw_name, dict) else raw_name
            )

            raw_priority = contact_map.get("priority", 99)
            priority = (
                int(raw_priority.get("N", 99))
                if isinstance(raw_priority, dict)
                else int(raw_priority)
            )

            if contact_email:
                parsed_contacts.append(
                    {"name": contact_name, "email": contact_email, 
                     "priority": priority}
                )

        parsed_contacts.sort(key=lambda x: x.get("priority", 99))

        # 1. CREATE THE ALERT RECORD
        alert_id = str(uuid.uuid4())
        table_alerts.put_item(
            Item={
                "alert_id": alert_id,
                "user_id": user_id,
                "status": "PENDING",
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
        )

        notified_contacts = []
        is_acknowledged = False

        # 2. ITERATE AND SEND
        for contact in parsed_contacts:
            contact_email = contact["email"]
            contact_name = contact["name"] or "Emergency Contact"

            # The link the contact will click
            ack_link = (
                f"{API_GATEWAY_URL}/alert/acknowledge?"
                f"alert_id={alert_id}&email={contact_email}"
            )

            subject = "URGENT: RESCU Fall Detected - Action Required"
            message = (
                f"Hello {contact_name},\n\n"
                f"This is an automated emergency alert from RESCU. "
                f"A fall has been detected for the user you are "
                f"monitoring.\\n\\n"
                f"Last Known Location: {location_data}\n\n"
                f"PLEASE CLICK THE LINK BELOW TO ACKNOWLEDGE YOU ARE "
                f"HANDLING THIS:\n{ack_link}\n\n"
                f"If you do not acknowledge this within 60 seconds, we will "
                f"notify the next contact."
            )

            try:
                sns_client.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=subject,
                    Message=message,
                    MessageAttributes={
                        "target_email": {
                            "DataType": "String",
                            "StringValue": contact_email,
                        }
                    },
                )
                notified_contacts.append(contact_email)
                print(
                    f"Alert sent to {contact_email}. " 
                    f"Waiting for acknowledgment..."
                )

                # 3. POLL THE DATABASE FOR ACKNOWLEDGMENT
                wait_time_seconds = 60
                poll_interval = 5
                iterations = wait_time_seconds // poll_interval

                for _ in range(iterations):
                    time.sleep(poll_interval)

                    # Check if status changed
                    alert_record = table_alerts.get_item(
                        Key={"alert_id": alert_id}
                    ).get("Item")
                    if alert_record and alert_record.get("status") == "ACKNOWLEDGED":
                        is_acknowledged = True
                        break  # Break the polling loop

                if is_acknowledged:
                    print(f"Alert {alert_id} acknowledged! Stopping loop.")
                    break  # Break the contact list loop entirely

            except ClientError as sns_err:
                print(f"Failed to send SNS to {contact_email}: {sns_err}")
                continue

        if is_acknowledged:
            return {
                "success": True,
                "message": "Alert acknowledged",
                "notified": notified_contacts,
            }
        else:
            return {
                "success": False,
                "error": ("Loop finished, but no contact acknowledged the alert."),
            }

    except ClientError as e:
        return {"success": False, "error": str(e)}


def acknowledge_alert(alert_id, contact_email):
    """
    Updates the alert status to ACKNOWLEDGED.
    """
    try:
        table_alerts.update_item(
            Key={"alert_id": alert_id},
            UpdateExpression=(
                "SET #st = :st, acknowledged_by = :ack, " "acknowledged_at = :time"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":st": "ACKNOWLEDGED",
                ":ack": contact_email,
                ":time": datetime.datetime.utcnow().isoformat(),
            },
        )
        return {"success": True}
    except ClientError as e:
        return {"success": False, "error": str(e)}
