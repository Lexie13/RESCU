from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import format_text
import requests

app = Flask(__name__)
application = app
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
API_GATEWAY_URL = os.environ.get(
    "API_GATEWAY_URL", "https://mi8iapyuya.execute-api.us-east-1.amazonaws.com"
)


@app.route("/")
def index():
    return render_template("login.html")


# =========================
# SIGNUP ROUTES
# =========================
@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if request.method == "GET":
        session.pop("temp_signup_data", None)
        return render_template("signup.html")

    session["temp_signup_data"] = {
        "username": request.form.get("username"),
        "password": request.form.get("password"),
        "first_name": request.form.get("first_name"),
        "last_name": request.form.get("last_name"),
        "email": request.form.get("email"),
        "role": request.form.get("role", "owner"),
    }

    if (
        not session["temp_signup_data"]["username"]
        or not session["temp_signup_data"]["password"]
    ):
        return render_template(
            "signup.html", error="Please enter both username and password."
        )

    return redirect(url_for("signup_emergency"))


@app.route("/signup-emergency", methods=["GET", "POST"])
def signup_emergency():
    if "temp_signup_data" not in session:
        return redirect(url_for("signup_page"))

    if request.method == "POST":
        contacts_list = []
        for i in range(1, 6):
            name = request.form.get(f"contact_name_{i}")
            email = request.form.get(f"contact_email_{i}")
            if name and email:
                contacts_list.append({"name": name, "email": email, "priority": i})

        payload = session["temp_signup_data"]
        payload["emergency_contacts"] = contacts_list
        payload["phone"] = "000-000-0000"

        try:
            response = requests.put(f"{API_GATEWAY_URL}/login", json=payload)
            status = response.status_code
            raw_body = response.text

            try:
                data = response.json()
            except Exception:
                data = {}

            if not isinstance(data, dict):
                data = {"message": str(data)}

            if status in (200, 201):
                session.pop("temp_signup_data", None)
                session["username"] = payload["username"]
                session["user_id"] = data.get("user_id")

                try:
                    login_response = requests.post(
                        f"{API_GATEWAY_URL}/login",
                        json={
                            "username": payload["username"],
                            "password": payload["password"],
                        },
                    )
                    if login_response.status_code == 200:
                        login_data = login_response.json()
                        if isinstance(login_data, dict):
                            session["profile"] = login_data.get("profile", {})
                except Exception:
                    session["profile"] = {}

                return redirect(url_for("home"))
            else:
                debug_msg = f"Status: {status} | Body: {raw_body}"
                return render_template("signup_emergency.html", error=debug_msg)

        except Exception as e:
            return render_template(
                "signup_emergency.html", error=f"Request failed: {str(e)}"
            )

    return render_template("signup_emergency.html")


# =========================
# LOGIN / LOGOUT
# =========================
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    try:
        response = requests.post(
            f"{API_GATEWAY_URL}/login",
            json={"username": username, "password": password},
        )

        try:
            data = response.json()
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        if response.status_code == 200 and data.get("success"):
            session["token"] = data["token"]
            session["username"] = username
            session["user_id"] = data["user_id"]
            session["profile"] = data.get("profile", {})
            return redirect(url_for("home"))
        else:
            return render_template(
                "login.html", error=data.get("error", "Invalid credentials")
            )

    except Exception as e:
        return render_template(
            "login.html", error=f"Backend connection failed: {str(e)}"
        )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# =========================
# DASHBOARD
# =========================
@app.route("/home")
def home():
    if not session.get("username"):
        return redirect(url_for("index"))

    if request.headers.get("Sec-Fetch-Dest") != "iframe":
        settings = session.get("profile", {}).get("device_settings", {})
        return render_template(
            "parent_page.html",
            user_id=session.get("user_id"),
            fall_delay=settings.get("fall_delay", 5),
        )

    user_data = session.get("profile", {})
    return render_template(
        "home.html",
        username=session.get("username"),
        email=user_data.get("email"),
        device={"battery": "--", "status": "Disconnected"},
    )


@app.route("/test-alert", methods=["POST"])
def test_alert():
    if "user_id" not in session:
        return redirect(url_for("index"))

    payload = {
        "user_id": session["user_id"],
        "location": "Manual Test from Web Dashboard",
    }

    try:
        response = requests.post(f"{API_GATEWAY_URL}/alert", json=payload)
        if response.status_code == 200:
            flash("Emergency loop triggered successfully! Check your email.", "success")
        else:
            flash(f"Failed to trigger loop: {response.text}", "error")
    except Exception as e:
        flash(f"Error connecting to alert service: {str(e)}", "error")

    return redirect(url_for("home"))


# =========================
# EMERGENCY CONTACTS
# =========================
@app.route("/edit-emergency-contacts", methods=["GET", "POST"])
def edit_emergency_contacts():
    if "username" not in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        names = request.form.getlist("contact_name")
        emails = request.form.getlist("contact_email")

        new_contacts = [
            {"name": name, "email": email, "priority": i}
            for i, (name, email) in enumerate(zip(names, emails), start=1)
            if name.strip() and email.strip()
        ]

        try:
            requests.patch(
                f"{API_GATEWAY_URL}/user",
                json={
                    "user_id": session.get("user_id"),
                    "emergency_contacts": new_contacts,
                },
            )
            session["profile"]["emergency_contacts"] = new_contacts
            session.modified = True
        except Exception as e:
            print(f"Failed to update contacts: {e}")

        return redirect(url_for("edit_emergency_contacts"))

    user_contacts = session.get("profile", {}).get("emergency_contacts", [])
    return render_template("emergency_contacts.html", contacts=user_contacts)


# =========================
# EDIT PROFILE
# =========================
@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    if "username" not in session:
        return redirect(url_for("index"))

    profile = session.get("profile", {})

    if request.method == "POST":
        updated_profile = {
            "first_name": request.form.get(
                "first_name", profile.get("first_name", "")
            ).strip(),
            "last_name": request.form.get(
                "last_name", profile.get("last_name", "")
            ).strip(),
            "email": request.form.get("email", profile.get("email", "")).strip(),
            "role": request.form.get("role", profile.get("role", "owner")),
        }

        new_password = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()

        if new_password:
            if new_password == confirm:
                updated_profile["password"] = new_password
            else:
                return render_template(
                    "edit_profile.html",
                    username=session["username"],
                    user=profile,
                    error="Passwords do not match.",
                )

        try:
            requests.patch(
                f"{API_GATEWAY_URL}/user",
                json={
                    "user_id": session.get("user_id"),
                    "profile_updates": updated_profile,
                },
            )
            session["profile"].update(updated_profile)
            session.modified = True
        except Exception as e:
            print(f"Failed to update profile: {e}")

        return redirect(url_for("edit_profile"))

    return render_template(
        "edit_profile.html", username=session["username"], user=profile
    )


# =========================
# DEVICE SETTINGS
# =========================
@app.route("/device-status", methods=["GET", "POST"])
def device_status():
    if "username" not in session:
        return redirect(url_for("index"))

    # Ensure device_settings exists in the session profile
    if "device_settings" not in session["profile"]:
        session["profile"]["device_settings"] = {
            "device_name": "RESCU-Wearable",
            "fall_delay": 5,
        }

    if request.method == "POST":
        data = request.json

        # Update session with new settings
        if "device_name" in data:
            session["profile"]["device_settings"]["device_name"] = data["device_name"]
        if "fall_delay" in data:
            session["profile"]["device_settings"]["fall_delay"] = int(
                data["fall_delay"]
            )

        session.modified = True

        # Sync settings to the backend API Gateway
        try:
            requests.patch(
                f"{API_GATEWAY_URL}/user",
                json={
                    "user_id": session.get("user_id"),
                    "device_settings": session["profile"]["device_settings"],
                },
            )
        except Exception as e:
            print(f"Failed to sync device settings: {e}")
            return {"status": "error", "message": str(e)}, 500

        return {"status": "success"}, 200

    # GET Request: Pass data to the template
    settings = session["profile"].get("device_settings", {})
    return render_template(
        "device_settings.html",
        device_name=settings.get("device_name", "RESCU-Wearable"),
        fall_delay=settings.get("fall_delay", 5),
    )


@app.route("/process-fall", methods=["POST"])
def process_fall():
    if "user_id" not in session:
        return {"status": "error", "message": "User not logged in"}, 401

    data = request.json
    # Generate the CAP XML string using the utility function
    cap_xml = format_text.get_cap_xml_for_current_alert(data["mcu"], data["location"])

    # Prepare the payload for the backend /alert endpoint
    payload = {
        "user_id": session["user_id"],
        "location": data.get("location", "Unknown Location"),
        "cap_xml": cap_xml,  # Send the raw XML string to be stored and parsed by the backend
    }

    try:
        # Forward to the API Gateway /alert endpoint (same as test_alert)
        response = requests.post(f"{API_GATEWAY_URL}/alert", json=payload)
        if response.status_code == 200:
            resp_data = response.json() if response.text else {}
            return {
                "status": "processed",
                "message": "Emergency alert triggered successfully",
                "alert_id": resp_data.get("alert_id"),
            }, 200
        else:
            return {
                "status": "error",
                "message": f"Backend failed: {response.text}",
            }, response.status_code
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}, 500


@app.route("/cancel-alert", methods=["POST"])
def cancel_alert():
    if "user_id" not in session:
        return {"status": "error", "message": "Unauthorized"}, 401

    data = request.json
    alert_id = data.get("alert_id")
    if not alert_id:
        return {"status": "error", "message": "alert_id required"}, 400

    try:
        response = requests.post(
            f"{API_GATEWAY_URL}/alert/cancel",
            json={"alert_id": alert_id}
        )
        return {"status": "cancelled"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/delete-account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return {"status": "error", "message": "Unauthorized"}, 401

    try:
        # Assuming your API Gateway handles DELETE for the user
        response = requests.delete(
            f"{API_GATEWAY_URL}/user", json={"user_id": session.get("user_id")}
        )

        if response.status_code in (200, 204):
            session.clear()
            return {"status": "success"}, 200
        else:
            return {"status": "error", "message": "Backend deletion failed"}, 500
    except Exception as e:
        print(f"Delete failed: {e}")
        return {"status": "error", "message": str(e)}, 500


# =========================
# EMERGENCY CONTACTS
# =========================
@app.route("/fall-history")
def fall_history():
    if "user_id" not in session:
        return redirect(url_for("index"))

    user_id = session.get("user_id")

    try:
        # Request alerts for the specific user from your API Gateway
        # Assuming your API has a GET /alert endpoint that takes a user_id
        response = requests.get(f"{API_GATEWAY_URL}/alert", params={"user_id": user_id})

        if response.status_code == 200:
            alerts = response.json()  # This should be a list of alert objects
        else:
            print(f"Failed to fetch alerts: {response.text}")
            alerts = []

    except Exception as e:
        print(f"Error connecting to alert service: {e}")
        alerts = []

    # Sort alerts by date (newest first) if not already sorted by the backend
    if alerts:
        alerts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return render_template("fall_history.html", alerts=alerts)


if __name__ == "__main__":
    app.run(debug=True)
