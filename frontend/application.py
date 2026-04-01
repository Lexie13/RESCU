from flask import Flask, render_template, request, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")  # change for production

# --- OAuth Setup ---
oauth = OAuth(app)

# Google OAuth
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID", "your-google-client-id"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "your-google-client-secret"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    client_kwargs={'scope': 'openid email profile'}
)

# Microsoft OAuth
microsoft = oauth.register(
    name='microsoft',
    client_id=os.environ.get("MICROSOFT_CLIENT_ID", "your-microsoft-client-id"),
    client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET", "your-microsoft-client-secret"),
    access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
    authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    api_base_url='https://graph.microsoft.com/v1.0/',
    client_kwargs={'scope': 'User.Read'}
)

# --- In-memory 'database' example ---
users = {}  # {username: password}
tasks = {}  # {username: [task1, task2]}

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# Traditional Signup
@app.route('/signup', methods=['POST'])
def signup():
    username = request.form.get('username')
    password = request.form.get('password')
    if username in users:
        return "User already exists!"
    users[username] = password
    tasks[username] = []
    session['user'] = username
    return redirect(url_for('tasks_page'))

# Traditional Login
@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    if users.get(username) == password:
        session['user'] = username
        return redirect(url_for('tasks_page'))
    return "Invalid username or password!"

# Logout
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# Tasks page
@app.route('/tasks')
def tasks_page():
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))
    user_tasks = tasks.get(username, [])
    return render_template('tasks.html', username=username, tasks=user_tasks)

# Add a task
@app.route('/add', methods=['POST'])
def add_task():
    username = session.get('user')
    if not username:
        return redirect(url_for('index'))
    task = request.form.get('task')
    if task:
        tasks[username].append(task)
    return redirect(url_for('tasks_page'))

# --- Google OAuth ---
@app.route('/login/google')
def login_google():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    user_info = resp.json()
    session['user'] = user_info.get('email')
    if session['user'] not in tasks:
        tasks[session['user']] = []
    return redirect(url_for('tasks_page'))

# --- Microsoft OAuth ---
@app.route('/login/microsoft')
def login_microsoft():
    redirect_uri = url_for('microsoft_callback', _external=True)
    return microsoft.authorize_redirect(redirect_uri)

@app.route('/auth/microsoft/callback')
def microsoft_callback():
    token = microsoft.authorize_access_token()
    resp = microsoft.get('me')
    user_info = resp.json()
    session['user'] = user_info.get('userPrincipalName')
    if session['user'] not in tasks:
        tasks[session['user']] = []
    return redirect(url_for('tasks_page'))

# --- Run the app ---
if __name__ == "__main__":
    app.run(debug=True)