# Routes for Cold Lead AI Flow (Part 3)
import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify, current_app
from openai import OpenAI
import resend
from twilio.rest import Client as TwilioClient

from src.models.supabase_interaction import (
    get_cold_lead_by_id,
    log_communication,
    update_lead_notes # May update notes with generated content
)
from dotenv import load_dotenv

load_dotenv()

cold_lead_bp = Blueprint("cold_lead_flow", __name__)

# --- Configuration & Clients --- #
PERSONAL_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
resend.api_key = RESEND_API_KEY
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --- Helper Functions --- #

def extract_domain(email):
    """Extracts domain from email."""
    if "@" not in email:
        return None
    return email.split("@")[1].lower()

def is_professional_domain(domain):
    """Checks if a domain is likely professional (not in PERSONAL_DOMAINS)."""
    return domain and domain not in PERSONAL_DOMAINS

def crawl_website(url):
    """Crawls a website URL and extracts visible text content."""
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status() # Raise an exception for bad status codes
        
        # Check content type
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type:
            print(f"Skipping non-HTML content at {url}")
            return ""

        soup = BeautifulSoup(response.content, "lxml")
        
        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
            
        # Get text, trying to preserve some structure
        text = soup.get_text(separator="\n", strip=True)
        
        # Basic cleaning (reduce multiple newlines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Limit length to avoid excessive token usage
        max_chars = 15000 # Approx 4k tokens
        return text[:max_chars]
        
    except requests.exceptions.RequestException as e:
        print(f"Error crawling website {url}: {e}")
        return ""
    except Exception as e:
        print(f"Error parsing website {url}: {e}")
        return ""

def generate_ai_content(company_info, lead_details):
    """Uses OpenAI GPT to generate solution offer, email, and WhatsApp message."""
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not configured.")
        return None

    prompt = f"""
    Analyze the following company information and lead details:
    
    Company Information:
    --- START COMPANY INFO ---
    {company_info if company_info else "No company website information available."} 
    --- END COMPANY INFO ---
    
    Lead Details:
    Name: {lead_details.get("name", "N/A")}
    Designation: {lead_details.get("designation", "N/A")}
    Original Inquiry Context (from notes): {lead_details.get("notes", "N/A")}
    
    Based on this, generate the following for a B2B outreach from a digital services agency:
    1.  **Customized Solution Offer (1-2 sentences):** Briefly propose a relevant service based on the company's potential needs inferred from the website info and lead's role. If no info, make a generic but relevant offer based on typical agency services (e.g., website enhancement, digital marketing).
    2.  **Short Follow-up Email:** Write a concise and personalized email (max 100 words) referencing the company/role (if possible) and the solution offer. Include a call to action (e.g., ask for a brief chat).
    3.  **WhatsApp Message Alternative:** Write a very short WhatsApp message (max 50 words) with the core offer and a clear call to action (e.g., "Interested? Reply YES" or provide a link).
    
    Format the output clearly, labeling each part (1. Solution Offer:, 2. Email:, 3. WhatsApp:).
    """
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # Or use gpt-4 if available/needed
            messages=[
                {"role": "system", "content": "You are an expert B2B sales assistant for a digital services agency."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        content = response.choices[0].message.content.strip()
        
        # Parse the generated content
        parsed_content = {
            "solution_offer": re.search(r"1\. Solution Offer:(.*?)(?:2\. Email:|$)", content, re.DOTALL).group(1).strip() if re.search(r"1\. Solution Offer:(.*?)(?:2\. Email:|$)", content, re.DOTALL) else "",
            "email_body": re.search(r"2\. Email:(.*?)(?:3\. WhatsApp:|$)", content, re.DOTALL).group(1).strip() if re.search(r"2\. Email:(.*?)(?:3\. WhatsApp:|$)", content, re.DOTALL) else "",
            "whatsapp_body": re.search(r"3\. WhatsApp:(.*)", content, re.DOTALL).group(1).strip() if re.search(r"3\. WhatsApp:(.*)", content, re.DOTALL) else ""
        }
        return parsed_content
        
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return None

def send_email_with_resend(to_email, subject, html_body):
    """Sends an email using the Resend API."""
    if not RESEND_API_KEY:
        print("Error: RESEND_API_KEY not configured.")
        return False, "Resend API key not configured"
        
    try:
        # Replace with your verified sending domain/email
        from_email = "onboarding@resend.dev" # Default for testing, change this!
        
        params = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body, # Resend prefers HTML
        }
        email = resend.Emails.send(params)
        print(f"Resend response: {email}")
        # Check response status (e.g., if email['id'] exists)
        return True, email.get("id")
    except Exception as e:
        print(f"Error sending email via Resend: {e}")
        return False, str(e)

def send_whatsapp_message(to_number, message_body):
    """Sends a WhatsApp message using Twilio API."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
        print("Error: Twilio credentials not fully configured.")
        return False, "Twilio credentials not configured"
        
    if not to_number:
        print("Error: No phone number provided for WhatsApp message.")
        return False, "Missing recipient phone number"
        
    # Ensure phone number is in E.164 format (e.g., +15551234567)
    # Basic check, might need more robust validation
    if not to_number.startswith("+"):
        # Attempt to prefix if it looks like a common format, otherwise fail
        # This is risky, proper formatting should be ensured earlier
        print(f"Warning: Phone number {to_number} might not be in E.164 format. Attempting to send anyway.")
        # Example: If number starts with country code digits but no +, add it.
        # Or, assume a default country code if appropriate for the context.
        # For now, we proceed but log a warning.

    try:
        message = twilio_client.messages.create(
            from_=f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
            body=message_body,
            to=f"whatsapp:{to_number}"
        )
        print(f"Twilio message SID: {message.sid}, Status: {message.status}")
        return True, message.sid
    except Exception as e:
        print(f"Error sending WhatsApp message via Twilio: {e}")
        return False, str(e)

# --- Main Route --- #

@cold_lead_bp.route("/process/<lead_id>", methods=["POST"])
def process_cold_lead(lead_id):
    """Processes a cold lead: crawls website (if applicable), generates AI content, and prepares for sending."""
    print(f"Received request to process cold lead {lead_id}")

    # 1. Fetch Cold Lead Data
    lead = get_cold_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": f"Cold lead with ID {lead_id} not found"}), 404

    email = lead.get("email")
    if not email:
        return jsonify({"error": f"Lead {lead_id} has no email address"}), 400

    domain = extract_domain(email)
    company_info = ""
    generated_content = None

    # 2. Check Domain & Crawl if Professional
    if is_professional_domain(domain):
        print(f"Professional domain detected: {domain}. Attempting to find website.")
        # Attempt to find website (could reuse function from gmail_parser or refine)
        website_url = f"https://{domain}" # Simple guess, could be improved
        print(f"Attempting to crawl: {website_url}")
        company_info = crawl_website(website_url)
        if not company_info:
             # Try www if root domain failed
             website_url_www = f"https://www.{domain}"
             print(f"Root domain failed, trying: {website_url_www}")
             company_info = crawl_website(website_url_www)
        
        if company_info:
            print(f"Successfully crawled website. Content length: {len(company_info)}")
        else:
            print("Failed to crawl website or extract content.")
            company_info = "Could not retrieve company website information." # Set placeholder for AI
    else:
        print(f"Personal domain detected: {domain}. Skipping website crawl.")

    # 3. Generate AI Content (always attempt, uses placeholder if crawl failed)
    print("Generating AI content...")
    generated_content = generate_ai_content(company_info, lead)

    if not generated_content:
        return jsonify({"error": "Failed to generate AI content"}), 500
        
    print(f"AI Content Generated: {generated_content}")

    # 4. Update Lead Notes (Optional - add generated content to notes?)
    # current_notes = lead.get("notes", "")
    # new_notes = f"{current_notes}\n\n--- AI Generated Content ---\nOffer: {generated_content['solution_offer']}\nEmail Draft: {generated_content['email_body']}\nWhatsApp Draft: {generated_content['whatsapp_body']}"
    # update_lead_notes(lead_id, new_notes) # Be careful about note length limits

    # 5. Prepare response (don't send automatically, let UI trigger send?)
    # The request asks for generation, not sending. Return the generated content.
    response_data = {
        "lead_id": lead_id,
        "lead_email": email,
        "lead_phone": lead.get("phone"),
        "is_professional": is_professional_domain(domain),
        "website_crawled": bool(company_info and "Could not retrieve" not in company_info),
        "generated_content": generated_content
    }

    return jsonify(response_data), 200

# --- Routes for Sending (Triggered by UI after review) --- #

@cold_lead_bp.route("/send_email/<lead_id>", methods=["POST"])
def send_cold_email(lead_id):
    data = request.json
    to_email = data.get("email")
    subject = data.get("subject", "Following Up") # Get subject from request or default
    html_body = data.get("body")

    if not all([to_email, html_body]):
        return jsonify({"error": "Missing 'email' or 'body' in request"}), 400

    success, result = send_email_with_resend(to_email, subject, html_body)

    # Log communication attempt
    log_communication({
        "lead_id": lead_id,
        "channel": "Email",
        "content": f"Subject: {subject}\nBody: {html_body[:500]}...", # Log snippet
        "status": "Sent" if success else f"Failed: {result}"
    })

    if success:
        return jsonify({"message": "Email sent successfully", "resend_id": result}), 200
    else:
        return jsonify({"error": f"Failed to send email: {result}"}), 500

@cold_lead_bp.route("/send_whatsapp/<lead_id>", methods=["POST"])
def send_cold_whatsapp(lead_id):
    data = request.json
    to_number = data.get("phone")
    message_body = data.get("body")

    if not all([to_number, message_body]):
        return jsonify({"error": "Missing 'phone' or 'body' in request"}), 400

    success, result = send_whatsapp_message(to_number, message_body)

    # Log communication attempt
    log_communication({
        "lead_id": lead_id,
        "channel": "WhatsApp",
        "content": message_body,
        "status": "Sent" if success else f"Failed: {result}"
    })

    if success:
        return jsonify({"message": "WhatsApp message sent successfully", "twilio_sid": result}), 200
    else:
        return jsonify({"error": f"Failed to send WhatsApp message: {result}"}), 500

