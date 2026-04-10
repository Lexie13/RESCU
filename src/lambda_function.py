import json
from decimal import Decimal
from user_service import (
    put_new_user,
    authenticate_user,
    delete_user,
    update_user,
    authenticate_oauth_user,
)
from alert_service import trigger_emergency_email_loop, acknowledge_alert


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)


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
        if method == "PUT" and "login" in path.lower():
            username = body.get("username")
            password = body.get("password")
            first_name = body.get("first_name")
            last_name = body.get("last_name")
            phone = body.get("phone")
            email = body.get("email")
            role = body.get("role", "primary_user")

            emergency_contacts = body.get("emergency_contacts", [])

            if not all([username, password, first_name, last_name, phone, email]):
                return {
                    "statusCode": 400,
                    "body": json.dumps("Missing required registration fields"),
                }

            result = put_new_user(
                username,
                password,
                first_name,
                last_name,
                phone,
                email,
                role,
                emergency_contacts,
            )
            return {
                "statusCode": 201 if result["success"] else 400,
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: Login (POST /login)
        elif method == "POST" and "login" in path.lower():
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
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: Trigger Fall Alert (POST /alert)
        elif method == "POST" and "alert" in path.lower():
            user_id = body.get("user_id")
            location = body.get("location", "Location Unavailable")

            if not user_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps("user_id required to trigger alert"),
                }

            result = trigger_emergency_email_loop(user_id, location)
            return {
                "statusCode": 200 if result["success"] else 500,
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: Update User Profile & Contacts (PATCH /user)
        elif method == "PATCH" and "user" in path.lower():
            user_id = body.get("user_id")
            if not user_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps("user_id required for update"),
                }

            emergency_contacts = body.get("emergency_contacts")
            profile_updates = body.get("profile_updates")

            result = update_user(user_id, emergency_contacts, profile_updates)
            return {
                "statusCode": 200 if result.get("success") else 500,
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: OAuth Login/Signup (POST /oauth-login)
        elif method == "POST" and "oauth-login" in path.lower():
            email = body.get("email")
            first_name = body.get("first_name", "")
            last_name = body.get("last_name", "")

            if not email:
                return {
                    "statusCode": 400,
                    "body": json.dumps("email required for OAuth login"),
                }

            result = authenticate_oauth_user(email, first_name, last_name)
            return {
                "statusCode": 200 if result.get("success") else 500,
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: Delete User (DELETE /user)
        elif method == "DELETE" and "user" in path.lower():
            user_id = body.get("user_id")
            if not user_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps("user_id required for deletion"),
                }

            result = delete_user(user_id)
            return {
                "statusCode": 200 if result["success"] else 500,
                "body": json.dumps(result, cls=DecimalEncoder),
            }

        # ROUTE: Acknowledge Alert (GET /alert/acknowledge)
        elif method == "GET" and "alert/acknowledge" in path.lower():
            query_params = event.get("queryStringParameters") or {}
            alert_id = query_params.get("alert_id")
            contact_email = query_params.get("email", "Unknown")

            if not alert_id:
                return {"statusCode": 400, "body": "Missing alert_id"}

            result = acknowledge_alert(alert_id, contact_email)

            if result.get("success"):
                html_body = """
                <html><body>
                <h2 style="color: green;">Alert Acknowledged</h2>
                <p>Thank you. The RESCU system has recorded that you are
                handling this emergency.</p>
                <p>The notification loop has been stopped.</p>
                </body></html>
                """
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html"},
                    "body": html_body,
                }
            else:
                return {"statusCode": 500, "body": "Failed to acknowledge alert."}

        # DEFAULT ROUTE: Handle unmatched paths/methods
        return {
            "statusCode": 404,
            "body": json.dumps(
                {"error": "Resource not found", "path": path, "method": method}
            ),
        }

    except Exception as e:
        print(f"Handler Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"Internal Server Error: {str(e)}"),
        }
