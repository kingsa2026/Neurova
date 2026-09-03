"""Test JWT directly"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jose import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = "test-secret"
ALGORITHM = "HS256"

payload = {
    "sub": "admin",
    "type": "access",
    "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
    "iat": datetime.now(timezone.utc),
}

print("Encoding JWT...")
token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
print(f"Token: {token[:30]}...")

print("Decoding JWT...")
decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
print(f"Decoded: {decoded}")
print("JWT works correctly!")
