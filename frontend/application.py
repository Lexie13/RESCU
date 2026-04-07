from flask import Flask, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
import os
import requests

app = Flask(__name__)
application = app
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "https://mi8iapyuya.execute-api.us-east-1.amazonaws.com")

# =========================
# OAUTH SETUP
# =========================
oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID", "your-google-client-id"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "your-google-client-secret"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    client_kwargs={'scope': 'openid email profile'}
)

microsoft = oauth.register(
    name='microsoft',
    client_id=os.environ.get("MICROSOFT_CLIENT_ID", "your-microsoft-client-id"),
    client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET", "your-microsoft-client-secret"),
    access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
    authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    api_base_url='https://graph.microsoft.com/v1.0/',
    client_kwargs={'scope': 'User.Read'}
)

@app.route('/')
def index():
    return render_template('login.html')

# =========================
# SIGNUP ROUTES
# =========================
@app.route('/signup', methods=['GET'])
def signup_page():
    return render_template('signup.html')

@app.route('/signup', methods=['POST'])
def signup():
    # 1. Temporarily store page 1 data in the session
    session['temp_signup_data'] = {
        "username": request.form.get('username'),
        "password": request.form.get('password'),
        "first_name": request.form.get('first_name'),
        "last_name": request.form.get('last_name'),
        "phone": request.form.get('phone'),
        "email": request.form.get('email'),
        "role": request.form.get('role', 'owner')
    }

    if not session['temp_signup_data']['username'] or not session['temp_signup_data']['password']:
        return "Please enter both username and password."

    return redirect(url_for('signup_emergency'))

@app.route('/signup-emergency', methods=['GET', 'POST'])
def signup_emergency():
    # Ensure they came from the first signup page
    if 'temp_signup_data' not in session:
        return redirect(url_for('signup_page'))

    if request.method == 'POST':
        # 2. Collect contacts from page 2
        contacts_list = []
        for i in range(1, 6):
            name = request.form.get(f'contact_name_{i}')
            # NOTE: Your HTML needs to ask for contact_email_X instead of phone for AWS SNS
            email = request.form.get(f'contact_email_{i}') 
            if name and email:
                contacts_list.append({"name": name, "email": email, "priority": i})

        # 3. Combine everything and send to the backend
        payload = session['temp_signup_data']
        payload['emergency_contacts'] = contacts_list

        try:
            response = requests.put(f"{API_GATEWAY_URL}/login", json=payload)
            data = response.json()
            
            if response.status_code == 201:
                # Cleanup, log in, and redirect
                session.pop('temp_signup_data', None)
                session['username'] = payload['username']
                session['user_id'] = data.get('user_id')
                
                # We need to fetch the profile data so the dashboard loads correctly
                login_response = requests.post(f"{API_GATEWAY_URL}/login", json={
                    "username": payload['username'],
                    "password": payload['password']
                })
                if login_response.status_code == 200:
                    session['profile'] = login_response.json().get('profile', {})

                return redirect(url_for('home'))
            else:
                return f"Registration failed: {data.get('error', 'Unknown error')}"
        except Exception as e:
            return f"Backend connection failed: {str(e)}"

    return render_template('signup_emergency.html')

# =========================
# LOGIN / LOGOUT
# =========================
@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    try:
        response = requests.post(f"{API_GATEWAY_URL}/login", json={
            "username": username,
            "password": password
        })
        
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            session['token'] = data['token']
            session['username'] = username
            session['user_id'] = data['user_id']
            session['profile'] = data.get('profile', {})
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error=data.get('error', 'Invalid credentials'))
            
    except Exception as e:
        return f"Backend connection failed: {str(e)}"

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- OAuth Routes (UI preserved, requires future backend linking) ---
@app.route('/login/google')
def login_google():
    redirect_uri = url_for('google_auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def google_auth():
    token = google.authorize_access_token()
    user_info = google.get('userinfo').json()
    
    # Send OAuth data to API Gateway
    try:
        response = requests.post(f"{API_GATEWAY_URL}/oauth-login", json={
            "email": user_info.get('email'),
            "first_name": user_info.get('given_name', ''),
            "last_name": user_info.get('family_name', '')
        })
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            session['token'] = data['token']
            session['username'] = user_info.get('email')
            session['user_id'] = data['user_id']
            session['profile'] = data.get('profile', {})
        else:
            flash("Google Login Failed.", "error")
    except Exception as e:
        print(f"OAuth Backend Error: {e}")
        
    return redirect(url_for('home'))

@app.route('/login/microsoft')
def login_microsoft():
    redirect_uri = url_for('microsoft_auth', _external=True)
    return microsoft.authorize_redirect(redirect_uri)

@app.route('/auth/microsoft')
def microsoft_auth():
    token = microsoft.authorize_access_token()
    resp = microsoft.get('me')
    user_info = resp.json()

    user_email = user_info.get('userPrincipalName')
    
    # Send OAuth data to API Gateway
    try:
        response = requests.post(f"{API_GATEWAY_URL}/oauth-login", json={
            "email": user_email,
            "first_name": user_info.get('givenName', ''),
            "last_name": user_info.get('surname', '')
        })
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            session['token'] = data['token']
            session['username'] = user_email
            session['user_id'] = data['user_id']
            session['profile'] = data.get('profile', {})
        else:
            flash("Microsoft Login Failed.", "error")
    except Exception as e:
        print(f"OAuth Backend Error: {e}")
        
    return redirect(url_for('home'))

# =========================
# DASHBOARD & CONTACTS
# =========================
@app.route('/home')
def home():
    if 'username' not in session:
        return redirect(url_for('index'))

    profile = session.get('profile', {})
    email = profile.get('email', session['username'])
    device_info = {"battery": "--", "status": "Disconnected"}

    return render_template('home.html',
                            username=session['username'],
                            email=email,
                            device=device_info)

@app.route('/edit-emergency-contacts', methods=['GET', 'POST'])
def edit_emergency_contacts():
    if 'username' not in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        names = request.form.getlist('contact_name')
        emails = request.form.getlist('contact_email') 

        new_contacts = []
        for i, (name, email) in enumerate(zip(names, emails), start=1):
            if name.strip() and email.strip():
                new_contacts.append({"name": name, "email": email, "priority": i})

        # Send update to API Gateway
        try:
            requests.patch(f"{API_GATEWAY_URL}/user", json={
                "user_id": session.get('user_id'),
                "emergency_contacts": new_contacts
            })
            
            # Update session locally so UI reflects changes immediately
            session['profile']['emergency_contacts'] = new_contacts
            session.modified = True
            
        except Exception as e:
            print(f"Failed to update contacts: {e}")

        return redirect(url_for('edit_emergency_contacts'))

    user_contacts = session.get('profile', {}).get('emergency_contacts', [])
    return render_template('emergency_contacts.html', contacts=user_contacts)

# =========================
# OTHER ROUTES
# =========================
@app.route('/fall-history')
def fall_history():
    return "Fall History Page"

@app.route('/device-status')
def device_status():
    return "Device Status Page"

@app.route('/edit-profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('index'))

    profile = session.get('profile', {})

    if request.method == 'POST':
        updated_profile = {
            "first_name": request.form.get('first_name', profile.get('first_name', '')).strip(),
            "last_name": request.form.get('last_name', profile.get('last_name', '')).strip(),
            "phone": request.form.get('phone', profile.get('phone', '')).strip(),
            "email": request.form.get('email', profile.get('email', '')).strip(),
            "role": request.form.get('role', profile.get('role', 'owner'))
        }

        # Handle password change if requested
        new_password = request.form.get('new_password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()
        
        if new_password:
            if new_password == confirm:
                updated_profile['password'] = new_password
            else:
                return render_template('edit_profile.html', username=session['username'], user=profile, error="Passwords do not match.")

        # Send update to API Gateway
        try:
            requests.patch(f"{API_GATEWAY_URL}/user", json={
                "user_id": session.get('user_id'),
                "profile_updates": updated_profile
            })
            
            # Update session
            session['profile'].update(updated_profile)
            session.modified = True
        except Exception as e:
            print(f"Failed to update profile: {e}")

        return redirect(url_for('edit_profile'))

    return render_template('edit_profile.html', username=session['username'], user=profile)

if __name__ == "__main__":
    app.run(debug=True)