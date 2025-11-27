#!/usr/bin/env python3
"""
Database Viewer and Management Utility for Fraud Alert Agent
Run this script to view, reset, or manage fraud cases in the database.
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any

# Database path - matches your agent configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "shared-data")
FRAUD_DB_PATH = os.path.join(DATA_DIR, "fraud_cases.db")


def connect_db():
    """Connect to the fraud cases database."""
    if not os.path.exists(FRAUD_DB_PATH):
        print(f"❌ Database not found at {FRAUD_DB_PATH}")
        print("   Run 'python fraud_agent.py dev' first to create the database.")
        return None
    
    conn = sqlite3.connect(FRAUD_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_column_names(conn):
    """Get the actual column names from the database."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(fraud_cases)")
    columns = [row[1] for row in cur.fetchall()]
    return columns


def view_all_cases():
    """Display all fraud cases in a formatted table."""
    conn = connect_db()
    if not conn:
        return
    
    # Get column names to handle both 'timestamp' and 'transaction_time'
    columns = get_column_names(conn)
    time_column = 'transaction_time' if 'transaction_time' in columns else 'timestamp'
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM fraud_cases ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print("📭 No fraud cases found in database.")
        return
    
    print("\n" + "="*150)
    print("🔍 ALL FRAUD CASES")
    print("="*150)
    
    for row in rows:
        print(f"\n{'─'*150}")
        print(f"ID: {row['id']}")
        print(f"Username: {row['user_name']}")
        print(f"Security ID: {row['security_identifier']}")
        print(f"Card: {row['masked_card']}")
        print(f"Amount: {row['transaction_amount']}")
        print(f"Merchant: {row['merchant_name']}")
        print(f"Location: {row['location']}")
        print(f"Time: {row[time_column]}")
        
        # Handle optional columns
        if 'transaction_category' in columns and row['transaction_category']:
            print(f"Category: {row['transaction_category']}")
        if 'transaction_source' in columns and row['transaction_source']:
            print(f"Source: {row['transaction_source']}")
        
        print(f"Security Question: {row['security_question']}")
        print(f"Status: {row['status']} {'✅' if row['status'] == 'confirmed_safe' else '❌' if row['status'] == 'confirmed_fraud' else '⏳'}")
        
        if row['outcome_note']:
            print(f"Outcome: {row['outcome_note']}")
        
        if 'created_at' in columns:
            print(f"Created: {row['created_at']}")
        if 'updated_at' in columns:
            print(f"Updated: {row['updated_at']}")
    
    print("="*150 + "\n")


def view_pending_cases():
    """Display only pending fraud cases."""
    conn = connect_db()
    if not conn:
        return
    
    # Get column names
    columns = get_column_names(conn)
    time_column = 'transaction_time' if 'transaction_time' in columns else 'timestamp'
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM fraud_cases WHERE status = 'pending_review' ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print("\n✅ No pending fraud cases! All cases have been reviewed.\n")
        return
    
    print("\n" + "="*100)
    print("⏳ PENDING FRAUD CASES")
    print("="*100)
    
    for row in rows:
        print(f"\nID: {row['id']} | User: {row['user_name']} | Card: {row['masked_card']}")
        print(f"Amount: {row['transaction_amount']} | Merchant: {row['merchant_name']}")
        print(f"Location: {row['location']} | Time: {row[time_column]}")
        print(f"Security Q: {row['security_question']}")
        print(f"Answer: {row['security_answer']}")
    
    print("="*100 + "\n")


def view_resolved_cases():
    """Display resolved fraud cases (safe or fraudulent)."""
    conn = connect_db()
    if not conn:
        return
    
    # Get column names
    columns = get_column_names(conn)
    time_column = 'transaction_time' if 'transaction_time' in columns else 'timestamp'
    
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM fraud_cases 
        WHERE status IN ('confirmed_safe', 'confirmed_fraud', 'verification_failed')
        ORDER BY updated_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print("\n📭 No resolved cases yet.\n")
        return
    
    print("\n" + "="*100)
    print("✅ RESOLVED FRAUD CASES")
    print("="*100)
    
    for row in rows:
        status_icon = "✅" if row['status'] == 'confirmed_safe' else "❌" if row['status'] == 'confirmed_fraud' else "⚠️"
        print(f"\n{status_icon} ID: {row['id']} | User: {row['user_name']} | Status: {row['status']}")
        print(f"   Amount: {row['transaction_amount']} | Merchant: {row['merchant_name']}")
        print(f"   Outcome: {row['outcome_note']}")
        if 'updated_at' in columns:
            print(f"   Resolved: {row['updated_at']}")
    
    print("="*100 + "\n")


def reset_database():
    """Reset all cases to pending_review status."""
    conn = connect_db()
    if not conn:
        return
    
    response = input("\n⚠️  This will reset ALL cases to 'pending_review'. Continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("❌ Reset cancelled.")
        return
    
    columns = get_column_names(conn)
    
    cur = conn.cursor()
    
    if 'updated_at' in columns:
        cur.execute("""
            UPDATE fraud_cases 
            SET status = 'pending_review', 
                outcome_note = '',
                updated_at = ?
        """, (datetime.utcnow().isoformat() + "Z",))
    else:
        cur.execute("""
            UPDATE fraud_cases 
            SET status = 'pending_review', 
                outcome_note = ''
        """)
    
    affected = cur.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ Reset {affected} cases to pending_review status.\n")


def view_statistics():
    """Display statistics about fraud cases."""
    conn = connect_db()
    if not conn:
        return
    
    cur = conn.cursor()
    
    # Total cases
    cur.execute("SELECT COUNT(*) as total FROM fraud_cases")
    total = cur.fetchone()['total']
    
    # By status
    cur.execute("""
        SELECT status, COUNT(*) as count 
        FROM fraud_cases 
        GROUP BY status
    """)
    status_counts = {row['status']: row['count'] for row in cur.fetchall()}
    
    # Total amounts
    cur.execute("""
        SELECT SUM(CAST(REPLACE(REPLACE(transaction_amount, '$', ''), ',', '') AS REAL)) as total_amount
        FROM fraud_cases
    """)
    total_amount = cur.fetchone()['total_amount'] or 0
    
    # Fraudulent amounts
    cur.execute("""
        SELECT SUM(CAST(REPLACE(REPLACE(transaction_amount, '$', ''), ',', '') AS REAL)) as fraud_amount
        FROM fraud_cases
        WHERE status = 'confirmed_fraud'
    """)
    fraud_amount = cur.fetchone()['fraud_amount'] or 0
    
    conn.close()
    
    print("\n" + "="*60)
    print("📊 FRAUD CASES STATISTICS")
    print("="*60)
    print(f"\nTotal Cases: {total}")
    print(f"\nStatus Breakdown:")
    print(f"  ⏳ Pending Review: {status_counts.get('pending_review', 0)}")
    print(f"  ✅ Confirmed Safe: {status_counts.get('confirmed_safe', 0)}")
    print(f"  ❌ Confirmed Fraud: {status_counts.get('confirmed_fraud', 0)}")
    print(f"  ⚠️  Verification Failed: {status_counts.get('verification_failed', 0)}")
    print(f"\nFinancial Impact:")
    print(f"  Total Transaction Value: ${total_amount:,.2f}")
    print(f"  Fraudulent Transaction Value: ${fraud_amount:,.2f}")
    if total_amount > 0:
        fraud_percentage = (fraud_amount / total_amount) * 100
        print(f"  Fraud Rate: {fraud_percentage:.1f}%")
    print("="*60 + "\n")


def export_to_json():
    """Export all fraud cases to a JSON file."""
    conn = connect_db()
    if not conn:
        return
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM fraud_cases ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    
    cases = [dict(row) for row in rows]
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fraud_cases_export_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(cases, f, indent=2)
    
    print(f"\n✅ Exported {len(cases)} cases to {filename}\n")


def main_menu():
    """Display and handle the main menu."""
    while True:
        print("\n" + "="*60)
        print("🏦 FRAUD ALERT AGENT - DATABASE VIEWER")
        print("="*60)
        print("\n1. View All Cases")
        print("2. View Pending Cases")
        print("3. View Resolved Cases")
        print("4. View Statistics")
        print("5. Reset All Cases to Pending")
        print("6. Export to JSON")
        print("7. Exit")
        print("\n" + "─"*60)
        
        choice = input("\nEnter your choice (1-7): ").strip()
        
        if choice == '1':
            view_all_cases()
        elif choice == '2':
            view_pending_cases()
        elif choice == '3':
            view_resolved_cases()
        elif choice == '4':
            view_statistics()
        elif choice == '5':
            reset_database()
        elif choice == '6':
            export_to_json()
        elif choice == '7':
            print("\n👋 Goodbye!\n")
            break
        else:
            print("\n❌ Invalid choice. Please enter a number between 1-7.")
        
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    print("\n🚀 Starting Database Viewer...")
    
    if not os.path.exists(FRAUD_DB_PATH):
        print(f"\n❌ Database not found at {FRAUD_DB_PATH}")
        print("\n💡 To create the database, run:")
        print("   python quick_fix.py")
        print("   OR")
        print("   python fraud_agent.py dev")
        print("\nThen run this script again.\n")
    else:
        main_menu()