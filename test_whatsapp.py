"""
Quick script to:
1. Update Emmanuel Okon's parent phone to your real number
2. Send a test WhatsApp reminder
"""
import time
import requests

BASE = "http://localhost:8001"

# Wait for server to be ready
for i in range(5):
    try:
        r = requests.get(f"{BASE}/health")
        if r.status_code == 200:
            break
    except requests.ConnectionError:
        time.sleep(1)

# Step 1: Update Emmanuel Okon's (student_id=1) parent phone to your number
print("=" * 50)
print("Step 1: Updating Emmanuel Okon's parent phone")
print("=" * 50)

r = requests.patch(f"{BASE}/api/v1/students/1", json={
    "parent_phone": "+2348147327980",
})
print(f"Status: {r.status_code}")
data = r.json()
print(f"Student: {data['student_name']}")
print(f"Parent: {data['parent_name']}")
print(f"Phone: {data['parent_phone']}")
print()

# Step 2: Send a reminder for school_id=1
# Emmanuel has a partial payment (paid 50k, balance 25k)
print("=" * 50)
print("Step 2: Sending WhatsApp reminder")
print("=" * 50)

r = requests.post(f"{BASE}/api/v1/reminders/send", json={
    "school_id": 1,
})
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")
