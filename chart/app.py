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


import requests

PRODUCT_MICROSERVICE_URL = os.getenv("PRODUCT_MICROSERVICE_URL")
USER_MICROSERVICE_URL = os.getenv("USER_MICROSERVICE_URL")
INVENTORY_MICROSERVICE_URL = os.getenv("INVENTORY_MICROSERVICE_URL")

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



# A route to send montly buy and sell to the frontend for cart represntation
@app.route('/inventory-products/<inventory_ID>', methods=['GET'])
def get_inventory_products(inventory_ID):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Ensure the inventory item exists and belongs to the user
    if not check_inventory(inventory_ID):
        return jsonify({"msg": "Unauthorized or inventory item not found"}), 403

    # Get the request body
    data = request.get_json()

    # Validate input data for month and year
    if not data or 'month' not in data:
        return jsonify({"msg": "Invalid input data. Required field: 'month'."}), 400

    # Get month and year from body, defaulting year to current year if not provided
    month = data['month']
    year = data.get('year', datetime.utcnow().year)  # Default to current year

    # Validate month and year
    if not (1 <= month <= 12):
        return jsonify({"msg": "Month must be between 1 and 12."}), 400
    if year < 0:
        return jsonify({"msg": "Year must be a positive integer."}), 400

    # Set up headers for the request to the product service
    headers = {"auth-token": request.headers.get("auth-token")}

    # Call the product service to get products for the specified inventory
    try:
        response = requests.get(
            f"{PRODUCT_MICROSERVICE_URL}/products/{inventory_ID}", 
            headers=headers
        )

        # If the product service returns an error status, propagate it
        if response.status_code != 200:
            return jsonify({"msg": response.json().get("msg", "Failed to fetch products")}), response.status_code

        # Return the products retrieved from the product service
        products_data = response.json()

        # Sort products by created_date in descending order
        sorted_products = sorted(products_data, key=lambda x: x['created_date'], reverse=True)

        return jsonify(sorted_products), 200

    except requests.exceptions.RequestException as e:
        return jsonify({"msg": f"Error communicating with product service: {str(e)}"}), 500

@app.route('/inventory-products-yearly/<inventory_ID>', methods=['GET'])
def get_inventory_products_by_year(inventory_ID):
    user_id, username, email, error = get_user_id_from_body()
    if error:
        return jsonify({"msg": error}), 401

    # Ensure the inventory item exists and belongs to the user
    if not check_inventory(inventory_ID):
        return jsonify({"msg": "Unauthorized or inventory item not found"}), 403

    # Get year from request body
    data = request.get_json()

    if not data or 'year' not in data:
        return jsonify({"msg": "Invalid input data. Required field: 'year'."}), 400

    # Validate year
    year = data['year']
    if year < 0:
        return jsonify({"msg": "Year must be a positive integer."}), 400

    headers = {"auth-token": request.headers.get("auth-token")}

    # Dictionary to store monthly data
    monthly_data = {month: [] for month in range(1, 13)}

    # Fetch and group products by month for the specified year
    try:
        for month in range(1, 13):
            response = requests.get(
                f"{PRODUCT_MICROSERVICE_URL}/products/{inventory_ID}?month={month}&year={year}", 
                headers=headers
            )

            if response.status_code == 200:
                products_data = response.json()
                sorted_products = sorted(products_data, key=lambda x: x['created_date'], reverse=True)
                monthly_data[month] = sorted_products
            else:
                monthly_data[month] = []

        return jsonify(monthly_data), 200

    except requests.exceptions.RequestException as e:
        return jsonify({"msg": f"Error communicating with product service: {str(e)}"}), 500




if __name__ == '__main__':
    app.run(debug=True, port=5003)