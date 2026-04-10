from flask import Flask, render_template, request, redirect, url_for, session
import os
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
        "username":   request.form.get("username"),
        "password":   request.form.get("password"),
        "first_name": request.form.get("first_name"),
        "last_name":  request.form.get("last_name"),
        "email":      request.form.get("email"),
        "role":       request.form.get("role", "owner"),
    }

    if not session["temp_signup_data"]["username"] or not session["temp_signup_data"]["password"]:
        return render_template("signup.html", error="Please enter both username and password.")

    return redirect(url_for("signup_emergency"))

@app.route("/signup-emergency", methods=["GET", "POST"])
def signup_emergency():
    if "temp_signup_data" not in session:
        return redirect(url_for("signup_page"))

    if request.method == "POST":
        contacts_list = []
        for i in range(1, 6):
            name  = request.form.get(f"contact_name_{i}")
            email = request.form.get(f"contact_email_{i}")
            if name and email:
                contacts_list.append({"name": name, "email": email, "priority": i})

        payload = session["temp_signup_data"]
        payload["emergency_contacts"] = contacts_list
        
        # FIX: satisfy the backend API mandatory field requirement
        payload["phone"] = "000-000-0000" 

        try:
            response = requests.put(f"{API_GATEWAY_URL}/login", json=payload)
            status   = response.status_code
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
                session["user_id"]  = data.get("user_id")

                try:
                    login_response = requests.post(
                        f"{API_GATEWAY_URL}/login",
                        json={"username": payload["username"], "password": payload["password"]},
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
            return render_template("signup_emergency.html", error=f"Request failed: {str(e)}")

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
            session["token"]    = data["token"]
            session["username"] = username
            session["user_id"]  = data["user_id"]
            session["profile"]  = data.get("profile", {})
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error=data.get("error", "Invalid credentials"))

    except Exception as e:
        return render_template("login.html", error=f"Backend connection failed: {str(e)}")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# =========================
# DASHBOARD
# =========================
@app.route("/home")
def home():
    if "username" not in session:
        return redirect(url_for("index"))

    profile     = session.get("profile", {})
    email       = profile.get("email", session["username"])
    device_info = {"battery": "--", "status": "Disconnected"}

    return render_template("home.html", username=session["username"], email=email, device=device_info)


# =========================
# EMERGENCY CONTACTS
# =========================
@app.route("/edit-emergency-contacts", methods=["GET", "POST"])
def edit_emergency_contacts():
    if "username" not in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        names  = request.form.getlist("contact_name")
        emails = request.form.getlist("contact_email")

        new_contacts = [
            {"name": name, "email": email, "priority": i}
            for i, (name, email) in enumerate(zip(names, emails), start=1)
            if name.strip() and email.strip()
        ]

        try:
            requests.patch(
                f"{API_GATEWAY_URL}/user",
                json={"user_id": session.get("user_id"), "emergency_contacts": new_contacts},
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
            "first_name": request.form.get("first_name", profile.get("first_name", "")).strip(),
            "last_name":  request.form.get("last_name",  profile.get("last_name",  "")).strip(),
            "email":      request.form.get("email",      profile.get("email",      "")).strip(),
            "role":       request.form.get("role",       profile.get("role", "owner")),
        }

        new_password = request.form.get("new_password", "").strip()
        confirm      = request.form.get("confirm_password", "").strip()

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
                json={"user_id": session.get("user_id"), "profile_updates": updated_profile},
            )
            session["profile"].update(updated_profile)
            session.modified = True
        except Exception as e:
            print(f"Failed to update profile: {e}")

        return redirect(url_for("edit_profile"))

    return render_template("edit_profile.html", username=session["username"], user=profile)


# =========================
# STUB ROUTES
# =========================
@app.route("/fall-history")
def fall_history():
    return "Fall History Page"


@app.route("/device-status")
def device_status():
    return "Device Status Page"


if __name__ == "__main__":
    app.run(debug=True)
