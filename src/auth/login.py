from flask import request, jsonify
import bcrypt
import jwt
from datetime import datetime, timedelta

def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    # Mock user lookup
    user = {"id": 1, "email": email, "password_hash": bcrypt.hashpw(b"password123", bcrypt.gensalt())}

    if bcrypt.checkpw(password.encode(), user["password_hash"]):
        token = jwt.encode({
            'user_id': user["id"],
            'exp': datetime.utcnow() + timedelta(hours=1)
        }, "secret", algorithm="HS256")
        return jsonify({"access_token": token})
    else:
        return jsonify({"error": "Invalid credentials"}), 401
