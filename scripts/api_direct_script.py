"""Direct test via ASGI (no TestClient, direct httpx)"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from httpx import AsyncClient, ASGITransport
from neurova.api.app import create_app, _add_health_routes

async def main():
    app = create_app(enable_memory=False, enable_channels=False)
    _add_health_routes(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test 1: Health
        r = await client.get("/health")
        print(f"1. Health: {r.status_code} - {r.json()}")

        # Test 2: Login
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "neurova2026"})
        j = r.json()
        print(f"2. Login: {r.status_code} - success={j['success']}, code={j['code']}")
        if j['success']:
            token = j["data"]["access_token"]
            print(f"   Token: {token[:20]}...")
            headers = {"Authorization": f"Bearer {token}"}

            # Test 3: Auth me
            r = await client.get("/api/v1/auth/me", headers=headers)
            print(f"3. Auth me: {r.status_code} - {r.json()['success']}")

            # Test 4: Wrong password
            r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
            j = r.json()
            print(f"4. Wrong password: {r.status_code} - code={j['code']}")

            # Test 5: Agents list
            r = await client.get("/api/v1/agents", headers=headers)
            print(f"5. Agents list: {r.status_code} - {r.json()['success']}")

            # Test 6: Skills list
            r = await client.get("/api/v1/skills", headers=headers)
            print(f"6. Skills list: {r.status_code} - {r.json()['success']}")

            # Test 7: Channels capabilities
            r = await client.get("/api/v1/channels/capabilities", headers=headers)
            caps = r.json()
            print(f"7. Channels: {r.status_code} - {len(caps['data']['capabilities'])} capabilities")

            # Test 8: Stats
            r = await client.get("/api/stats")
            print(f"8. Stats: {r.status_code} - {r.json()['status']}")

            # Test 9: Unauthorized
            r = await client.get("/api/v1/agents")
            print(f"9. No token: {r.status_code} - code={r.json()['code']}")

            print("\nAll tests passed!")
        else:
            print(f"Login failed: {j['message']}")

asyncio.run(main())
