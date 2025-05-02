# Main application file for LeadNest CRM
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__))) # Required for Flask template

from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS
from flask_login import LoginManager # Import LoginManager
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "a_very_secret_key_that_should_be_changed") # Change this!
CORS(app, supports_credentials=True) # Enable CORS with credentials support for session cookies

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
# If using blueprints, specify the login view like this:
login_manager.login_view = "auth.login" # The endpoint name for the login route within the auth blueprint
# Optional: Message flashed when login is required
# login_manager.login_message = "Please log in to access this page."
# login_manager.login_message_category = "info"

# User loader function required by Flask-Login
from src.models.supabase_interaction import find_user_by_id

@login_manager.user_loader
def load_user(user_id):
    return find_user_by_id(user_id)

# Configuration (e.g., API keys, Supabase URL/Key)
# These should ideally be loaded from environment variables
# app.config["SECRET_KEY"] is set above
app.config["SUPABASE_URL"] = os.getenv("SUPABASE_URL")
app.config['SUPABASE_KEY'] = os.getenv('SUPABASE_SERVICE_KEY') # Use service role key for backend operations
app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')
app.config['RESEND_API_KEY'] = os.getenv('RESEND_API_KEY')
app.config['TWILIO_ACCOUNT_SID'] = os.getenv('TWILIO_ACCOUNT_SID')
app.config['TWILIO_AUTH_TOKEN'] = os.getenv('TWILIO_AUTH_TOKEN')
app.config['TWILIO_WHATSAPP_NUMBER'] = os.getenv('TWILIO_WHATSAPP_NUMBER')

# Initialize Supabase client (example - adjust based on library usage)
# from supabase import create_client, Client
# supabase: Client = create_client(app.config['SUPABASE_URL'], app.config['SUPABASE_KEY'])# Import and register blueprints for different parts of the application
from src.routes.auth import auth_bp # Import auth blueprint
from src.routes.gmail_parser import gmail_bp
from src.routes.lead_actions import lead_actions_bp
from src.routes.cold_lead_flow import cold_lead_bp
from src.routes.reactivation import reactivation_bp

app.register_blueprint(auth_bp, url_prefix='/auth') # Register auth blueprint
app.register_blueprint(gmail_bp, url_prefix='/gmail')
app.register_blueprint(lead_actions_bp, url_prefix='/leads') # Using /leads prefix for actions on specific leads
app.register_blueprint(cold_lead_bp, url_prefix='/cold_leads')
app.register_blueprint(reactivation_bp, url_prefix='/reactivate') # Prefix for potential helper routes

# Basic route
@app.route('/')
def index():
    return jsonify({'message': 'Welcome to LeadNest CRM API!'})

# Webhook endpoint for Part 4
from src.models.supabase_interaction import reactivate_lead

@app.route('/webhook/reactivate', methods=['POST'])
def handle_reactivation_webhook():
    """Handles webhook trigger from email/WhatsApp CTA to reactivate a lead."""
    data = request.json
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    lead_id = data.get("lead_id")
    if not lead_id:
        return jsonify({"error": "Missing 'lead_id' in request body"}), 400

    print(f"Received reactivation webhook for lead_id: {lead_id}")

    reactivated_lead = reactivate_lead(lead_id)

    if reactivated_lead:
        print(f"Successfully reactivated lead {lead_id}.")
        # Placeholder for triggering user notification/prompt
        print(f"ACTION NEEDED: Notify user about reactivated lead {lead_id}") 
        return jsonify({"status": "success", "message": f"Lead {lead_id} reactivated.", "lead_data": reactivated_lead}), 200
    else:
        print(f"Failed to reactivate lead {lead_id}.")
        # Check if lead was not found or if another error occurred
        # For simplicity, returning a generic error
        return jsonify({"status": "error", "message": f"Failed to reactivate lead {lead_id}. It might already be active or an error occurred."}), 500

if __name__ == '__main__':
    # Run the app (listening on 0.0.0.0 for accessibility)
    # Port 5000 is a common default for Flask
    app.run(host='0.0.0.0', port=5000, debug=True) # Set debug=False for production

