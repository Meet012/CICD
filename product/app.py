from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from flask_jwt_extended import JWTManager
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import requests
from urllib.parse import quote as url_quote

load_dotenv()

app = Flask(__name__)

# MongoDB connection configuration
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "123456")
jwt = JWTManager(app)

# Collection references
products_collection = mongo.db.product

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

def check_inventory(inventory_id):
    try:
        # Call the inventory microservice to check if the inventory item exists
        inventory_service_url = f"{os.getenv('INVENTORY_MICROSERVICE_URL')}/checkInventory/{inventory_id}"
        auth_header = request.headers.get("auth-token")
        # Include the auth token in the headers for authentication
        headers = {"auth-token": auth_header}
        response = requests.get(inventory_service_url, headers=headers)

        if response.status_code == 200:
            # If the inventory item exists and is owned by the user
            return True
        elif response.status_code == 403:
            # The inventory item exists but does not belong to the user
            return False
        elif response.status_code == 404:
            # The inventory item does not exist
            return False
        else:
            # Handle unexpected status codes
            raise Exception("Error checking inventory: unexpected response")

    except requests.exceptions.RequestException as e:
        raise Exception(f"Error occurred while contacting inventory service: {str(e)}")

# For creating a product in an inventory 
@app.route('/createProduct/<inventory_ID>', methods=['POST'])
def create_product(inventory_ID):
    data = request.get_json()

    # Validate input data
    if not data or 'name' not in data or 'price' not in data or 'quantity' not in data or 'type' not in data:
        return jsonify({"msg": "Invalid input data. Required fields: 'name', 'price', 'quantity', 'type'."}), 400

    # Ensure the type is either 'buy' or 'sell'
    if data['type'] not in ['buy', 'sell']:
        return jsonify({"msg": "Type must be either 'buy' or 'sell'."}), 400

    # Get user details and validate inventory existence
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401  # Return error if user ID retrieval failed

    # Check if the inventory item exists
    if not check_inventory(inventory_ID):
        return jsonify({"msg": "Inventory item does not exist or unauthorized."}), 404

    # Set the date to current date and time if not provided
    date = data.get('date', datetime.utcnow().isoformat())

    # Create a new product
    new_product = {
        "name": data['name'],
        "price": data['price'],
        "quantity": data['quantity'],
        "type": data['type'],
        "inventory_id": inventory_ID,
        "user_id": user_id,
        "date": date  # Use the provided date or the current date
    }

    try:
        result = products_collection.insert_one(new_product)
        new_product["_id"] = str(result.inserted_id)
        return jsonify(new_product), 201
    except Exception as e:
        logging.error(f"Database error: {e}")
        return jsonify({"msg": "Failed to create product"}), 500
    
@app.route('/', methods=['GET'])
def home():
    return jsonify({"msg": "Welcome to the API!"}), 200


# For getting all product of an inventory
@app.route('/products/<inventory_ID>', methods=['GET'])
def get_products_by_inventory(inventory_ID):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Ensure the inventory item exists and belongs to the user
    if not check_inventory(inventory_ID):
        return jsonify({"msg": "Unauthorized or inventory item not found"}), 403

    # Query for products associated with the specified inventory ID
    products = products_collection.find({"inventory_id": inventory_ID, "user_id": user_id})
    products_list = [
        {
            "id": str(product["_id"]),
            "name": product["name"],
            "price": product["price"],
            "quantity": product["quantity"],
            "type": product["type"],
            "inventory_id": product["inventory_id"]
        }
        for product in products
    ]

    if not products_list:
        return jsonify({"msg": "No products found for this inventory"}), 404

    return jsonify(products_list), 200

# For deleting the product
@app.route('/deleteProduct/<product_id>', methods=['DELETE'])
def delete_product(product_id):
    # Get the user ID from the authorization token
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Find the product and ensure it belongs to the requesting user
    product = products_collection.find_one({"_id": ObjectId(product_id), "user_id": user_id})
    
    if not product:
        return jsonify({"msg": "Product not found or unauthorized"}), 404

    # Delete the product
    result = products_collection.delete_one({"_id": ObjectId(product_id), "user_id": user_id})
    if result.deleted_count == 1:
        return jsonify({"msg": "Product deleted successfully"}), 200
    else:
        return jsonify({"msg": "Failed to delete product"}), 500

@app.route('/products/summary/<inventory_ID>', methods=['GET'])
def get_spending_summary(inventory_ID):
    # Get the user ID from the authorization token
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401
    if not check_inventory(inventory_ID):
        return jsonify({"msg": "Inventory item does not exist or unauthorized."}), 404

    # Retrieve all products for the user that belong to the specified inventory
    products = products_collection.find({"user_id": user_id, "inventory_id": inventory_ID})

    total_buy = 0
    total_sell = 0

    # Calculate total spending on 'buy' and 'sell' type products
    for product in products:
        price = product.get("price", 0)
        quantity = product.get("quantity", 0)
        type_ = product.get("type")

        if type_ == "buy":
            total_buy += price * quantity
        elif type_ == "sell":
            total_sell += price * quantity

    # Calculate total profit (revenue from sells minus cost of buys)
    total_profit = total_sell - total_buy

    return jsonify({
        "total_buy": total_buy,
        "total_sell": total_sell,
        "total_profit": total_profit
    }), 200

@app.route('/products/delete_all/<inventory_ID>', methods=['GET'])
def delete_all_products(inventory_ID):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    inventory_exists = check_inventory(inventory_ID)
    if not inventory_exists:
        return jsonify({"msg": "Inventory not found or unauthorized access"}), 404

    result = products_collection.delete_many({"user_id": user_id, "inventory_id": inventory_ID})
    print(result)
    if result.deleted_count > 0:
        return jsonify({"msg": f"Deleted {result.deleted_count} products from inventory {inventory_ID}"}), 200
    else:
        return jsonify({"msg": "No products found for the specified inventory or unauthorized access"}), 404



if __name__ == '__main__':
    app.run(host="0.0.0.0",debug=True, port=5002)
