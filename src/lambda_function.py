import json
from user_service import put_new_user

def lambda_handler(event, context):
    """
    RESCU API Entry Point
    """
    try:
        method = event.get('httpMethod')
        if not method and 'requestContext' in event:
            method = event['requestContext'].get('http', {}).get('method')
            
        body_raw = event.get('body', '{}')
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw

        print(f"Received {method} request with body: {body}")

        if method == 'PUT':
            username = body.get('username')
            password = body.get('password')
            role = body.get('role', 'primary_user')

            if not username or not password:
                return {"statusCode": 400, "body": json.dumps("Missing credentials")}

            result = put_new_user(username, password, role)
            
            if result["success"]:
                return {
                    "statusCode": 201, 
                    "body": json.dumps({
                        "message": "User added", 
                        "user_id": result["user_id"]
                    })
                }
        
        return {
            "statusCode": 405, 
            "body": json.dumps(f"Method {method} Not Allowed")
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps(str(e))}