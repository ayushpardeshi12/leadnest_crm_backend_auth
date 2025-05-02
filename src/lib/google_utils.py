# Utilities for Google API interactions (Gmail, Calendar)
import os
import pickle
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# Define the scopes required for Gmail and Calendar
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly", # Read emails
    "https://www.googleapis.com/auth/calendar",       # Read/write calendar events
    "https://www.googleapis.com/auth/calendar.events" # Read/write calendar events
]

TOKEN_PATH = "/home/ubuntu/leadnest_crm/token.json" # Changed from pickle to json for compatibility with google lib
CREDENTIALS_PATH = "/home/ubuntu/leadnest_crm/credentials.json"

def get_google_credentials():
    """Gets valid Google API credentials, handling OAuth flow if necessary."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"Error loading token file: {e}. Need to re-authenticate.")
            creds = None # Force re-authentication

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}. Need to re-authenticate.")
                # If refresh fails, delete token and re-run flow
                if os.path.exists(TOKEN_PATH):
                    os.remove(TOKEN_PATH)
                return authenticate_user()
        else:
            # Run the OAuth 2.0 flow
            return authenticate_user()

        # Save the credentials for the next run
        try:
            with open(TOKEN_PATH, "w") as token:
                token.write(creds.to_json())
            print(f"Credentials saved to {TOKEN_PATH}")
        except Exception as e:
            print(f"Error saving token file: {e}")

    return creds

def authenticate_user():
    """Runs the OAuth 2.0 authentication flow."""
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"Error: Credentials file not found at {CREDENTIALS_PATH}")
        print("Please ensure 'credentials.json' from Google Cloud Console is placed in the project root.")
        return None

    try:
        # Note: InstalledAppFlow is typically for desktop apps.
        # For a web app (Flask), WebApplicationFlow is more appropriate,
        # requiring handling redirects. Using InstalledAppFlow for simplicity here,
        # but this will require manual interaction in the console where the Flask app runs.
        # A proper web flow implementation would involve Flask routes for /authorize and /oauth2callback.
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        # The redirect_uri here is mainly for the InstalledAppFlow's local server.
        # It might differ from the one configured in Google Cloud Console for a web app.
        creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
        print(f"Credentials obtained and saved to {TOKEN_PATH}")
        return creds
    except Exception as e:
        print(f"Error during authentication flow: {e}")
        return None

def get_gmail_service():
    """Returns an authenticated Gmail API service object."""
    creds = get_google_credentials()
    if not creds:
        print("Failed to get Google credentials.")
        return None
    try:
        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Gmail service: {e}")
        return None

def get_calendar_service():
    """Returns an authenticated Google Calendar API service object."""
    creds = get_google_credentials()
    if not creds:
        print("Failed to get Google credentials.")
        return None
    try:
        service = build("calendar", "v3", credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Calendar service: {e}")
        return None

# Example usage (for testing purposes)
if __name__ == "__main__":
    print("Attempting to get Gmail service...")
    gmail = get_gmail_service()
    if gmail:
        print("Successfully obtained Gmail service object.")
        # Example: List labels
        # results = gmail.users().labels().list(userId='me').execute()
        # labels = results.get('labels', [])
        # print("Labels:", labels)
    else:
        print("Failed to obtain Gmail service object.")

    print("\nAttempting to get Calendar service...")
    calendar = get_calendar_service()
    if calendar:
        print("Successfully obtained Calendar service object.")
    else:
        print("Failed to obtain Calendar service object.")

