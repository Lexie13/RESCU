import boto3
import bcrypt
import uuid
import jwt
import datetime
import os
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

# Configuration
dynamodb = boto3.resource("dynamodb")
table_logins = dynamodb.Table("logins")
table_users = dynamodb.Table("users")

SECRET_KEY = os.environ.get("JWT_SECRET", "fallback-dev-secret-only")

def put_new_user(username, password, first_name, last_name, phone, email, role="primary_user"):
    """
    Creates entries in both 'logins' and 'users' tables linked by a common user_id.
    """
    user_id = str(uuid.uuid4())
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), salt)

    login_item = {
        "user_id": user_id,
        "username": username,
        "password": hashed_password.decode("utf-8"),
        "role": role,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

    user_profile_item = {
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone,
        "email": email
    }

    try:
        table_logins.put_item(Item=login_item, ConditionExpression="attribute_not_exists(user_id)")
        table_users.put_item(Item=user_profile_item)
        return {"success": True, "user_id": user_id}
    except ClientError as e:
        return {"success": False, "error": str(e)}

def authenticate_user(username, password):
    """
    Checks credentials and retrieves the linked profile data from the 'users' table.
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
        stored_hash = user_login["password"].encode("utf-8")

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
                    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
                },
                SECRET_KEY,
                algorithm="HS256",
            )

            return {
                "success": True, 
                "token": token, 
                "user_id": user_id,
                "profile": profile # Includes first_name, last_name, phone, etc.
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