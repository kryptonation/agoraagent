import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "memory.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Store profiles of opposing agents
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_profiles (
        agent_id TEXT PRIMARY KEY,
        notes TEXT,
        last_updated TIMESTAMP
    )
    """)
    
    # Store history of past negotiations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS negotiation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer_id TEXT,
        seller_id TEXT,
        item_name TEXT,
        status TEXT,
        final_price REAL,
        rounds INTEGER,
        timestamp TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()

def get_agent_profile(agent_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT notes FROM agent_profiles WHERE agent_id = ?", (agent_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return f"No prior interaction record found for agent {agent_id}. Treat them as a new connection."

def update_agent_profile(agent_id: str, notes: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO agent_profiles (agent_id, notes, last_updated)
    VALUES (?, ?, ?)
    ON CONFLICT(agent_id) DO UPDATE SET
        notes = excluded.notes,
        last_updated = excluded.last_updated
    """, (agent_id, notes, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_negotiation(buyer_id: str, seller_id: str, item_name: str, status: str, final_price: float, rounds: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO negotiation_history (buyer_id, seller_id, item_name, status, final_price, rounds, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (buyer_id, seller_id, item_name, status, final_price, rounds, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
# Initialize database on import
init_db()
