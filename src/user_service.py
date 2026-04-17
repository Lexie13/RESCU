import boto3
import bcrypt
import uuid
import jwt
import datetime
import os
import json
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import Binary

# Configuration
region = os.environ.get("AWS_REGION", "us-east-1")
dynamodb = boto3.resource("dynamodb", region_name=region)
table_logins = dynamodb.Table("logins")
table_users = dynamodb.Table("users")

# Initialize SNS client
sns_client = boto3.client("sns", region_name=region)
SNS_TOPIC_ARN = os.environ.get(
    "EMERGENCY_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:RESCU_Alerts"
)

SECRET_KEY = os.environ.get("JWT_SECRET", "fallback-dev-secret-only")


def subscribe_email_to_alerts(email):
    """
    Subscribes a new email address to the SNS topic only if it doesn't exist.
    """
    try:
        # 1. List existing subscriptions for the topic
        paginator = sns_client.get_paginator("list_subscriptions_by_topic")
        iterator = paginator.paginate(TopicArn=SNS_TOPIC_ARN)

        for page in iterator:
            for sub in page.get("Subscriptions", []):
                # Check if the email is already registered (confirmed or pending)
                if sub["Endpoint"] == email:
                    print(f"Email {email} is already subscribed. Skipping.")
                    return

        # 2. Only subscribe if the email was not found in the list
        sns_client.subscribe(
            TopicArn=SNS_TOPIC_ARN,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": json.dumps({"target_email": [email]})},
        )
        print(f"New subscription request sent to {email}.")
    except Exception as e:
        print(f"SNS Subscription check/fail for {email}: {str(e)}")


def put_new_user(
    username,
    password,
    first_name,
    last_name,
    phone,
    email,
    role="primary_user",
    emergency_contacts=None,
):
    """
    Creates entries in both 'logins' and 'users' tables linked by
    a common user_id.
    """
    if emergency_contacts is None:
        emergency_contacts = []

    user_id = str(uuid.uuid4())
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), salt)

    login_item = {
        "user_id": user_id,
        "username": username,
        "password": Binary(hashed_password),  # Store as raw bytes wrapped in Binary
        "role": role,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

    user_profile_item = {
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone,
        "email": email,
        "emergency_contacts": emergency_contacts,
    }

    try:
        table_logins.put_item(
            Item=login_item, ConditionExpression="attribute_not_exists(user_id)"
        )
        table_users.put_item(Item=user_profile_item)

        # Subscribe each contact email provided during signup
        if emergency_contacts:
            for contact in emergency_contacts:
                contact_map = (
                    contact.get("M", contact) if isinstance(contact, dict) else contact
                )
                email_addr = contact_map.get("email")
                if isinstance(email_addr, dict):
                    email_addr = email_addr.get("S")

                if email_addr:
                    subscribe_email_to_alerts(email_addr)

        return {"success": True, "user_id": user_id}
    except ClientError as e:
        return {"success": False, "error": str(e)}


def authenticate_user(username, password):
    """
    Checks credentials and retrieves the linked profile data from
    the 'users' table.
    """
    try:
        # 1. Find the user in the logins table using the GSI
        response = table_logins.query(
            IndexName="username-index",
            KeyConditionExpression=Key("username").eq(username),
        )
        items = response.get("Items", [])

        if not items:
            return {"success": False, "error": "Incorrect username or password"}

        user_login = items[0]
        user_id = user_login["user_id"]

        # Handle both the new Binary format and legacy string format
        stored_password = user_login["password"]
        if hasattr(stored_password, "value"):
            stored_hash = stored_password.value  # Extract bytes from Binary
        elif isinstance(stored_password, str):
            stored_hash = stored_password.encode("utf-8")  # Fallback for old records
        else:
            stored_hash = stored_password

        # 2. Verify password
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            # 3. Retrieve profile data from the 'users' table
            profile_response = table_users.get_item(Key={"user_id": user_id})
            profile = profile_response.get("Item", {})

            token = jwt.encode(
                {
                    "user_id": user_id,
                    "username": user_login["username"],
                    "role": user_login.get("role", "primary_user"),
                    "exp": (datetime.datetime.utcnow() + datetime.timedelta(hours=24)),
                },
                SECRET_KEY,
                algorithm="HS256",
            )

            return {
                "success": True,
                "token": token,
                "user_id": user_id,
                "profile": profile,
            }

        return {"success": False, "error": "Incorrect username or password"}
    except Exception as e:
        print(f"Auth error: {str(e)}")
        return {"success": False, "error": "Internal authentication error"}


def delete_user(user_id):
    """
    Deletes the user from both the 'logins' and 'users' tables.
    """
    try:
        # Delete from security table
        table_logins.delete_item(Key={"user_id": user_id})

        # Delete from profile table
        table_users.delete_item(Key={"user_id": user_id})

        return {"success": True}
    except ClientError as e:
        print(f"Delete error: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}


def update_user(user_id, emergency_contacts=None, profile_updates=None):
    """
    Updates the user profile in 'users' and optionally the password in 'logins'.
    """
    try:
        # 1. Update Profile Information (users table)
        if emergency_contacts is not None or profile_updates is not None:
            update_expr_parts = []
            expr_attr_values = {}
            expr_attr_names = {}

            if emergency_contacts is not None:
                update_expr_parts.append("emergency_contacts = :ec")
                expr_attr_values[":ec"] = emergency_contacts

                # Trigger SNS subscriptions for the new contact list
                for contact in emergency_contacts:
                    contact_map = (
                        contact.get("M", contact)
                        if isinstance(contact, dict)
                        else contact
                    )
                    email_addr = contact_map.get("email")
                    if isinstance(email_addr, dict):
                        email_addr = email_addr.get("S")

                    if email_addr:
                        subscribe_email_to_alerts(email_addr)

            if profile_updates is not None:
                # Map frontend 'phone' to DynamoDB 'phone_number'
                for field in ["first_name", "last_name", "phone", "email"]:
                    db_field = "phone_number" if field == "phone" else field

                    if field in profile_updates:
                        # Use ExpressionAttributeNames to avoid reserved keyword conflicts
                        expr_attr_names[f"#{db_field}"] = db_field
                        update_expr_parts.append(f"#{db_field} = :{db_field}")
                        expr_attr_values[f":{db_field}"] = profile_updates[field]

            if update_expr_parts:
                update_kwargs = {
                    "Key": {"user_id": user_id},
                    "UpdateExpression": "SET " + ", ".join(update_expr_parts),
                    "ExpressionAttributeValues": expr_attr_values,
                }
                if expr_attr_names:
                    update_kwargs["ExpressionAttributeNames"] = expr_attr_names

                table_users.update_item(**update_kwargs)

        # 2. Update Password (logins table) if provided
        if profile_updates and "password" in profile_updates:
            new_password = profile_updates["password"]
            salt = bcrypt.gensalt()
            hashed_password = bcrypt.hashpw(new_password.encode("utf-8"), salt)

            table_logins.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET #pw = :pw",
                ExpressionAttributeNames={"#pw": "password"},
                ExpressionAttributeValues={":pw": Binary(hashed_password)},
            )

        return {"success": True}

    except ClientError as e:
        print(f"Update error: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}


def authenticate_oauth_user(email, first_name=None, last_name=None):
    """
    Authenticates an OAuth user. Creates a new profile if the email doesn't exist.
    """
    try:
        # Check if user already exists
        response = table_logins.query(
            IndexName="username-index",
            KeyConditionExpression=Key("username").eq(email),
        )
        items = response.get("Items", [])

        if items:
            # User exists
            user_login = items[0]
            user_id = user_login["user_id"]
        else:
            # User does not exist, create them with a dummy secure password
            random_password = str(uuid.uuid4())
            create_result = put_new_user(
                username=email,
                password=random_password,
                first_name=first_name or "",
                last_name=last_name or "",
                phone="",
                email=email,
                role="primary_user",
                emergency_contacts=[],
            )

            if not create_result.get("success"):
                return {"success": False, "error": "Failed to create OAuth user"}

            user_id = create_result["user_id"]
            user_login = {"username": email, "role": "primary_user"}

        # Retrieve profile data
        profile_response = table_users.get_item(Key={"user_id": user_id})
        profile = profile_response.get("Item", {})

        # Generate Token
        token = jwt.encode(
            {
                "user_id": user_id,
                "username": user_login["username"],
                "role": user_login.get("role", "primary_user"),
                "exp": (datetime.datetime.utcnow() + datetime.timedelta(hours=24)),
            },
            SECRET_KEY,
            algorithm="HS256",
        )

        return {"success": True, "token": token, "user_id": user_id, "profile": profile}

    except Exception as e:
        print(f"OAuth error: {str(e)}")
        return {"success": False, "error": "Internal authentication error"}
