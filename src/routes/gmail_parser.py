# Routes for Gmail Lead Parsing (Part 1)
import os
import base64
import re
import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify, current_app
from src.lib.google_utils import get_gmail_service
from src.models.supabase_interaction import add_lead_to_supabase
from dotenv import load_dotenv

load_dotenv()

gmail_bp = Blueprint("gmail_parser", __name__)

TARGET_EMAIL = os.getenv("TARGET_GMAIL_ADDRESS", "complete.anant@gmail.com")
KEYWORDS = ["meeting fixed", "lead inquiry", "new lead", "contact request"]
PERSONAL_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"]

# --- Email Parsing Helper Functions ---

def decode_base64(encoded_data):
    """Decodes base64url encoded string."""
    if not encoded_data:
        return ""
    # Replace URL-safe characters and add padding if needed
    decoded_bytes = base64.urlsafe_b64decode(encoded_data + "===")
    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback for other encodings if UTF-8 fails
        try:
            return decoded_bytes.decode("latin-1")
        except Exception as e:
            print(f"Decoding error: {e}")
            return ""

def get_email_body(payload):
    """Extracts the text body from the email payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                body_data = part.get("body", {}).get("data")
                if body_data:
                    body += decode_base64(body_data)
            elif mime_type == "text/html":
                # Prefer plain text, but fallback to HTML if plain is empty
                if not body:
                    body_data = part.get("body", {}).get("data")
                    if body_data:
                        html_content = decode_base64(body_data)
                        # Basic HTML to text conversion
                        soup = BeautifulSoup(html_content, "lxml")
                        body += soup.get_text(separator="\n", strip=True)
            elif "parts" in part: # Handle nested parts (multipart/alternative)
                nested_body = get_email_body(part)
                if nested_body:
                    body += nested_body
    elif payload.get("mimeType") == "text/plain":
        body_data = payload.get("body", {}).get("data")
        if body_data:
            body = decode_base64(body_data)
    elif payload.get("mimeType") == "text/html":
        body_data = payload.get("body", {}).get("data")
        if body_data:
            html_content = decode_base64(body_data)
            soup = BeautifulSoup(html_content, "lxml")
            body = soup.get_text(separator="\n", strip=True)

    return body.strip()

def parse_sender_info(headers):
    """Parses sender name and email from headers."""
    sender_name = ""
    sender_email = ""
    for header in headers:
        if header["name"].lower() == "from":
            sender_str = header["value"]
            match = re.match(r"(.*)<(.*)>", sender_str)
            if match:
                sender_name = match.group(1).strip().replace("\"", "")
                sender_email = match.group(2).strip()
            else:
                # If no name part, assume the value is just the email
                sender_email = sender_str.strip()
            break
    return sender_name, sender_email

def parse_subject(headers):
    """Parses subject from headers."""
    for header in headers:
        if header["name"].lower() == "subject":
            return header["value"]
    return ""

def extract_phone(text):
    """Extracts a phone number from text using a simple regex."""
    # Regex to find potential phone numbers (adjust as needed for formats)
    # This is a basic example and might need refinement
    phone_match = re.search(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}", text)
    return phone_match.group(0) if phone_match else ""

def extract_company_from_email(email):
    """Extracts domain from email and checks if it's non-personal."""
    if "@" not in email:
        return None, None
    domain = email.split("@")[1].lower()
    if domain in PERSONAL_DOMAINS:
        return None, domain
    # Simple way to get company name from domain (e.g., example.com -> Example)
    company_name_guess = domain.split(".")[0].capitalize()
    return company_name_guess, domain

def find_company_website(domain):
    """Attempts to find the company website using the domain (placeholder)."""
    if not domain or domain in PERSONAL_DOMAINS:
        return ""
    # Basic check: try https and http
    for protocol in ["https", "http"]:
        url = f"{protocol}://{domain}"
        try:
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code < 400:
                return response.url # Return the final URL after redirects
        except requests.RequestException:
            continue
    # Fallback: try www version
    for protocol in ["https", "http"]:
        url = f"{protocol}://www.{domain}"
        try:
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code < 400:
                return response.url
        except requests.RequestException:
            continue

    print(f"Could not automatically verify website for domain: {domain}")
    return "" # Return empty if not found/verified

# --- Main Route --- #

@gmail_bp.route("/fetch_and_parse", methods=["POST"]) # Changed route name
def fetch_and_parse_gmail_leads():
    """Fetches new emails, filters, parses, and adds leads to Supabase."""
    print(f"Attempting to fetch emails for {TARGET_EMAIL}...")
    gmail_service = get_gmail_service()
    if not gmail_service:
        return jsonify({"error": "Failed to authenticate with Gmail"}), 500

    processed_leads = []
    errors = []

    try:
        # 1. Search for relevant emails (unread and matching keywords)
        # Construct query: is:unread AND (subject:(keyword1) OR subject:(keyword2) OR keyword1 OR keyword2        keyword_query = " OR ".join([f'subject:("{kw}") OR "{kw}"' for kw in KEYWORDS])
        query = f"is:unread in:inbox to:{TARGET_EMAIL} ({keyword_query})"
        print(f"Using Gmail query: {query}")

        results = gmail_service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])

        if not messages:
            print("No new relevant emails found.")
            return jsonify({"message": "No new relevant emails found.", "processed_count": 0}), 200

        print(f"Found {len(messages)} potential lead emails.")

        # 2. Process each message
        for msg_ref in messages:
            msg_id = msg_ref["id"]
            try:
                # Get full email details
                msg = gmail_service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])

                # Parse essential info
                sender_name, sender_email = parse_sender_info(headers)
                subject = parse_subject(headers)
                email_body = get_email_body(payload)

                print(f"\nProcessing email ID: {msg_id}")
                print(f"From: {sender_name} <{sender_email}>")
                print(f"Subject: {subject}")

                # Basic check if email content seems relevant (redundant with query but good practice)
                content_lower = (subject + " " + email_body).lower()
                if not any(kw in content_lower for kw in KEYWORDS):
                    print("Skipping email - keywords not found in body/subject after fetch.")
                    # Optionally mark as read here if query isn't perfect
                    # gmail_service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
                    continue

                # Extract details
                phone = extract_phone(email_body)
                company_guess, domain = extract_company_from_email(sender_email)
                company_website = find_company_website(domain) if domain else ""

                # Prepare lead data for Supabase
                lead_data = {
                    "name": sender_name or sender_email.split("@")[0], # Use email prefix if name is empty
                    "email": sender_email,
                    "phone": phone,
                    "company": company_guess, # Use guess from email domain
                    "designation": "", # Designation not easily parsed, leave empty
                    "source": "Gmail",
                    "status": "Active",
                    "notes": f"Subject: {subject}\n\nBody Snippet:\n{email_body[:500]}..." # Add snippet as initial note
                    # last_contacted will be set by Supabase default or trigger
                }

                print(f"Parsed Lead Data: {lead_data}")

                # 3. Add to Supabase
                supabase_response = add_lead_to_supabase(lead_data)

                if supabase_response:
                    print(f"Successfully added lead {lead_data['email']} to Supabase.")
                    processed_leads.append(lead_data["email"])
                    # 4. Mark email as read
                    gmail_service.users().messages().modify(userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}).execute()
                    print(f"Marked email {msg_id} as read.")
                else:
                    print(f"Failed to add lead {lead_data['email']} to Supabase.")
                    errors.append({"email_id": msg_id, "error": "Supabase insertion failed"})

            except Exception as e:
                print(f"Error processing email ID {msg_id}: {e}")
                errors.append({"email_id": msg_id, "error": str(e)})
                # Optionally, decide whether to mark as read even if processing fails
                # gmail_service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()

        result_message = f"Processed {len(processed_leads)} leads successfully." 
        if errors:
            result_message += f" Encountered {len(errors)} errors."
        
        return jsonify({
            "message": result_message,
            "processed_count": len(processed_leads),
            "processed_leads": processed_leads,
            "errors": errors
        }), 200

    except Exception as e:
        print(f"An error occurred during Gmail fetching/parsing: {e}")
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

# Placeholder for OAuth callback - needed for a proper web flow
# @gmail_bp.route("/oauth2callback")
# def oauth2callback():
#     # Handle the redirect from Google after user authorization
#     pass

