"""
Test script to verify order saving works
Run this with: python test_save.py
"""
import json
from datetime import datetime
from pathlib import Path

# Set up orders directory
ORDERS_DIR = Path(__file__).parent.parent / "orders"
print(f"Orders directory: {ORDERS_DIR.absolute()}")

# Create directory
ORDERS_DIR.mkdir(exist_ok=True, parents=True)
print(f"✅ Directory exists: {ORDERS_DIR.exists()}")

# Create test order
test_order = {
    "drinkType": "latte",
    "size": "medium",
    "milk": "oat milk",
    "extras": ["whipped cream"],
    "name": "TestUser"
}

# Save JSON
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
json_file = ORDERS_DIR / f"order_{timestamp}.json"

order_data = {
    "timestamp": datetime.now().isoformat(),
    "order": test_order
}

with open(json_file, "w") as f:
    json.dump(order_data, f, indent=2)

print(f"✅ Test order saved to: {json_file}")
print(f"✅ File exists: {json_file.exists()}")
print(f"✅ File size: {json_file.stat().st_size} bytes")

# List all orders
order_files = list(ORDERS_DIR.glob("order_*.json"))
print(f"\n📊 Total orders in folder: {len(order_files)}")
for f in order_files:
    print(f"  - {f.name}")

print("\n✅ TEST COMPLETED SUCCESSFULLY!")
print(f"\nNow check this folder in Windows Explorer:")
print(f"{ORDERS_DIR.absolute()}")