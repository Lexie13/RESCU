from flask import Flask, render_template, request, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# --- OAuth Setup ---
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

# --- In-memory 'database' ---
users = {}  
tasks = {}  
emergency_contacts = {}

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
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        return "Please enter both username and password."

    if username in users:
        return "User already exists!"

    users[username] = {
        "password": password,
        "first_name": request.form.get('first_name'),
        "last_name": request.form.get('last_name'),
        "phone": request.form.get('phone'),
        "email": request.form.get('email'),
        "role": request.form.get('role')
    }
    tasks[username] = []
    emergency_contacts[username] = []
    session['user'] = username

    return redirect(url_for('signup_emergency'))

@app.route('/signup-emergency', methods=['GET', 'POST'])
def signup_emergency():
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))

    if request.method == 'POST':
        contacts_list = []
        for i in range(1, 6):
            name = request.form.get(f'contact_name_{i}')
            phone = request.form.get(f'contact_phone_{i}')
            if name and phone:
                contacts_list.append({"name": name, "phone": phone})
        
        emergency_contacts[username] = contacts_list
        return redirect(url_for('home'))

    return render_template('signup_emergency.html')

# =========================
# LOGIN / LOGOUT
# =========================
@app.route('/login/google')
def login_google():
    # 'google' matches the name used in oauth.register('google', ...)
    redirect_uri = url_for('google_auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def google_auth():
    token = google.authorize_access_token()
    user_info = google.get('userinfo').json()
    # Logic to handle the user (e.g., save to your 'users' dict and session)
    session['user'] = user_info['email']
    if user_info['email'] not in users:
        users[user_info['email']] = {"email": user_info['email'], "first_name": user_info.get('given_name')}
    
    return redirect(url_for('home'))

@app.route('/login/microsoft')
def login_microsoft():
    # Ensure this matches the redirect URI in your Azure Portal
    redirect_uri = url_for('microsoft_auth', _external=True)
    return microsoft.authorize_redirect(redirect_uri)

# 2. The route Microsoft sends the user back to
@app.route('/auth/microsoft')
def microsoft_auth():
    token = microsoft.authorize_access_token()
    # Fetch user data from Microsoft Graph API
    resp = microsoft.get('me')
    user_info = resp.json()
    
    # Simple logic to log them in to your session
    user_email = user_info.get('userPrincipalName')
    session['user'] = user_email
    
    # If they are a new user, add them to your 'users' dictionary
    if user_email not in users:
        users[user_email] = {
            "email": user_email,
            "first_name": user_info.get('givenName'),
            "last_name": user_info.get('surname')
        }
    
    return redirect(url_for('home'))


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    user = users.get(username)
    if user and user.get('password') == password:
        session['user'] = username
        return redirect(url_for('home'))

    return "Invalid username or password!"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# =========================
# DASHBOARD & CONTACTS
# =========================
@app.route('/home')
def home():
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))

    user_data = users.get(username, {})
    email = user_data.get('email', username)
    
    device_info = {"battery": "85%", "status": "Connected"}
    return render_template('home.html', 
                           username=username, 
                           email=email, 
                           device=device_info)

@app.route('/edit-emergency-contacts', methods=['GET', 'POST'])
def edit_emergency_contacts():
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))

    if request.method == 'POST':
        names = request.form.getlist('contact_name')
        phones = request.form.getlist('contact_phone')

        new_contacts = []
        for name, phone in zip(names, phones):
            if name.strip() and phone.strip():
                new_contacts.append({"name": name, "phone": phone})
        
        emergency_contacts[username] = new_contacts
        return redirect(url_for('edit_emergency_contacts'))

    user_contacts = emergency_contacts.get(username, [])
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
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))

    user = users.get(username, {})

    if request.method == 'POST':
        new_username = request.form.get('username', username).strip()

        # Handle username change
        if new_username != username:
            if new_username in users:
                return render_template('edit_profile.html', username=username, user=user, error="Username already taken.")
            users[new_username] = users.pop(username)
            emergency_contacts[new_username] = emergency_contacts.pop(username, [])
            session['user'] = new_username
            username = new_username
            user = users[username]

        # Update fields
        user['first_name'] = request.form.get('first_name', '').strip()
        user['last_name']  = request.form.get('last_name', '').strip()
        user['phone']      = request.form.get('phone', '').strip()
        user['email']      = request.form.get('email', '').strip()
        user['role']       = request.form.get('role', 'owner')

        # Password change (optional)
        new_password = request.form.get('new_password', '').strip()
        confirm      = request.form.get('confirm_password', '').strip()
        if new_password:
            if new_password == confirm:
                user['password'] = new_password
            else:
                return render_template('edit_profile.html', username=username, user=user, error="Passwords do not match.")

        return redirect(url_for('edit_profile'))

    return render_template('edit_profile.html', username=username, user=user)

# OAUTH CALLBACKS (Google/MS) remain as you had them...

if __name__ == "__main__":
    app.run(debug=True)