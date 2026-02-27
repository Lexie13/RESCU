import json
from user_service import put_new_user

def lambda_handler(event, context):
    """
    RESCU API Entry Point
    """
    try:
        http_method = event.get('httpMethod')
        body = json.loads(event.get('body', '{}'))

        if http_method == 'PUT':
            username = body.get('username')
            password = body.get('password')
            role = body.get('role', 'primary_user')

            if not username or not password:
                return {"statusCode": 400, "body": json.dumps("Missing credentials")}

            result = put_new_user(username, password, role)
            
            if result["success"]:
                return {
                    "statusCode": 201, 
                    "body": json.dumps({"message": "User added", "user_id": result["user_id"]})
                }
        
        return {"statusCode": 405, "body": json.dumps("Method Not Allowed")}

    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(str(e))}