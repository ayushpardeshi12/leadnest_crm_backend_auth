# Routes for User Authentication (Login, Register, Logout, Google OAuth)
import os
from flask import Blueprint, request, jsonify, redirect, url_for, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
import requests
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport.requests import Request as GoogleRequest

from src.models.supabase_interaction import create_user, find_user_by_email, find_or_create_google_user
from src.models.user import User

auth_bp = Blueprint("auth", __name__)

# --- Google OAuth Configuration --- #
# Ensure these are in your .env file
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# This must match the authorized redirect URI in Google Cloud Console
# For local testing, it might be http://localhost:5000/auth/google/callback
# For production, it will be your deployed backend URL + /auth/google/callback
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback") 

# Path to your client secrets file (ensure it exists or configure flow differently)
# If GOOGLE_CLIENT_ID/SECRET are set, we can configure the flow directly
# CLIENT_SECRETS_FILE = "/home/ubuntu/leadnest_crm/credentials.json" 

# Scopes required for Google Sign-In (profile and email are standard)
SCOPES = ["https://www.googleapis.com/auth/userinfo.profile", 
          "https://www.googleapis.com/auth/userinfo.email", 
          "openid"] # openid is required for ID tokens

# --- Standard Authentication Routes --- #

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    name = data.get("name") # Optional

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # Basic validation (add more as needed)
    if "@" not in email:
         return jsonify({"error": "Invalid email format"}), 400
    if len(password) < 6:
         return jsonify({"error": "Password must be at least 6 characters long"}), 400

    new_user, error_message = create_user(email, password, name)

    if new_user:
        # Optionally log the user in immediately after registration
        # login_user(new_user)
        return jsonify({"message": "User registered successfully", "user": {"id": new_user.id, "email": new_user.email, "name": new_user.name}}), 201
    else:
        status_code = 409 if "already exists" in (error_message or "") else 500
        return jsonify({"error": error_message or "Registration failed"}), status_code

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user_data = find_user_by_email(email)

    if user_data and user_data.get("password_hash") and check_password_hash(user_data["password_hash"], password):
        # Create User object for Flask-Login
        user = User(id=user_data["id"], email=user_data["email"], name=user_data.get("name"), google_id=user_data.get("google_id"))
        login_user(user, remember=True) # Remember the user session
        print(f"User {email} logged in successfully.")
        return jsonify({"message": "Login successful", "user": {"id": user.id, "email": user.email, "name": user.name}}), 200
    elif user_data and not user_data.get("password_hash") and user_data.get("google_id"):
         print(f"Login attempt failed for {email}: User signed up via Google, no password set.")
         return jsonify({"error": "Login failed. Try signing in with Google."}), 401
    else:
        print(f"Login attempt failed for {email}: Invalid credentials.")
        return jsonify({"error": "Invalid email or password"}), 401

@auth_bp.route("/logout", methods=["POST"])
@login_required # Ensure user is logged in to log out
def logout():
    user_email = current_user.email
    logout_user()
    # Clear Google OAuth state if stored in session
    session.pop("google_oauth_state", None)
    session.pop("google_oauth_token", None)
    print(f"User {user_email} logged out.")
    return jsonify({"message": "Logout successful"}), 200

@auth_bp.route("/status")
def status():
    """Returns the current logged-in user's information, or indicates not logged in."""
    if current_user.is_authenticated:
        return jsonify({
            "logged_in": True,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "name": current_user.name,
                "google_id": current_user.google_id
            }
        }), 200
    else:
        return jsonify({"logged_in": False}), 200

# --- Google OAuth Routes --- #

@auth_bp.route("/google/login")
def google_login():
    """Initiates the Google OAuth 2.0 flow."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({"error": "Google OAuth not configured correctly on server."}), 500
        
    # Use client_config dictionary directly if client_secrets.json is not preferred
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
            "javascript_origins": [] # Add frontend origin if needed for JS client
        }
    }

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

    # Generate authorization URL and state for CSRF protection
    authorization_url, state = flow.authorization_url(
        access_type="offline", # Request refresh token for long-term access (optional)
        include_granted_scopes="true"
    )

    # Store state in session to verify callback
    session["google_oauth_state"] = state
    print(f"Redirecting to Google: {authorization_url}")
    # Redirect the user to Google's authorization page
    return redirect(authorization_url)

@auth_bp.route("/google/callback")
def google_callback():
    """Handles the callback from Google after user authorization."""
    # Verify state to prevent CSRF attacks
    state = session.get("google_oauth_state")
    if not state or state != request.args.get("state"):
        print("OAuth State mismatch error.")
        return jsonify({"error": "Invalid state parameter"}), 400

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({"error": "Google OAuth not configured correctly on server."}), 500

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    }
    
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

    try:
        # Exchange authorization code for credentials (access token, refresh token, ID token)
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        print(f"Error fetching Google token: {e}")
        return jsonify({"error": f"Failed to fetch token from Google: {e}"}), 500

    credentials = flow.credentials
    # Store credentials in session (optional, consider security implications)
    # session["google_oauth_token"] = credentials_to_dict(credentials)

    # Verify the ID token to get user information securely
    try:
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, GoogleRequest(), GOOGLE_CLIENT_ID
        )
        print(f"Google ID Token verified: {id_info}")
    except ValueError as e:
        print(f"Error verifying Google ID token: {e}")
        return jsonify({"error": f"Invalid ID token: {e}"}), 400

    # Use the verified user info (id_info contains 'sub', 'email', 'name', etc.)
    user, error_message = find_or_create_google_user(id_info)

    if user:
        login_user(user, remember=True) # Log the user in
        print(f"User {user.email} logged in via Google.")
        # Redirect to the frontend application after successful login
        # TODO: Make the frontend URL configurable
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000") 
        return redirect(frontend_url + "/leads") # Redirect to leads page or dashboard
    else:
        print(f"Failed to find or create Google user: {error_message}")
        # Redirect to frontend login page with error message?
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000") 
        return redirect(frontend_url + "/?error=google_login_failed") # Redirect back to login page

# Helper function to convert credentials to dict (if storing in session)
# def credentials_to_dict(credentials):
#     return {"token": credentials.token,
#             "refresh_token": credentials.refresh_token,
#             "token_uri": credentials.token_uri,
#             "client_id": credentials.client_id,
#             "client_secret": credentials.client_secret,
#             "scopes": credentials.scopes}

