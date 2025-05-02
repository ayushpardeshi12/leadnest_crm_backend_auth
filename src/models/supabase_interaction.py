# Functions for interacting with Supabase tables
import os
from supabase import create_client, Client
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from src.models.user import User # Import the User class

load_dotenv() # Load environment variables

# Initialize Supabase client
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_KEY") # Use service role key for backend operations
supabase: Client = create_client(url, key)

def add_lead_to_supabase(lead_data):
    """Adds a new lead to the active_leads table in Supabase.

    Args:
        lead_data (dict): A dictionary containing lead details matching the table columns.
                          e.g., {"name": "John Doe", "email": "john.doe@example.com", ...}

    Returns:
        tuple: A tuple containing the response data and count from Supabase, or None if error.
    """
    try:
        # Ensure required fields are present (example)
        if not all(k in lead_data for k in ["name", "email", "source", "status"]):
            print("Error: Missing required lead data fields.")
            return None

        data, count = supabase.table("active_leads").insert(lead_data).execute()
        print(f"Supabase insert response: {data}, Count: {count}")
        # The response format might vary based on the library version and operation
        # Check the actual response structure: data is typically a list containing a dict
        if data and len(data[1]) > 0:
            print(f"Successfully added lead: {data[1][0]['id']}")
            return data, count
        else:
            print(f"Error adding lead, Supabase response: {data}")
            # Check for specific errors if available in the response
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (add_lead): {e}")
        return None



def get_cold_lead_by_id(lead_id):
    """Fetches a single lead by its ID from the cold_leads table."""
    try:
        data, count = supabase.table("cold_leads").select("*").eq("id", lead_id).maybe_single().execute()
        if data and data[1]:
            return data[1]
        else:
            # Check active leads as a fallback if not found in cold, though ideally it should be in cold
            print(f"Lead {lead_id} not found in cold_leads, checking active_leads...")
            active_lead = get_lead_by_id(lead_id) # Uses the existing function for active_leads
            if active_lead:
                print(f"Warning: Lead {lead_id} found in active_leads but requested from cold flow.")
                return active_lead # Return active lead if found, but this indicates a state issue
            print(f"Lead with ID {lead_id} not found in cold_leads or active_leads.")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (get_cold_lead_by_id): {e}")
        return None

def get_active_leads():
    """Fetches all leads from the active_leads table."""
    try:
        data, count = supabase.table("active_leads").select("*").order("created_at", desc=True).execute()
        if data:
            # The actual data is in the second element of the tuple
            return data[1]
        else:
            print(f"Error fetching active leads, Supabase response: {data}")
            return []
    except Exception as e:
        print(f"Error interacting with Supabase (get_active_leads): {e}")
        return []

def get_lead_by_id(lead_id):
    """Fetches a single lead by its ID from the active_leads table."""
    try:
        data, count = supabase.table("active_leads").select("*").eq("id", lead_id).maybe_single().execute()
        if data and data[1]:
            return data[1]
        else:
            print(f"Lead with ID {lead_id} not found or error occurred.")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (get_lead_by_id): {e}")
        return None

def update_lead_notes(lead_id, notes):
    """Updates the notes for a specific lead in the active_leads table."""
    try:
        data, count = supabase.table("active_leads").update({"notes": notes, "last_contacted": "now()"}).eq("id", lead_id).execute()
        if data and len(data[1]) > 0:
            print(f"Successfully updated notes for lead {lead_id}")
            return data[1][0]
        else:
            print(f"Error updating notes for lead {lead_id}, Supabase response: {data}")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (update_lead_notes): {e}")
        return None

def update_lead_status(lead_id, new_status):
    """Updates the status for a specific lead in the active_leads table."""
    try:
        data, count = supabase.table("active_leads").update({"status": new_status, "last_contacted": "now()"}).eq("id", lead_id).execute()
        if data and len(data[1]) > 0:
            print(f"Successfully updated status for lead {lead_id} to {new_status}")
            return data[1][0]
        else:
            print(f"Error updating status for lead {lead_id}, Supabase response: {data}")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (update_lead_status): {e}")
        return None

def move_lead_to_cold(lead_id, reason="Marked as cold by user"):
    """Moves a lead from active_leads to cold_leads table."""
    try:
        # 1. Get the lead details from active_leads
        lead_to_move = get_lead_by_id(lead_id)
        if not lead_to_move:
            print(f"Cannot move lead {lead_id} to cold: Lead not found in active_leads.")
            return None

        # 2. Prepare data for cold_leads table (add reason_cold)
        cold_lead_data = lead_to_move.copy()
        cold_lead_data["reason_cold"] = reason
        # Remove fields that might not exist in cold_leads or handle them appropriately
        # Assuming cold_leads has the same base fields + reason_cold
        # If IDs are auto-generated, remove the original ID or handle potential conflicts
        # For simplicity, let's assume ID can be reused or is handled by Supabase policies/triggers
        # If 'id' is primary key and unique, this insert might fail if the ID already exists.
        # A safer approach might be to not copy the ID and let Supabase generate a new one,
        # or update status in active_leads instead of moving.
        # Based on schema description, let's assume moving is intended.

        # Remove original ID if it's auto-incrementing in cold_leads
        # if 'id' in cold_lead_data:
        #     del cold_lead_data['id']

        # 3. Insert into cold_leads
        insert_data, insert_count = supabase.table("cold_leads").insert(cold_lead_data).execute()

        if insert_data and len(insert_data[1]) > 0:
            print(f"Successfully inserted lead {lead_id} into cold_leads.")
            # 4. Delete from active_leads
            delete_data, delete_count = supabase.table("active_leads").delete().eq("id", lead_id).execute()
            if delete_data and len(delete_data[1]) > 0:
                print(f"Successfully deleted lead {lead_id} from active_leads.")
                return insert_data[1][0] # Return the newly created cold lead record
            else:
                print(f"Error deleting lead {lead_id} from active_leads after moving to cold. Manual cleanup might be needed.")
                # Rollback? Or just report error?
                return None # Indicate partial failure
        else:
            print(f"Error inserting lead {lead_id} into cold_leads, Supabase response: {insert_data}")
            return None

    except Exception as e:
        print(f"Error interacting with Supabase (move_lead_to_cold): {e}")
        return None

def add_appointment(appointment_data):
    """Adds a new appointment to the appointments table."""
    try:
        # Ensure required fields are present
        if not all(k in appointment_data for k in ["lead_id", "date_time", "meet_link"]):
            print("Error: Missing required appointment data fields.")
            return None

        data, count = supabase.table("appointments").insert(appointment_data).execute()
        if data and len(data[1]) > 0:
            print(f"Successfully added appointment for lead {appointment_data['lead_id']}")
            return data[1][0]
        else:
            print(f"Error adding appointment, Supabase response: {data}")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (add_appointment): {e}")
        return None


def reactivate_lead(lead_id):
    """Moves a lead from cold_leads back to active_leads with 'Warmed Up' status."""
    try:
        # 1. Get the lead details from cold_leads
        cold_lead_data, count = supabase.table("cold_leads").select("*").eq("id", lead_id).maybe_single().execute()
        
        if not cold_lead_data or not cold_lead_data[1]:
            # Maybe it's already active? Check active_leads
            active_lead_data, active_count = supabase.table("active_leads").select("id, status").eq("id", lead_id).maybe_single().execute()
            if active_lead_data and active_lead_data[1]:
                print(f"Lead {lead_id} is already in active_leads.")
                # Optionally update status if it's not already 'Warmed Up'
                if active_lead_data[1].get("status") != "Warmed Up / Priority Lead":
                    return update_lead_status(lead_id, "Warmed Up / Priority Lead")
                return active_lead_data[1] # Return existing active lead data
            else:
                print(f"Cannot reactivate lead {lead_id}: Lead not found in cold_leads or active_leads.")
                return None

        lead_to_move = cold_lead_data[1]

        # 2. Prepare data for active_leads table
        active_lead_data = lead_to_move.copy()
        active_lead_data["status"] = "Warmed Up / Priority Lead"
        active_lead_data["last_contacted"] = "now()" # Update last contacted time
        # Remove fields specific to cold_leads if they exist
        if "reason_cold" in active_lead_data:
            del active_lead_data["reason_cold"]
        # Add reactivated_at timestamp if schema supports it
        # active_lead_data["reactivated_at"] = "now()"

        # 3. Insert into active_leads (handle potential conflicts if ID exists)
        # Using upsert to handle cases where the lead might somehow exist in active_leads already
        # or if we want to ensure the latest data overwrites.
        # Note: `ignore_duplicates=False` is default, `on_conflict` might be needed depending on PK/unique constraints
        insert_data, insert_count = supabase.table("active_leads").upsert(active_lead_data).execute()

        if insert_data and len(insert_data[1]) > 0:
            print(f"Successfully upserted lead {lead_id} into active_leads with 'Warmed Up' status.")
            # 4. Delete from cold_leads
            delete_data, delete_count = supabase.table("cold_leads").delete().eq("id", lead_id).execute()
            if delete_data and len(delete_data[1]) > 0:
                print(f"Successfully deleted lead {lead_id} from cold_leads.")
                # 5. TODO: Implement follow-up prompt logic here (e.g., update a flag, send notification)
                print(f"Placeholder: Schedule follow-up prompt for user regarding lead {lead_id}.")
                return insert_data[1][0] # Return the reactivated lead record from active_leads
            else:
                print(f"Error deleting lead {lead_id} from cold_leads after moving to active. Manual cleanup might be needed.")
                # Rollback? Or just report error?
                return None # Indicate partial failure
        else:
            print(f"Error upserting lead {lead_id} into active_leads, Supabase response: {insert_data}")
            return None

    except Exception as e:
        print(f"Error interacting with Supabase (reactivate_lead): {e}")
        return None

def log_communication(log_data):
    """Logs an email or WhatsApp message sent to a lead."""
    try:
        # Ensure required fields are present
        if not all(k in log_data for k in ["lead_id", "channel", "content", "status"]):
            print("Error: Missing required communication log data fields.")
            return None
        
        # Determine the correct table based on the channel
        table_name = "email_logs" if log_data["channel"].lower() == "email" else "whatsapp_logs"
        
        data, count = supabase.table(table_name).insert(log_data).execute()
        if data and len(data[1]) > 0:
            print(f"Successfully logged {log_data['channel']} communication for lead {log_data['lead_id']}")
            return data[1][0]
        else:
            print(f"Error logging communication, Supabase response: {data}")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (log_communication): {e}")
        return None



# --- User Authentication Functions --- #

def create_user(email, password, name=None):
    """Creates a new user in the users table with a hashed password."""
    try:
        # Check if user already exists
        existing_data, count = supabase.table("users").select("id").eq("email", email).maybe_single().execute()
        # Check if the query returned data and if the data list is not empty
        if existing_data and len(existing_data) > 1 and existing_data[1]:
            print(f"User with email {email} already exists.")
            return None, "User already exists"

        hashed_password = generate_password_hash(password)
        user_data = {
            "email": email,
            "password_hash": hashed_password,
            "name": name or email # Use email if name is not provided
        }
        data, count = supabase.table("users").insert(user_data).execute()
        
        # Check if the insert was successful (data list is not empty)
        if data and len(data) > 1 and len(data[1]) > 0:
            created_user_info = data[1][0]
            print(f"Successfully created user: {email} with ID: {created_user_info['id']}")
            # Return the created user data as a User object (excluding password hash for security)
            return User(id=created_user_info["id"], email=created_user_info["email"], name=created_user_info.get("name")), None
        else:
            print(f"Error creating user {email}, Supabase response: {data}")
            # Try to extract a more specific error if possible
            error_message = f"Supabase error: {data}"
            if isinstance(data, tuple) and len(data) > 0 and hasattr(data[0], 'error'):
                 error_message = f"Supabase error: {data[0].error.message if data[0].error else 'Unknown'}"
            return None, error_message
    except Exception as e:
        print(f"Error interacting with Supabase (create_user): {e}")
        return None, str(e)

def find_user_by_email(email):
    """Finds a user by email and returns the raw user data including password hash."""
    try:
        data, count = supabase.table("users").select("id, email, password_hash, name, google_id").eq("email", email).maybe_single().execute()
        # Check if data was returned and the data list is not empty
        if data and len(data) > 1 and data[1]:
            user_data = data[1]
            # Return the full user data including password hash for login check
            return user_data 
        else:
            print(f"User with email {email} not found.")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (find_user_by_email): {e}")
        return None

def find_user_by_id(user_id):
    """Finds a user by ID and returns a User object (used by Flask-Login)."""
    try:
        data, count = supabase.table("users").select("id, email, name, google_id").eq("id", user_id).maybe_single().execute()
        # Check if data was returned and the data list is not empty
        if data and len(data) > 1 and data[1]:
            user_data = data[1]
            return User(id=user_data["id"], email=user_data["email"], name=user_data.get("name"), google_id=user_data.get("google_id"))
        else:
            print(f"User with ID {user_id} not found.")
            return None
    except Exception as e:
        print(f"Error interacting with Supabase (find_user_by_id): {e}")
        return None

def find_or_create_google_user(google_user_info):
    """Finds a user by Google ID or email, creates if not found, returns User object."""
    google_id = google_user_info.get("sub")
    email = google_user_info.get("email")
    name = google_user_info.get("name")

    if not google_id or not email:
        print("Error: Missing Google ID or email in user info.")
        return None, "Missing Google ID or email"

    try:
        # 1. Try finding by Google ID
        data_gid, count_gid = supabase.table("users").select("id, email, name, google_id").eq("google_id", google_id).maybe_single().execute()
        if data_gid and len(data_gid) > 1 and data_gid[1]:
            user_data = data_gid[1]
            print(f"Found existing user by Google ID: {email}")
            return User(id=user_data["id"], email=user_data["email"], name=user_data.get("name"), google_id=user_data.get("google_id")), None

        # 2. Try finding by email (maybe they registered normally first)
        data_email, count_email = supabase.table("users").select("id, email, name, google_id").eq("email", email).maybe_single().execute()
        if data_email and len(data_email) > 1 and data_email[1]:
            user_data = data_email[1]
            # User exists, link Google ID
            print(f"Found existing user by email: {email}. Linking Google ID.")
            update_data, update_count = supabase.table("users").update({"google_id": google_id, "name": user_data.get("name") or name}).eq("id", user_data["id"]).execute()
            # Check if update was successful
            if update_data and len(update_data) > 1 and len(update_data[1]) > 0:
                updated_user_data = update_data[1][0]
                return User(id=updated_user_data["id"], email=updated_user_data["email"], name=updated_user_data.get("name"), google_id=updated_user_data.get("google_id")), None
            else:
                print(f"Error linking Google ID for user {email}: {update_data}")
                return None, f"Failed to link Google ID: {update_data}"

        # 3. User doesn't exist, create new user with Google info
        print(f"Creating new user from Google Sign-In: {email}")
        user_data_insert = {
            "email": email,
            "name": name,
            "google_id": google_id,
            # No password hash needed for Google Sign-In users initially
            "password_hash": None 
        }
        insert_data, insert_count = supabase.table("users").insert(user_data_insert).execute()
        
        # Check if insert was successful
        if insert_data and len(insert_data) > 1 and len(insert_data[1]) > 0:
            created_user_info = insert_data[1][0]
            print(f"Successfully created user via Google: {email}")
            return User(id=created_user_info["id"], email=created_user_info["email"], name=created_user_info.get("name"), google_id=created_user_info.get("google_id")), None
        else:
            print(f"Error creating Google user {email}, Supabase response: {insert_data}")
            return None, f"Supabase error during Google user creation: {insert_data}"

    except Exception as e:
        print(f"Error interacting with Supabase (find_or_create_google_user): {e}")
        return None, str(e)

# --- Lead Management Functions --- #

