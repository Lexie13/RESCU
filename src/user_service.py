import boto3
import bcrypt
import uuid
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('logins')

def put_new_user(username, password, role='primary_user'):
    """
    Creates a new user record in DynamoDB with a hashed password.
    """
    # Hash password 
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)

    # Generate a unique key for the primary user
    user_id = str(uuid.uuid4())

    user_item = {
        'user_id': user_id,
        'username': username,
        'password': hashed_password.decode('utf-8'),
        'role': role
    }

    try:
        # Save information to database 
        table.put_item(Item=user_item)
        return {"success": True, "user_id": user_id}
    except ClientError as e:
        print(f"Error adding user: {e.response['Error']['Message']}")
        return {"success": False, "error": str(e)}