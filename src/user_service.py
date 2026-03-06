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
    # 1. Generate unique key for both entries
    user_id = str(uuid.uuid4())
    
    # 2. Hash password for 'logins' table
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), salt)

    # 3. Prepare items
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
        # Save to logins table
        table_logins.put_item(
            Item=login_item, 
            ConditionExpression="attribute_not_exists(user_id)"
        )
        
        # Save to users table
        table_users.put_item(Item=user_profile_item)
        
        return {"success": True, "user_id": user_id}
    except ClientError as e:
        print(f"Error adding user: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}


def authenticate_user(username, password):
    """
    Checks credentials using a GSI query and returns a JWT token if valid.
    """
    try:
        # Query the GSI 'username-index' to find the user efficiently
        response = table_logins.query(
            IndexName="username-index",
            KeyConditionExpression=Key("username").eq(username),
        )
        items = response.get("Items", [])

        if not items:
            return {"success": False, "error": "Incorrect username or password"}

        user = items[0]
        stored_hash = user["password"].encode("utf-8")

        # Verify entered password against the stored bcrypt hash
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            token = jwt.encode(
                {
                    "user_id": user["user_id"],
                    "username": user["username"],
                    "role": user.get("role", "primary_user"),
                    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
                },
                SECRET_KEY,
                algorithm="HS256",
            )

            return {"success": True, "token": token, "user_id": user["user_id"]}

        return {"success": False, "error": "Incorrect username or password"}
    except Exception as e:
        print(f"Auth error: {str(e)}")
        return {"success": False, "error": "Internal authentication error"}


def delete_user(user_id):
    """
    Deletes a user entry from the database using their unique user_id.
    """
    try:
        table_logins.delete_item(Key={"user_id": user_id})
        return {"success": True}
    except ClientError as e:
        print(f"Delete error: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}
