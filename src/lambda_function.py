import json
from user_service import put_new_user, authenticate_user, delete_user
from alert_service import trigger_emergency_email_loop


def lambda_handler(event, context):
    """
    RESCU API Entry Point. Routes requests based on HTTP Method and Path.
    """
    try:
        # Extract method and path
        method = event.get("httpMethod")
        path = event.get("path", "")

        if not method and "requestContext" in event:
            method = event["requestContext"].get("http", {}).get("method")
            path = event["requestContext"].get("http", {}).get("path", "")

        body_raw = event.get("body", "{}")
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw

        # ROUTE: Create User (PUT /login)
        if method == "PUT":
            username = body.get("username")
            password = body.get("password")
            first_name = body.get("first_name")
            last_name = body.get("last_name")
            phone = body.get("phone")
            email = body.get("email")
            role = body.get("role", "primary_user")
            
            # Extract emergency contacts (default to empty list if none provided)
            emergency_contacts = body.get("emergency_contacts", [])

            if not all([username, password, first_name, last_name, phone, email]):
                return {"statusCode": 400, "body": json.dumps("Missing required registration fields")}

            result = put_new_user(
                username, password, first_name, last_name, phone, email, role, emergency_contacts
            )
            
            return {
                "statusCode": 201 if result["success"] else 400,
                "body": json.dumps(result),
            }

        # ROUTE: Login (POST /login)
        elif method == "POST":
            username = body.get("username")
            password = body.get("password")

            if not username or not password:
                return {
                    "statusCode": 400,
                    "body": json.dumps("Username and password required"),
                }

            result = authenticate_user(username, password)
            return {
                "statusCode": 200 if result["success"] else 401,
                "body": json.dumps(result),
            }
        
        # ROUTE: Trigger Fall Alert (POST /alert)
        elif method == "POST" and "alert" in path.lower():
            user_id = body.get("user_id")
            location = body.get("location", "Location Unavailable")

            if not user_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps("user_id required to trigger alert")
                }

            result = trigger_emergency_email_loop(user_id, location)
            return {
                "statusCode": 200 if result["success"] else 500,
                "body": json.dumps(result),
            }

        # ROUTE: Delete User (DELETE /user)
        elif method == "DELETE":
            user_id = body.get("user_id")
            if not user_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps("user_id required for deletion"),
                }

            result = delete_user(user_id)
            return {
                "statusCode": 200 if result["success"] else 500,
                "body": json.dumps(result),
            }

        return {"statusCode": 405, "body": json.dumps(f"Method {method} Not Allowed")}

    except Exception as e:
        print(f"Handler Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps("Internal Server Error")}