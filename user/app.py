from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_jwt_extended.utils import decode_token  # Import decode_token for manual decoding
from datetime import timedelta
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

# Use pbkdf2:sha256 as the hashing algorithm


# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# MongoDB configuration
app.config["MONGO_URI"] = os.getenv("MONGO_URI")  # Set this in your .env file
mongo = PyMongo(app)

# JWT Configuration
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")   # Replace with a strong secret key
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=1)  # Set token expiry to 1 day
jwt = JWTManager(app)

# Collection references
users_collection = mongo.db.user  

### Route: Get User ID Only (Retrieve user ID by token)
@app.route('/user_id', methods=['GET'])
def user_id():
    auth_header = request.headers.get("auth-token")
    
    if not auth_header:
        return jsonify({"msg": "Token is missing"}), 400
    
    token = auth_header
    try:
        user_id = decode_token(token)["sub"]  # Get the user ID from the token's 'sub' field
    except Exception as e:
        return jsonify({"msg": f"Invalid token: {str(e)}"}), 401

    # Check if the user exists
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return jsonify({
            "user_id": str(user["_id"]),
            "username": user["username"],
            "email": user["email"]
        }), 200
    
    return jsonify({"msg": "User not found"}), 404

### Route: Sign-Up (User Registration)
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    # Check if email already exists
    if users_collection.find_one({"email": email}):
        return jsonify({"msg": "Email already exists"}), 409

    # Hash the password and store new user in MongoDB
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    users_collection.insert_one({
        "username": username,
        "email": email,
        "password": hashed_password,
        "token": None  # Initialize token as None
    })
    return jsonify({"msg": "User created successfully"}), 201

### Route: Sign-In (Authenticate and Get JWT Token)
@app.route('/signin', methods=['POST'])
def signin():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    # Find user by username
    user = users_collection.find_one({"username": username})
    
    if user and check_password_hash(user["password"], password):
        # Create JWT token for the user
        access_token = create_access_token(identity=str(user["_id"]))

        # Update user document with the new token
        users_collection.update_one({"_id": user["_id"]}, {"$set": {"token": access_token}})
        
        return jsonify(access_token=access_token), 200

    return jsonify({"msg": "Invalid username or password"}), 401

### Route: Logout (Clear JWT Token)
@app.route('/logout', methods=['POST'])
def logout():
    # Retrieve the token from the Authorization header
    auth_header = request.headers.get("auth-token")
    if not auth_header:
        return jsonify({"msg": "Token is missing"}), 400

    # Extract the token from the header
    token=auth_header
    try:
        user_id = decode_token(token)["sub"]  # Get the user ID from the token's 'sub' field
    except Exception as e:
        return jsonify({"msg": f"Invalid token: {str(e)}"}), 401

    users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"token": None}})
    return jsonify({"msg": "Logged out successfully"}), 200


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001, debug=True)
