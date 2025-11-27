#!/usr/bin/env python3
"""
Database Diagnostic Tool
Use this to find out why the agent can't find fraud cases.
"""

import sqlite3
import os
import sys

def find_database():
    """Find all possible database locations."""
    print("🔍 Searching for fraud_cases.db...")
    print("="*70)
    
    possible_paths = []
    
    # Path 1: shared-data (from agent code)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path1 = os.path.join(os.path.dirname(base_dir), "shared-data", "fraud_cases.db")
    possible_paths.append(("shared-data (parent)", path1))
    
    # Path 2: data directory
    path2 = os.path.join(base_dir, "data", "fraud_cases.db")
    possible_paths.append(("data (local)", path2))
    
    # Path 3: current directory
    path3 = os.path.join(base_dir, "fraud_cases.db")
    possible_paths.append(("current directory", path3))
    
    # Path 4: shared-data in current directory
    path4 = os.path.join(base_dir, "shared-data", "fraud_cases.db")
    possible_paths.append(("shared-data (local)", path4))
    
    found_databases = []
    
    for name, path in possible_paths:
        exists = os.path.exists(path)
        status = "✅ EXISTS" if exists else "❌ NOT FOUND"
        print(f"{status} - {name}")
        print(f"         {path}")
        if exists:
            found_databases.append((name, path))
    
    print("="*70)
    return found_databases

def check_database_contents(db_path):
    """Check what's in the database."""
    print(f"\n📊 Analyzing database: {db_path}")
    print("="*70)
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fraud_cases'")
        if not cur.fetchone():
            print("❌ Table 'fraud_cases' does NOT exist in this database!")
            conn.close()
            return False
        
        print("✅ Table 'fraud_cases' exists")
        
        # Check table structure
        print("\n📋 Table Structure:")
        cur.execute("PRAGMA table_info(fraud_cases)")
        columns = cur.fetchall()
        for col in columns:
            print(f"   - {col['name']} ({col['type']})")
        
        # Count total records
        cur.execute("SELECT COUNT(*) as total FROM fraud_cases")
        total = cur.fetchone()["total"]
        print(f"\n📊 Total records: {total}")
        
        if total == 0:
            print("❌ Database is EMPTY! No fraud cases found.")
            conn.close()
            return False
        
        # Count by status
        cur.execute("SELECT status, COUNT(*) as count FROM fraud_cases GROUP BY status")
        print("\n📊 Records by status:")
        for row in cur.fetchall():
            print(f"   - {row['status']}: {row['count']}")
        
        # List all usernames
        cur.execute("SELECT DISTINCT user_name FROM fraud_cases")
        usernames = [row["user_name"] for row in cur.fetchall()]
        print(f"\n👤 Usernames in database: {', '.join(usernames)}")
        
        # Show pending cases
        cur.execute("""
            SELECT id, user_name, masked_card, transaction_amount, 
                   merchant_name, status, security_answer
            FROM fraud_cases 
            WHERE status = 'pending_review'
        """)
        pending = cur.fetchall()
        
        if pending:
            print(f"\n⏳ Pending cases ({len(pending)}):")
            for case in pending:
                print(f"\n   ID: {case['id']}")
                print(f"   Username: '{case['user_name']}'")
                print(f"   Card: {case['masked_card']}")
                print(f"   Amount: {case['transaction_amount']}")
                print(f"   Merchant: {case['merchant_name']}")
                print(f"   Security Answer: '{case['security_answer']}'")
        else:
            print("\n❌ No pending cases found!")
        
        # Test exact queries the agent uses
        print("\n🧪 Testing Agent Query Logic:")
        print("-"*70)
        test_names = ["John", "Alice", "Bob", "Mike", "Sarah"]
        
        for name in test_names:
            cur.execute("""
                SELECT id, user_name FROM fraud_cases 
                WHERE user_name = ? AND status = 'pending_review'
            """, (name,))
            exact_match = cur.fetchone()
            
            cur.execute("""
                SELECT id, user_name FROM fraud_cases 
                WHERE LOWER(user_name) = LOWER(?) AND status = 'pending_review'
            """, (name,))
            case_insensitive_match = cur.fetchone()
            
            if exact_match:
                print(f"✅ '{name}' - Found with EXACT match (ID: {exact_match['id']})")
            elif case_insensitive_match:
                print(f"⚠️  '{name}' - Found with CASE-INSENSITIVE match (ID: {case_insensitive_match['id']})")
                print(f"     Stored as: '{case_insensitive_match['user_name']}'")
            else:
                print(f"❌ '{name}' - NOT FOUND")
        
        conn.close()
        print("="*70)
        return True
        
    except Exception as e:
        print(f"❌ Error analyzing database: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_agent_database_path():
    """Get the exact path the agent will use."""
    print("\n🤖 Determining Agent's Database Path...")
    print("="*70)
    
    # This mimics the logic in fraud_agent.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(os.path.dirname(base_dir), "shared-data")
    fraud_db_path = os.path.join(data_dir, "fraud_cases.db")
    
    print(f"Agent will look for database at:")
    print(f"   {fraud_db_path}")
    
    exists = os.path.exists(fraud_db_path)
    print(f"\nStatus: {'✅ EXISTS' if exists else '❌ DOES NOT EXIST'}")
    
    if not exists:
        print(f"\n⚠️  WARNING: Agent will not find the database!")
        print(f"   Directory exists: {os.path.exists(data_dir)}")
        if not os.path.exists(data_dir):
            print(f"   Creating directory: {data_dir}")
            os.makedirs(data_dir, exist_ok=True)
            print(f"   ✅ Directory created")
    
    print("="*70)
    return fraud_db_path

def main():
    print("\n" + "="*70)
    print("FRAUD ALERT AGENT - DATABASE DIAGNOSTIC TOOL")
    print("="*70)
    
    # Step 1: Find all databases
    found_databases = find_database()
    
    # Step 2: Determine agent's expected path
    agent_db_path = get_agent_database_path()
    
    # Step 3: Check each found database
    if found_databases:
        print(f"\n✅ Found {len(found_databases)} database(s)")
        for name, path in found_databases:
            check_database_contents(path)
    else:
        print("\n❌ No fraud_cases.db files found!")
    
    # Step 4: Recommendations
    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)
    
    if not os.path.exists(agent_db_path):
        print("\n⚠️  Problem: Agent's expected database does not exist!")
        print("\n✅ Solution: Run one of these commands:")
        print(f"   1. python insert_fraud_cases.py")
        print(f"   2. python fraud_agent.py dev (will auto-create)")
    elif os.path.exists(agent_db_path):
        conn = sqlite3.connect(agent_db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM fraud_cases WHERE status = 'pending_review'")
        count = cur.fetchone()[0]
        conn.close()
        
        if count == 0:
            print("\n⚠️  Problem: Database exists but has no pending cases!")
            print("\n✅ Solution: Run this command:")
            print(f"   python insert_fraud_cases.py")
        else:
            print(f"\n✅ Everything looks good! {count} pending cases found.")
            print("\n🚀 You can now run:")
            print(f"   python fraud_agent.py dev")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    main()