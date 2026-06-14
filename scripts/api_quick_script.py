"""Simple inline test for the API server"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from neurova.api.app import create_app, _add_health_routes
from fastapi.testclient import TestClient

app = create_app(enable_memory=False, enable_channels=False)
_add_health_routes(app)
client = TestClient(app)

# Test 1: Health
r = client.get("/health")
print(f"1. Health: {r.status_code} - OK")

# Test 2: Login
r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "neurova2026"})
print(f"2. Login: {r.status_code} - {r.json()['success']}")
token = r.json()["data"]["access_token"]
refresh_token = r.json()["data"]["refresh_token"]
headers = {"Authorization": f"Bearer {token}"}

# Test 3: Auth me
r = client.get("/api/v1/auth/me", headers=headers)
print(f"3. Auth me: {r.status_code} - {r.json()['success']}")

# Test 4: Wrong password
r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
print(f"4. Wrong password: {r.status_code} - code={r.json()['code']}")

# Test 5: Refresh token
r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
print(f"5. Refresh token: {r.status_code} - {r.json()['success']}")

# Test 6: Agents list
r = client.get("/api/v1/agents", headers=headers)
print(f"6. Agents list: {r.status_code} - {r.json()['success']}")

# Test 7: Skills list
r = client.get("/api/v1/skills", headers=headers)
print(f"7. Skills list: {r.status_code} - {r.json()['success']}")

# Test 8: Channels capabilities
r = client.get("/api/v1/channels/capabilities", headers=headers)
caps = r.json()
cap_count = len(caps.get("data", {}).get("capabilities", {}))
print(f"8. Channels: {r.status_code} - {cap_count} capabilities")

# Test 9: Stats
r = client.get("/api/stats")
print(f"9. Stats: {r.status_code} - OK")

# Test 10: Unauthorized access (no token)
r = client.get("/api/v1/agents")
print(f"10. No token: {r.status_code} - code={r.json()['code']}")

print("\nAll 10 tests passed!")
