from flask import Flask, request, jsonify, session
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId
from dotenv import load_dotenv
from functools import wraps
import jwt
import bcrypt
import secrets
import os
import math
import traceback
import re
import urllib.parse
import requests
import threading
try:
    import certifi
    ca = certifi.where()
except ImportError:
    ca = None

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Enhanced session configuration for Vercel deployment
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Required for cross-origin
app.config['SESSION_COOKIE_SECURE'] = True     # Required for HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.getenv('SESSION_DURATION_DAYS', 7)))

# For Vercel, we need to handle sessions differently
app.config['SESSION_COOKIE_DOMAIN'] = os.getenv('COOKIE_DOMAIN', None)

# CORS configuration - more permissive for production debugging
CORS(
    app,
    origins=[
        "https://ayurvedic-app.vercel.app",
        "https://*.vercel.app",  # Allow all vercel subdomains
        "http://localhost:3000", 
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ],
    allow_headers=[
        "Content-Type", 
        "Authorization", 
        "Cache-Control", 
        "X-Requested-With",
        "Access-Control-Allow-Credentials",
        "Access-Control-Allow-Origin"
    ],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    supports_credentials=True,
    expose_headers=["Set-Cookie"]
)

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://admin:admin123@cluster0.tafpwxo.mongodb.net/')

client = None
db = None

def connect_to_mongodb():
    """Connect to MongoDB"""
    global client, db
    
    try:
        # Get public IP for debugging
        try:
            public_ip = requests.get('https://api.ipify.org', timeout=5).text
            print(f"Your Public IP is: {public_ip}")
            print(f"Make sure this IP is added to MongoDB Atlas Network Access!")
        except:
            print("Could not detect public IP")

        client_kwargs = {
            'serverSelectionTimeoutMS': 5000,
            'connectTimeoutMS': 5000
        }
        
        if ca:
            client_kwargs['tlsCAFile'] = ca
        
        client = MongoClient(MONGO_URI, **client_kwargs)
        
        client.admin.command('ping')
        db = client['kuzhiveil_dentals']
        
        print("Connected to MongoDB successfully!")
        return True
        
    except Exception as e:
        print(f"MongoDB connection failed: {str(e)}")
        # Try again without certificate validation if first attempt fails
        try:
            print("Attempting connection without certificate validation...")
            client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                tlsAllowInvalidCertificates=True
            )
            client.admin.command('ping')
            db = client['kuzhiveil_dentals']
            print("Connected to MongoDB successfully (insecure mode)!")
            return True
        except Exception as e2:
            print(f"Secondary connection attempt failed: {str(e2)}")
            return False

# Try to connect
if not connect_to_mongodb():
    print("Starting without database connection...")

# Collections
patients_collection = db['patients'] if db is not None else None
admins_collection = db['admins'] if db is not None else None

# --- Helper Functions ---
def format_time_12h(time_str):
    """Convert 24h time string (HH:MM) to 12h format (HH:MM AM/PM)"""
    try:
        if not time_str:
            return time_str
        dt = datetime.strptime(time_str, "%H:%M")
        return dt.strftime("%I:%M %p")
    except Exception:
        return time_str

# JWT Helper Functions
def generate_token(admin_id, username):
    """Generate JWT token for authentication"""
    try:
        payload = {
            'admin_id': str(admin_id),
            'username': username,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow()
        }
        
        secret_key = app.config['SECRET_KEY']
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        print(f"Generated token for {username}: {token[:50]}...")  # Debug log
        return token
        
    except Exception as e:
        print(f"Error generating token: {e}")
        return None

def verify_token(token):
    """Improved token verification with better error handling"""
    try:
        secret_key = app.config['SECRET_KEY']
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        
        # Check if token is expired
        exp_timestamp = payload.get('exp')
        if exp_timestamp:
            current_timestamp = datetime.utcnow().timestamp()
            if current_timestamp > exp_timestamp:
                print("Token has expired")
                return None
        
        print(f"Token verified successfully for user: {payload.get('username')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        print("JWT Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

# Initialize default admin
def initialize_admin():
    if admins_collection is None:
        print("Cannot initialize admin - no database connection")
        return
        
    try:
        existing_admin = admins_collection.find_one({'username': 'admin'})
        if not existing_admin:
            hashed_password = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt())
            admin_doc = {
                'username': 'admin',
                'password': hashed_password,
                'email': 'admin@kuzhiveil.com',
                'role': 'super_admin',
                'created_at': datetime.now(),
                'last_login': None,
                'is_active': True
            }
            admins_collection.insert_one(admin_doc)
            print("Default admin created")
        else:
            print("Admin user already exists")
    except Exception as e:
        print(f"Error initializing admin: {e}")

initialize_admin()

# Database health check
def check_db_connection():
    """Check if database is connected and accessible"""
    if client is None or db is None:
        return False
    try:
        client.admin.command('ping')
        return True
    except Exception:
        return False

# Helper functions
def serialize_patient(patient):
    """Serialize patient document and handle field mapping from different sources"""
    if not patient:
        return None
        
    # Standardize field names (mapping common CSV variations to our API format)
    mappings = {
        'Reg No': 'regno',
        'Name': 'name',
        'Phone': 'phone',
        'Age': 'age',
        'Date': 'created_at',
        'OP No': 'op_no'
    }
    
    for old_key, new_key in mappings.items():
        if old_key in patient and new_key not in patient:
            patient[new_key] = patient[old_key]

    # Convert ObjectId to string
    patient['_id'] = str(patient['_id'])
    
    # Handle NaN values and ensure all expected fields exist
    for key, value in patient.items():
        if isinstance(value, float) and math.isnan(value):
            patient[key] = None
        elif value is None:
            patient[key] = None
            
    # Ensure mandatory fields for frontend are at least present as empty/null
    for field in ['regno', 'name', 'phone', 'age', 'created_at']:
        if field not in patient:
            patient[field] = None
                
    return patient

def serialize_admin(admin):
    """Serialize admin document"""
    if admin:
        admin['_id'] = str(admin['_id'])
        admin.pop('password', None)
        
        # Handle NaN values and None
        for key, value in admin.items():
            if isinstance(value, float) and math.isnan(value):
                admin[key] = None
                
    return admin

def find_patient_by_regno(regno):
    """Find patient by registration number with proper URL decoding"""
    try:
        if patients_collection is None:
            return None
        
        # URL decode the registration number
        search_regno = urllib.parse.unquote(str(regno)).strip()
        
        # Try exact match first on both possible field names
        patient = patients_collection.find_one({
            '$or': [
                {'regno': search_regno},
                {'Reg No': search_regno}
            ]
        })
        if patient:
            return patient
            
        # If not found, try case-insensitive search on both
        patient = patients_collection.find_one({
            '$or': [
                {'regno': {'$regex': f'^{re.escape(search_regno)}$', '$options': 'i'}},
                {'Reg No': {'$regex': f'^{re.escape(search_regno)}$', '$options': 'i'}}
            ]
        })
        
        return patient
        
    except Exception as e:
        print(f"Error finding patient by regno: {e}")
        return None

def is_regno_exists(regno):
    """Check if registration number already exists"""
    try:
        if patients_collection is None:
            return False
        
        search_regno = str(regno).strip()
        existing = patients_collection.find_one({
            '$or': [
                {'regno': search_regno},
                {'Reg No': search_regno}
            ]
        })
        return existing is not None
        
    except Exception as e:
        print(f"Error checking regno existence: {e}")
        return False

def validate_patient_data(data, is_update=False):
    """Validate patient data and return list of errors"""
    errors = []
    
    try:
        # Required fields validation
        if not data.get('name', '').strip():
            errors.append('Name is required')
        
        if not data.get('age'):
            errors.append('Age is required')
        elif not isinstance(data['age'], (int, str)) or not str(data['age']).isdigit():
            errors.append('Age must be a valid number')
        elif int(data['age']) <= 0:
            errors.append('Age must be greater than 0')
        
        if not is_update and not data.get('regno', '').strip():
            errors.append('Registration number is required')
        
        # Phone validation (if provided)
        phone = data.get('phone', '').strip()
        if phone:
            # Remove any non-digit characters for validation
            phone_digits = ''.join(filter(str.isdigit, phone))
            if len(phone_digits) != 10:
                errors.append('Phone number must be exactly 10 digits')
        
    except Exception as e:
        errors.append(f'Validation error: {str(e)}')
    
    return errors
# ==================== WHATSAPP INTEGRATION ====================

WHATSAPP_API_URL = os.getenv(
    "WHATSAPP_API_URL",
    "http://localhost:5001/send"  # CHANGE THIS
)

def send_whatsapp(phone, message):
    """Send WhatsApp message via Node backend"""
    try:
        requests.post(WHATSAPP_API_URL, json={
            "phone": phone,
            "message": message
        }, timeout=5)
    except Exception as e:
        print("❌ WhatsApp send failed:", e)


def send_whatsapp_async(phone, message):
    """Non-blocking WhatsApp sender"""
    threading.Thread(
        target=send_whatsapp,
        args=(phone, message)
    ).start()

# Update the authentication functions

def is_authenticated():
    """Enhanced authentication check with better JWT handling"""
    try:
        # For production, prioritize JWT token authentication
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            payload = verify_token(token)
            
            if payload:
                # Store in session for this request
                session['authenticated'] = True
                session['admin_id'] = payload['admin_id']
                session['username'] = payload['username']
                return True
            else:
                # Clear invalid session data
                session.clear()
                return False
        
        # Fallback to session-based auth (for local development)
        authenticated = session.get('authenticated', False)
        admin_id = session.get('admin_id')
        
        if authenticated and admin_id:
            return True
        
        return False
        
    except Exception as e:
        print(f"Authentication error: {e}")
        session.clear()
        return False

# Authentication decorator
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        return f(*args, **kwargs)
    return wrapper

# ==================== AUTH ROUTES ====================

@app.route('/api/auth/refresh', methods=['POST'])
def refresh_token():
    """Add token refresh endpoint"""
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': 'No token provided'
            }), 401
        
        token = auth_header.split(' ')[1]
        payload = verify_token(token)
        
        if not payload:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired token'
            }), 401
        
        # Generate new token
        new_token = generate_token(payload['admin_id'], payload['username'])
        
        if not new_token:
            return jsonify({
                'success': False,
                'error': 'Failed to generate new token'
            }), 500
        
        return jsonify({
            'success': True,
            'token': new_token
        })
        
    except Exception as e:
        print(f"Token refresh error: {e}")
        return jsonify({
            'success': False,
            'error': 'Token refresh failed'
        }), 500

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Improved auth check with better error handling"""
    try:
        if is_authenticated():
            admin_id = session.get('admin_id')
            username = session.get('username')
            
            # Basic admin data fallback
            admin_data = {
                'username': username or 'Unknown',
                'role': 'admin',
                '_id': admin_id
            }
            
            # Try to get full admin details from database
            if admin_id and admins_collection is not None:
                try:
                    # Handle both string and ObjectId admin_id
                    admin = None
                    if isinstance(admin_id, str):
                        if ObjectId.is_valid(admin_id):
                            admin = admins_collection.find_one({'_id': ObjectId(admin_id)})
                        else:
                            # Fallback to username lookup
                            admin = admins_collection.find_one({'username': username})
                    else:
                        admin = admins_collection.find_one({'_id': admin_id})
                    
                    if admin:
                        admin_data = serialize_admin(admin.copy())
                        
                except Exception as db_error:
                    print(f"Admin lookup error (non-critical): {db_error}")
                    # Continue with fallback admin_data
            
            return jsonify({
                'success': True,
                'authenticated': True,
                'admin': admin_data
            })
        
        # Not authenticated
        return jsonify({
            'success': False,
            'authenticated': False
        })
        
    except Exception as e:
        print(f"Auth check error: {e}")
        traceback.print_exc()  # Add this for better debugging
        
        # Return a safe fallback response instead of 500
        return jsonify({
            'success': False,
            'authenticated': False,
            'error': 'Authentication check failed'
        }), 200  # Changed from 500 to 200 to prevent frontend errors

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Enhanced admin login with JWT token"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({
                'success': False,
                'error': 'Username and password are required'
            }), 400

        if not check_db_connection() or admins_collection is None:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 503

        admin = admins_collection.find_one({'username': username})
        if not admin:
            return jsonify({
                'success': False,
                'error': 'Invalid username or password'
            }), 401

        if not admin.get('is_active', True):
            return jsonify({
                'success': False,
                'error': 'Account is deactivated'
            }), 401

        if bcrypt.checkpw(password.encode('utf-8'), admin['password']):
            # Generate JWT token
            token = generate_token(admin['_id'], admin['username'])
            
            if not token:
                return jsonify({
                    'success': False,
                    'error': 'Failed to generate authentication token'
                }), 500
            
            # Set session with consistent data types
            session.clear()
            session['authenticated'] = True
            session['admin_id'] = str(admin['_id'])  # Always store as string
            session['username'] = admin['username']
            session['login_time'] = datetime.now().isoformat()
            session.permanent = True

            print(f"Login successful - admin_id: {session['admin_id']}, username: {session['username']}")

            # Update last login in database
            try:
                admins_collection.update_one(
                    {'_id': admin['_id']},
                    {'$set': {'last_login': datetime.now()}}
                )
            except Exception as e:
                print(f"Failed to update last login: {e}")

            return jsonify({
                'success': True,
                'message': 'Login successful',
                'admin': serialize_admin(admin.copy()),
                'token': token
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid username or password'
            }), 401

    except Exception as e:
        print(f"Login error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Login failed due to server error'
        }), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout admin"""
    try:
        session.clear()
        return jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
    except Exception as e:
        print(f"Logout error: {e}")
        return jsonify({
            'success': False,
            'error': 'Logout failed'
        }), 500

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    """Change admin password with improved error handling"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')

        if not current_password or not new_password:
            return jsonify({
                'success': False,
                'error': 'Current and new password are required'
            }), 400

        if len(new_password) < 6:
            return jsonify({
                'success': False,
                'error': 'New password must be at least 6 characters'
            }), 400

        admin_id = session.get('admin_id')
        username = session.get('username')
        
        if not admin_id or admins_collection is None:
            return jsonify({
                'success': False,
                'error': 'Authentication failed'
            }), 401

        print(f"Attempting password change for admin_id: {admin_id}, username: {username}")

        # Try to find admin by ID first, then by username as fallback
        admin = None
        
        # Try ObjectId lookup if admin_id looks like a valid ObjectId
        if isinstance(admin_id, str) and ObjectId.is_valid(admin_id):
            try:
                admin = admins_collection.find_one({'_id': ObjectId(admin_id)})
                print(f"Found admin by ObjectId: {admin is not None}")
            except Exception as e:
                print(f"ObjectId lookup failed: {e}")
        
        # Fallback to username lookup if ID lookup failed
        if not admin and username:
            admin = admins_collection.find_one({'username': username})
            print(f"Found admin by username: {admin is not None}")
        
        # Final fallback - try string ID lookup
        if not admin:
            admin = admins_collection.find_one({'_id': admin_id})
            print(f"Found admin by string ID: {admin is not None}")

        if not admin:
            print(f"Admin not found with admin_id: {admin_id}, username: {username}")
            return jsonify({
                'success': False,
                'error': 'Admin not found'
            }), 404

        # Verify current password
        if not bcrypt.checkpw(current_password.encode('utf-8'), admin['password']):
            print("Current password verification failed")
            return jsonify({
                'success': False,
                'error': 'Current password is incorrect'
            }), 400

        # Hash new password
        hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())

        # Update password using the same lookup criteria that worked
        update_result = None
        
        if isinstance(admin['_id'], ObjectId):
            update_result = admins_collection.update_one(
                {'_id': admin['_id']},
                {'$set': {'password': hashed_new_password}}
            )
        else:
            # Fallback to username update
            update_result = admins_collection.update_one(
                {'username': admin['username']},
                {'$set': {'password': hashed_new_password}}
            )

        if update_result is not None and update_result.modified_count > 0:
            print(f"Password updated successfully for {admin['username']}")
            return jsonify({
                'success': True,
                'message': 'Password changed successfully'
            })
        else:
            print("Password update failed - no documents modified")
            return jsonify({
                'success': False,
                'error': 'Password update failed'
            }), 500

    except Exception as e:
        print(f"Change password error: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Password change failed: {str(e)}'
        }), 500

# ==================== PATIENT ROUTES ====================

@app.route('/api/patients', methods=['GET'])
@require_auth
def get_patients():
    """Get all patients with pagination and search"""
    try:
        if not check_db_connection() or patients_collection is None:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 503

        # Get query parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        search = request.args.get('search', '').strip()

        # Calculate skip value
        skip = (page - 1) * limit

        # Build search query
        query = {}
        if search:
            query = {
                '$or': [
                    {'name': {'$regex': search, '$options': 'i'}},
                    {'Name': {'$regex': search, '$options': 'i'}},
                    {'regno': {'$regex': search, '$options': 'i'}},
                    {'Reg No': {'$regex': search, '$options': 'i'}},
                    {'phone': {'$regex': search, '$options': 'i'}},
                    {'Phone': {'$regex': search, '$options': 'i'}},
                    {'created_at': {'$regex': search, '$options': 'i'}},
                    {'Date': {'$regex': search, '$options': 'i'}}
                ]
            }

        # Get total count
        total_count = patients_collection.count_documents(query)

        # Get patients with pagination
        patients = list(patients_collection.find(query)
                        .sort([('created_at', -1), ('Date', -1)])
                       .skip(skip)
                       .limit(limit))

        # Serialize patients
        serialized_patients = [serialize_patient(patient) for patient in patients]

        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit

        return jsonify({
            'success': True,
            'data': serialized_patients,
            'pagination': {
                'page': page,
                'limit': limit,
                'total_count': total_count,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })

    except Exception as e:
        print(f"Get patients error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch patients'
        }), 500

@app.route('/api/patients', methods=['POST'])
@require_auth
def create_patient():
    """Create a new patient"""
    try:
        if not check_db_connection() or patients_collection is None:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 503

        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        # Validate patient data
        errors = validate_patient_data(data)
        if errors:
            return jsonify({
                'success': False,
                'error': '; '.join(errors)
            }), 400

        # Check if registration number already exists
        if is_regno_exists(data['regno']):
            return jsonify({
                'success': False,
                'error': 'Registration number already exists'
            }), 400

        # Create patient document
        patient_doc = {
            'regno': data['regno'].strip(),
            'name': data['name'].strip(),
            'address': data.get('address', '').strip(),
            'phone': data.get('phone', '').strip(),
            'age': int(data['age']),
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }

        # Insert patient
        result = patients_collection.insert_one(patient_doc)
        patient_doc['_id'] = result.inserted_id
        
        if patient_doc.get("phone"):
          phone = "91" + ''.join(filter(str.isdigit, patient_doc["phone"]))
          msg = (
              f"🦷 *Kuzhivelil Multi Speciality Dental Care* 🦷\n\n"
              f"📄 *OP Number:* {patient_doc['regno']}\n"
              f"👤 *Patient Name:* {patient_doc['name']}\n\n"
              f"Thank you for choosing us for your dental care needs.\n"
              f"We’re excited to continue keeping your smile healthy and bright✨...!"
          )
          send_whatsapp_async(phone, msg)

        return jsonify({
            'success': True,
            'message': 'Patient created successfully',
            'patient': serialize_patient(patient_doc)
        }), 201

    except Exception as e:
        print(f"Create patient error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to create patient'
        }), 500

@app.route('/api/patients/<path:regno>', methods=['PUT'])
@require_auth
def update_patient(regno):
    """Update a patient"""
    try:
        if not check_db_connection() or patients_collection is None:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 503

        # URL decode the registration number
        decoded_regno = urllib.parse.unquote(regno).strip()
        print(f"Update request for regno: '{regno}' -> decoded: '{decoded_regno}'")

        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        # Find existing patient
        existing_patient = find_patient_by_regno(decoded_regno)
        if not existing_patient:
            print(f"Patient not found for regno: '{decoded_regno}'")
            return jsonify({
                'success': False,
                'error': 'Patient not found'
            }), 404

        # Validate patient data
        errors = validate_patient_data(data, is_update=True)
        if errors:
            return jsonify({
                'success': False,
                'error': '; '.join(errors)
            }), 400

        # Update patient document
        update_doc = {
            'name': data['name'].strip(),
            'address': data.get('address', '').strip(),
            'phone': data.get('phone', '').strip(),
            'age': int(data['age']),
            'updated_at': datetime.now()
        }

        # Update using the exact regno from database
        patients_collection.update_one(
            {'regno': existing_patient['regno']},
            {'$set': update_doc}
        )

        # Get updated patient
        updated_patient = find_patient_by_regno(existing_patient['regno'])

        return jsonify({
            'success': True,
            'message': 'Patient updated successfully',
            'patient': serialize_patient(updated_patient)
        })

    except Exception as e:
        print(f"Update patient error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to update patient'
        }), 500

@app.route('/api/patients/<path:regno>', methods=['DELETE'])
@require_auth
def delete_patient(regno):
    """Delete a patient"""
    try:
        if not check_db_connection() or patients_collection is None:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 503

        # URL decode the registration number
        decoded_regno = urllib.parse.unquote(regno).strip()
        print(f"Delete request for regno: '{regno}' -> decoded: '{decoded_regno}'")

        # Find existing patient
        existing_patient = find_patient_by_regno(decoded_regno)
        if not existing_patient:
            print(f"Patient not found for regno: '{decoded_regno}'")
            return jsonify({
                'success': False,
                'error': 'Patient not found'
            }), 404

        # Delete using the exact regno from database
        result = patients_collection.delete_one({'regno': existing_patient['regno']})
        
        if result.deleted_count == 0:
            return jsonify({
                'success': False,
                'error': 'Patient not found'
            }), 404

        return jsonify({
            'success': True,
            'message': 'Patient deleted successfully'
        })

    except Exception as e:
        print(f"Delete patient error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to delete patient'
        }), 500
# ==================== APPOINTMENT ROUTES ====================

@app.route('/api/appointments', methods=['POST'])
@require_auth
def create_appointment():
    try:
        data = request.get_json()

        regno = data.get("regno")
        date = data.get("date")
        time = data.get("time")

        if not regno or not date or not time:
            return jsonify({
                "success": False,
                "error": "regno, date and time required"
            }), 400

        patient = find_patient_by_regno(regno)

        if not patient:
            return jsonify({
                "success": False,
                "error": "Patient not found"
            }), 404

        # Save appointment
        appointment_doc = {
            "regno": regno,
            "date": date,
            "time": time,
            "datetime": datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M"),
            "created_at": datetime.now()
        }

        db['appointments'].insert_one(appointment_doc)

        # 🔥 SEND WHATSAPP MESSAGE
        if patient.get("phone"):
            phone = "91" + ''.join(filter(str.isdigit, patient["phone"]))

            message = (
                f"🦷 *Kuzhivelil Dental Care*\n\n"
                f"Dear Patient,\n"
                f"Your appointment has been successfully booked with *Kuzhivelil Dental Care*.\n\n"
                f"📅 *Date:* {date}\n"
                f"⏰ *Time:* {format_time_12h(time)}\n\n"
                f"Please arrive 10 minutes early for your consultation. For any changes or queries, feel free to contact us at 📞 +91 82812 95098.\n\n"
                f"We look forward to taking care of your smile! 😊\n\n"
                f"— *This is an automated system-generated message*"
            )

            send_whatsapp_async(phone, message)

        return jsonify({
            "success": True,
            "message": "Appointment scheduled"
        })

    except Exception as e:
        print("Appointment error:", e)
        return jsonify({
            "success": False,
            "error": "Failed to schedule appointment"
        }), 500

@app.route('/api/appointments', methods=['GET'])
@require_auth
def get_appointments():
    """Get all appointments, auto-deleting past ones, and grouped by date"""
    try:
        # Auto-delete past appointments (older than today)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        db['appointments'].delete_many({'datetime': {'$lt': today_start}})

        # Get query parameters
        search = request.args.get('search', '').strip()
        
        # Build query
        query = {}
        if search:
            # First find patients matching search
            matching_patients = list(patients_collection.find({
                '$or': [
                    {'name': {'$regex': search, '$options': 'i'}},
                    {'regno': {'$regex': search, '$options': 'i'}},
                    {'phone': {'$regex': search, '$options': 'i'}}
                ]
            }, {'regno': 1}))
            
            matching_regnos = [p['regno'] for p in matching_patients]
            
            query = {
                '$or': [
                    {'regno': {'$in': matching_regnos}},
                    {'date': {'$regex': search, '$options': 'i'}}
                ]
            }

        # Get appointments sorted by date and time
        appointments = list(db['appointments'].find(query).sort([('date', 1), ('time', 1)]))
        
        # Serialize and join with patient names
        serialized = []
        for appt in appointments:
            appt['_id'] = str(appt['_id'])
            
            # Find patient name
            patient = patients_collection.find_one({'regno': appt['regno']}, {'name': 1, 'phone': 1})
            if patient:
                appt['patient_name'] = patient['name']
                appt['patient_phone'] = patient.get('phone', 'N/A')
            else:
                appt['patient_name'] = 'Unknown Patient'
                appt['patient_phone'] = 'N/A'
                
            serialized.append(appt)

        return jsonify({
            'success': True,
            'data': serialized
        })

    except Exception as e:
        print(f"Get appointments error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch appointments'
        }), 500

@app.route('/api/appointments/<id>', methods=['PUT'])
@require_auth
def update_appointment(id):
    """Update an appointment (date and time)"""
    try:
        if not ObjectId.is_valid(id):
            return jsonify({'success': False, 'error': 'Invalid appointment ID'}), 400
            
        data = request.get_json()
        date = data.get('date')
        time = data.get('time')
        
        if not date or not time:
            return jsonify({'success': False, 'error': 'Date and time are required'}), 400
            
        # Update document
        update_doc = {
            'date': date,
            'time': time,
            'datetime': datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M"),
            'updated_at': datetime.now()
        }
        
        result = db['appointments'].update_one(
            {'_id': ObjectId(id)},
            {'$set': update_doc}
        )
        
        if result.matched_count == 0:
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
            
        # 🔥 SEND WHATSAPP MESSAGE FOR RESCHEDULE
        try:
            # Get appointment details to find patient
            appt = db['appointments'].find_one({'_id': ObjectId(id)})
            if appt:
                patient = find_patient_by_regno(appt['regno'])
                if patient and patient.get("phone"):
                    phone = "91" + ''.join(filter(str.isdigit, patient["phone"]))
                    message = (
                        f"🦷 *Kuzhivelil Dental Care*\n\n"
                        f"Dear Patient,\n"
                        f"Your appointment has been successfully *rescheduled* with *Kuzhivelil Dental Care*.\n\n"
                        f"📅 *Date:* {date}\n"
                        f"⏰ *Time:* {format_time_12h(time)}\n\n"
                        f"Please arrive 10 minutes early for your consultation. For any changes or queries, feel free to contact us at 📞 +91 82812 95098.\n\n"
                        f"We look forward to taking care of your smile! 😊\n\n"
                        f"— *This is an automated system-generated message*"
                    )
                    send_whatsapp_async(phone, message)
        except Exception as e:
            print(f"Failed to send reschedule notification: {e}")

        return jsonify({
            'success': True,
            'message': 'Appointment updated successfully'
        })

    except Exception as e:
        print(f"Update appointment error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to update appointment'
        }), 500

@app.route('/api/appointments/<id>', methods=['DELETE'])
@require_auth
def delete_appointment(id):
    """Delete an appointment"""
    try:
        if not ObjectId.is_valid(id):
            return jsonify({'success': False, 'error': 'Invalid appointment ID'}), 400
            
        result = db['appointments'].delete_one({'_id': ObjectId(id)})
        
        if result.deleted_count == 0:
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
            
        return jsonify({
            'success': True,
            'message': 'Appointment deleted successfully'
        })

    except Exception as e:
        print(f"Delete appointment error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to delete appointment'
        }), 500

@app.route('/api/reminder', methods=['GET'])
def send_reminders():
    try:
        now = datetime.now()
        future = now + timedelta(hours=6)

        appointments = db['appointments'].find({
            "datetime": {"$gte": now, "$lte": future}
        })

        count = 0

        for appt in appointments:
            patient = find_patient_by_regno(appt["regno"])

            if patient and patient.get("phone"):
                phone = "91" + ''.join(filter(str.isdigit, patient["phone"]))

                message = f"Reminder: Your appointment is at {format_time_12h(appt['time'])} today."

                send_whatsapp_async(phone, message)
                count += 1

        return jsonify({
            "success": True,
            "sent": count
        })

    except Exception as e:
        print("Reminder error:", e)
        return jsonify({
            "success": False
        })

@app.route('/api/dashboard/stats', methods=['GET'])
@require_auth
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        if not check_db_connection() or patients_collection is None:
            return jsonify({
                'success': True,
                'total_patients': 0,
                'today_registrations': 0,
                'month_registrations': 0,
                'latest_patients': []
            })

        # Get current date info
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        month_start = datetime(now.year, now.month, 1)

        # Get statistics
        total_patients = patients_collection.count_documents({})
        
        # Today's date as string for string-based comparisons
        today_str = today_start.strftime('%Y-%m-%d')
        month_str = month_start.strftime('%Y-%m')

        today_registrations = patients_collection.count_documents({
            '$or': [
                {'created_at': {'$gte': today_start}},
                {'Date': {'$gte': today_start}},
                {'created_at': {'$regex': f'^{today_str}'}},
                {'Date': {'$regex': f'^{today_str}'}}
            ]
        })
        
        month_registrations = patients_collection.count_documents({
            '$or': [
                {'created_at': {'$gte': month_start}},
                {'Date': {'$gte': month_start}},
                {'created_at': {'$regex': f'^{month_str}'}},
                {'Date': {'$regex': f'^{month_str}'}}
            ]
        })

        today_appointments = db['appointments'].count_documents({
            'datetime': {'$gte': today_start, '$lt': today_start + timedelta(days=1)}
        })

        # Get latest 5 patients
        latest_patients = list(patients_collection.find()
                             .sort([('created_at', -1), ('Date', -1)])
                             .limit(5))

        # Serialize latest patients
        serialized_latest = [serialize_patient(patient) for patient in latest_patients]

        return jsonify({
            'success': True,
            'total_patients': total_patients,
            'today_registrations': today_registrations,
            'month_registrations': month_registrations,
            'today_appointments': today_appointments,
            'latest_patients': serialized_latest
        })

    except Exception as e:
        print(f"Dashboard stats error: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to fetch dashboard stats'
        }), 500

# Add a health check endpoint for debugging
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'success': True,
        'message': 'API is running',
        'timestamp': datetime.now().isoformat(),
        'db_connected': check_db_connection()
    })

if __name__ == '__main__':
    print(f"Starting Kuzhiveil Dentals API server...")
    print(f"Session lifetime: {app.config['PERMANENT_SESSION_LIFETIME']}")
    app.run(debug=True, host='0.0.0.0', port=5000)