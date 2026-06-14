"""Direct test without middleware"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Test the auth module directly
from neurova.api.auth import login, init_default_user, authenticate_user

init_default_user()
print(f"User DB: {list(authenticate_user('admin', 'neurova2026'))}")
result = login("admin", "neurova2026")
print(f"Login result: token={result['access_token'][:20]}..." if result else "Login failed")
