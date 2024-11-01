from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from bson import ObjectId
from flask_jwt_extended import JWTManager
from flask_jwt_extended.utils import decode_token
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import requests

load_dotenv()

app = Flask(__name__)

app.config["MONGO_URI"] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

app.config["JWT_SECRET_KEY"] = "123456"
jwt = JWTManager(app)

# Collection references
inventory_collection = mongo.db.inventory

# For inter service communication between user and inventory
def get_user_id_from_body():
    auth_header = request.headers.get("auth-token")
    
    if not auth_header:
        return None, None, None, "Token is missing"

    try:
        # Call the user microservice to get user details
        response = requests.get(
            f"{os.getenv('USER_MICROSERVICE_URL')}/user_id",
            headers={"auth-token": auth_header}
        )
        
        if response.status_code == 200:
            user_data = response.json()
            return user_data["user_id"], user_data["username"], user_data["email"], None
        elif response.status_code == 401:
            return None, None, None, "Invalid token"
        else:
            return None, None, None, "User not found or unauthorized"
    
    except Exception as e:
        return None, None, None, f"Error occurred: {str(e)}"

def delete_all_product(inventory_id):
    auth_header = request.headers.get("auth-token")
    if not auth_header:
        return None, "Token is missing"
    try:
        # Make a DELETE request to the product microservice
        product_service_url = f"{os.getenv('PRODUCT_MICROSERVICE_URL')}/products/delete_all/{inventory_id}"
        headers = {"auth-token": auth_header}
        response = requests.get(product_service_url, headers=headers)
        print(response.status_code,response.json())
        # Check response status
        if response.status_code == 200:
            return response.json(), None
        elif response.status_code == 404:
            return None, response.json()
        elif response.status_code == 401:
            return None, "Invalid token"
        else:
            error_msg = response.json().get("msg", "Unexpected error")
            return None, f"Error: {error_msg}"
    
    except requests.exceptions.RequestException as e:
        return None, f"Error occurred while contacting product service: {str(e)}"


@app.route('/', methods=['GET'])
def home():
    return jsonify({"msg": "Welcome to the API!"}), 200



@app.route('/checkInventory/<inventory_ID>', methods=['GET'])
def checkInventory(inventory_ID):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401  # Return error if user ID retrieval failed

    try:
        # Check if the inventory item exists and belongs to the user
        inventory_item = inventory_collection.find_one({"_id": ObjectId(inventory_ID), "user_id": user_id})

        if inventory_item:
            # Item exists and is owned by the user
            return jsonify(True), 200
        else:
            # Item not found or does not belong to the user
            return jsonify(False), 403  # Return False if unauthorized

    except Exception as e:
        # Handle any exceptions that occur during database access
        return jsonify({"msg": f"Error occurred while checking inventory: {str(e)}"}), 500


# Get Item is completed
@app.route('/items', methods=['GET'])
def get_items():
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Proceed with fetching items if the user_id is valid
    items = inventory_collection.find({"user_id": user_id})
    return jsonify([
        {
            "id": str(item["_id"]),
            "name": item["name"],
            "type": item["type"],
            "created_date": item["created_date"],
            "user_id": item["user_id"]
        }
        for item in items
    ]), 200

# Get Item by Id is completed
@app.route('/items/<item_id>', methods=['GET'])
def get_item(item_id):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Fetch the item and check that it belongs to the authenticated user
    item = mongo.db.inventory.find_one({"_id": ObjectId(item_id), "user_id": user_id})
    if item:
        return jsonify({
            "id": str(item["_id"]),
            "name": item["name"],
            "type": item["type"],
            "created_date": item["created_date"],
            "user_id": item["user_id"]
        }), 200
    
    return jsonify({"error": "Item not found or unauthorized"}), 404

# Create Item is also completed
@app.route('/createItem', methods=['POST'])
def create_item():
    user_id, username, email, error = get_user_id_from_body()
    if error:
        logging.error(f"Authentication error: {error}")
        return jsonify({"msg": error}), 401

    data = request.get_json()
    # Ensure required fields are provided
    if not data or 'name' not in data or 'type' not in data:
        return jsonify({"msg": "Invalid input data: 'name' and 'type' are required fields"}), 400

    # Construct new item
    new_item = {
        "name": data['name'],
        "type": data['type'],
        "created_date": datetime.utcnow().isoformat(),
        "user_id": user_id
    }

    try:
        # Insert the item into the inventory collection
        result = mongo.db.inventory.insert_one(new_item)
        new_item["_id"] = str(result.inserted_id)
        return jsonify(new_item), 201
    except Exception as e:
        logging.error(f"Database error: {e}")
        return jsonify({"msg": "Failed to create item"}), 500

# Update item is completed
@app.route('/items/<item_id>', methods=['PUT'])
def update_item(item_id):
    user_id, username, email, error = get_user_id_from_body()  # Get user details for authorization
    if error:
        return jsonify({"msg": error}), 401

    # Find the item by item_id and ensure it belongs to the authenticated user
    item = mongo.db.inventory.find_one({"_id": ObjectId(item_id), "user_id": user_id})
    if item:
        data = request.get_json()
        # Validate the incoming data for updates
        if 'name' not in data or 'type' not in data:
            return jsonify({"msg": "Invalid input data: 'name' and 'type' are required fields"}), 400

        # Prepare updated data
        updated_data = {
            "name": data['name'],
            "type": data['type']
        }
        
        # Update the item in the database
        mongo.db.inventory.update_one({"_id": ObjectId(item_id)}, {"$set": updated_data})
        item.update(updated_data)

        return jsonify({
            "id": str(item["_id"]),
            "name": item["name"],
            "type": item["type"],
            "created_date": item["created_date"],
            "user_id": item["user_id"]
        }), 200

    return jsonify({"error": "Item not found or unauthorized"}), 404

# Delete Item is completed
@app.route('/items/<item_id>', methods=['DELETE'])
def delete_item(item_id):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        logging.error(f"User authentication failed: {error}")
        return jsonify({"msg": error}), 401

    try:
        # First, delete all related products
        logging.info(f"Deleting all related products for item {item_id}")
        delete_result, delete_error = delete_all_product(item_id)
        if delete_error:
            logging.error(f"Failed to delete related products for item {item_id}: {delete_error}")
            return jsonify({"error": f"Failed to delete related products: {delete_error}"}), 500

        # If product deletion is successful, proceed to delete the item from inventory
        logging.info(f"Attempting to delete item {item_id} from inventory for user {username} (ID: {user_id})")
        result = mongo.db.inventory.delete_one({"_id": ObjectId(item_id), "user_id": user_id})

        if result.deleted_count:
            logging.info(f"Successfully deleted item {item_id} from inventory for user {username} (ID: {user_id})")
            return jsonify({"msg": "Item and all related products deleted successfully"}), 204
        else:
            logging.warning(f"Item not found or unauthorized for user {username} (ID: {user_id})")
            return jsonify({"error": "Item not found or unauthorized"}), 404

    except Exception as e:
        logging.error(f"Exception occurred while deleting item {item_id}: {str(e)}")
        return jsonify({"error": "Failed to delete item"}), 500



if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
