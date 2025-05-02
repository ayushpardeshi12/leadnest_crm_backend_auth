# User model for Flask-Login
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, email, name=None, google_id=None):
        self.id = id
        self.email = email
        self.name = name or email # Use email if name is not available
        self.google_id = google_id

    # Flask-Login requires get_id method
    def get_id(self):
           return str(self.id)

    # Add any other user-specific methods or properties if needed

