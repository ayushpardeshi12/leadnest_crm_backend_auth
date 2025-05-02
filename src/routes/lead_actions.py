# Routes for Post-Call Lead Actions (Part 2)
import datetime
from flask import Blueprint, request, jsonify, current_app
from src.models.supabase_interaction import (
    get_lead_by_id,
    update_lead_notes,
    move_lead_to_cold,
    add_appointment,
    get_active_leads # Added for fetching leads
)
from src.lib.google_utils import get_calendar_service

lead_actions_bp = Blueprint("lead_actions", __name__)

# --- API Routes for Frontend --- #

@lead_actions_bp.route("/active", methods=["GET"])
def get_all_active_leads():
    """API endpoint to fetch all active leads for the frontend."""
    leads = get_active_leads()
    return jsonify(leads), 200

# Add similar routes for /cold, /deleted etc. as needed

# --- Action Routes --- #

@lead_actions_bp.route("/<lead_id>/notes", methods=["POST"])
def handle_add_notes(lead_id):
    """API endpoint to add/update notes for a lead."""
    data = request.json
    notes = data.get("notes")
    if notes is None: # Allow empty notes to clear existing ones
        return jsonify({"error": "Missing 'notes' field in request body"}), 400

    updated_lead = update_lead_notes(lead_id, notes)
    if updated_lead:
        return jsonify(updated_lead), 200
    else:
        return jsonify({"error": f"Failed to update notes for lead {lead_id}"}), 500

@lead_actions_bp.route("/<lead_id>/schedule", methods=["POST"])
def handle_schedule_meeting(lead_id):
    """API endpoint to schedule a meeting via Google Calendar."""
    data = request.json
    start_time_str = data.get("start_time") # Expected format: "YYYY-MM-DDTHH:MM:SS"
    end_time_str = data.get("end_time")     # Expected format: "YYYY-MM-DDTHH:MM:SS"
    summary = data.get("summary", "Meeting with Lead")
    description = data.get("description", "") # From notes
    timezone = data.get("timezone", "UTC") # Get timezone from request or default

    if not start_time_str or not end_time_str:
        return jsonify({"error": "Missing 'start_time' or 'end_time' in request body"}), 400

    # 1. Get Lead Email
    lead = get_lead_by_id(lead_id)
    if not lead or not lead.get("email"):
        return jsonify({"error": f"Lead {lead_id} not found or has no email address"}), 404

    # 2. Get Calendar Service
    calendar_service = get_calendar_service()
    if not calendar_service:
        return jsonify({"error": "Failed to authenticate with Google Calendar"}), 500

    # 3. Create Calendar Event
    event = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_time_str,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_time_str,
            "timeZone": timezone,
        },
        "attendees": [
            {"email": lead["email"]},
            # Optionally add the user's email (fetch from settings/auth)
        ],
        "conferenceData": {
            "createRequest": {
                "requestId": f"leadnest-{lead_id}-{datetime.datetime.utcnow().timestamp()}", # Unique request ID
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        },
        "reminders": {
            "useDefault": True,
        },
    }

    try:
        print(f"Creating calendar event: {event}")
        created_event = calendar_service.events().insert(
            calendarId="primary", 
            body=event,
            conferenceDataVersion=1 # Required to get Meet link
        ).execute()
        print(f"Event created: {created_event.get('htmlLink')}")
        meet_link = created_event.get("hangoutLink", "")

        # 4. Save Appointment to Supabase
        appointment_data = {
            "lead_id": lead_id,
            "date_time": start_time_str, # Store start time
            "notes": description,
            "meet_link": meet_link,
            "google_event_id": created_event.get("id") # Store Google Event ID for potential future updates/deletion
        }
        db_appointment = add_appointment(appointment_data)

        if db_appointment:
            return jsonify({
                "message": "Meeting scheduled successfully",
                "event_link": created_event.get("htmlLink"),
                "meet_link": meet_link,
                "appointment_id": db_appointment.get("id")
            }), 201
        else:
            # Event created in Google, but failed to save in DB. Log this inconsistency.
            print(f"CRITICAL: Google Event {created_event.get('id')} created but failed to save appointment to DB for lead {lead_id}")
            return jsonify({"error": "Meeting scheduled in Google Calendar, but failed to save to database."}), 500

    except Exception as e:
        print(f"Error creating Google Calendar event: {e}")
        return jsonify({"error": f"Failed to schedule meeting: {e}"}), 500

@lead_actions_bp.route("/<lead_id>/mark_cold", methods=["POST"])
def handle_mark_as_cold(lead_id):
    """API endpoint to mark a lead as cold."""
    # Optional: Get reason from request body if needed
    # data = request.json
    # reason = data.get("reason", "Marked as cold by user")
    
    moved_lead = move_lead_to_cold(lead_id)
    if moved_lead:
        # Return the data of the lead as it exists in the cold_leads table
        return jsonify(moved_lead), 200 
    else:
        return jsonify({"error": f"Failed to mark lead {lead_id} as cold"}), 500

