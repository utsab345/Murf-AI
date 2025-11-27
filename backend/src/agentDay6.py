# fraud_agent.py
import logging
import os
import json
import datetime
import sqlite3
import inspect
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
    function_tool,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("fraud_agent")
logger.setLevel(logging.INFO)
load_dotenv(".env.local")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "shared-data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- Fraud DB config ---------- #
FRAUD_DB_PATH = os.path.join(DATA_DIR, "fraud_cases.db")
BANK_NAME = "SecureBank"

# ---------- TTS Configuration ---------- #
def make_murf_tts():
    """Create a fresh Murf TTS instance."""
    return murf.TTS(
        voice="en-US-matthew",
        style="Conversation",
        tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
        text_pacing=True,
    )

# ---------- Simple fraud-case SQLite DB utilities ---------- #
def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(FRAUD_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_fraud_db():
    """Initialize the fraud cases database."""
    conn = _connect_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fraud_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT NOT NULL,
        security_identifier TEXT,
        masked_card TEXT,
        transaction_amount TEXT,
        merchant_name TEXT,
        location TEXT,
        timestamp TEXT,
        transaction_category TEXT,
        transaction_source TEXT,
        security_question TEXT,
        security_answer TEXT,
        status TEXT DEFAULT 'pending_review',
        outcome_note TEXT,
        raw_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()
    logger.info("Fraud database initialized at %s", FRAUD_DB_PATH)

def seed_sample_fraud_cases():
    """Seed the database with sample fraud cases."""
    conn = _connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) as c FROM fraud_cases")
    if cur.fetchone()["c"] > 0:
        conn.close()
        logger.info("Database already contains fraud cases, skipping seed")
        return
    
    samples = [
        {
            "user_name": "John",
            "security_identifier": "12345",
            "masked_card": "**** 4242",
            "transaction_amount": "$129.99",
            "merchant_name": "ABC Industry",
            "location": "Shanghai, China",
            "timestamp": "2025-11-27 14:32:00 UTC",
            "transaction_category": "e-commerce",
            "transaction_source": "alibaba.com",
            "security_question": "What is the name of your first pet?",
            "security_answer": "fluffy",
            "status": "pending_review",
        },
        {
            "user_name": "Alice",
            "security_identifier": "67890",
            "masked_card": "**** 9876",
            "transaction_amount": "$599.00",
            "merchant_name": "TechGadgets Pro",
            "location": "Mumbai, India",
            "timestamp": "2025-11-27 09:15:00 UTC",
            "transaction_category": "electronics",
            "transaction_source": "techgadgets.com",
            "security_question": "In which city were you born?",
            "security_answer": "pune",
            "status": "pending_review",
        },
        {
            "user_name": "Bob",
            "security_identifier": "11223",
            "masked_card": "**** 1111",
            "transaction_amount": "$1,250.00",
            "merchant_name": "Luxury Fashion Store",
            "location": "Paris, France",
            "timestamp": "2025-11-26 20:02:00 UTC",
            "transaction_category": "fashion",
            "transaction_source": "luxuryfashion.fr",
            "security_question": "What was your high school mascot?",
            "security_answer": "tigers",
            "status": "pending_review",
        },
        {
            "user_name": "Sarah",
            "security_identifier": "44556",
            "masked_card": "**** 7788",
            "transaction_amount": "$45.99",
            "merchant_name": "Global Streaming Service",
            "location": "Lagos, Nigeria",
            "timestamp": "2025-11-27 03:45:00 UTC",
            "transaction_category": "subscription",
            "transaction_source": "streamingservice.ng",
            "security_question": "What is your mother's maiden name?",
            "security_answer": "johnson",
            "status": "pending_review",
        },
        {
            "user_name": "Mike",
            "security_identifier": "99887",
            "masked_card": "**** 5555",
            "transaction_amount": "$2,499.99",
            "merchant_name": "Electronics Warehouse",
            "location": "Seoul, South Korea",
            "timestamp": "2025-11-27 11:20:00 UTC",
            "transaction_category": "electronics",
            "transaction_source": "electronicswarehouse.kr",
            "security_question": "What was the name of your first school?",
            "security_answer": "lincoln",
            "status": "pending_review",
        }
    ]
    
    for s in samples:
        cur.execute("""
            INSERT INTO fraud_cases
            (user_name, security_identifier, masked_card, transaction_amount, merchant_name,
             location, timestamp, transaction_category, transaction_source, security_question, 
             security_answer, status, outcome_note, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["user_name"], s["security_identifier"], s["masked_card"], s["transaction_amount"],
            s["merchant_name"], s["location"], s["timestamp"], s.get("transaction_category", ""),
            s.get("transaction_source", ""), s["security_question"], s["security_answer"], 
            s["status"], "", json.dumps(s)
        ))
    
    conn.commit()
    conn.close()
    logger.info("Seeded %d sample fraud cases", len(samples))

def load_case_for_username(username: str) -> Optional[Dict[str, Any]]:
    """Load a pending fraud case for the given username."""
    conn = _connect_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM fraud_cases
        WHERE LOWER(user_name) = LOWER(?) AND status = 'pending_review'
        ORDER BY id ASC
        LIMIT 1
    """, (username.strip(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)

def update_fraud_case(case_id: int, status: str, outcome_note: str):
    """Update a fraud case status and outcome note."""
    conn = _connect_db()
    cur = conn.cursor()
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    update_data = {
        "last_updated": timestamp,
        "note": outcome_note,
        "status": status
    }
    cur.execute("""
        UPDATE fraud_cases
        SET status = ?, outcome_note = ?, raw_json = ?, updated_at = ?
        WHERE id = ?
    """, (status, outcome_note, json.dumps(update_data), timestamp, case_id))
    conn.commit()
    conn.close()
    logger.info("Updated fraud case %d: status=%s", case_id, status)

# Initialize DB at import time (safe: idempotent)
try:
    init_fraud_db()
    seed_sample_fraud_cases()
except Exception as e:
    logger.exception("Failed initializing fraud DB: %s", e)

# ---------- Fraud Agent ---------- #

class FraudAgent(Agent):
    """
    Fraud alert voice agent for SecureBank.
    
    Tools exposed:
      - fetch_case(username) -> returns fraud case JSON or a message if none
      - verify_security(case_id, answer) -> returns True/False (and message)
      - confirm_decision(case_id, decision) -> updates DB and returns summary message
    
    Notes:
      - Uses only fake data seeded in shared-data/fraud_cases.db
      - NEVER asks for or stores sensitive data like full card numbers, PINs, passwords, or OTPs.
    """

    def __init__(self, *, tts=None, **kwargs):
        base_instructions = f"""You are a calm, professional fraud department representative for {BANK_NAME}.

Your conversation flow:
1. GREETING: Greet the caller warmly and explain you're calling from {BANK_NAME}'s Fraud Department about a suspicious transaction.

2. USERNAME: Ask for the caller's first name to look up their case.

3. FETCH CASE: Once you have the username, call fetch_case(username) tool.
   - If no case found: Apologize politely and end the call.
   - If case found: Continue to verification.

4. SECURITY VERIFICATION: Ask the security question from the fraud case.
   Wait for the answer, then call verify_security(case_id, answer) tool.
   - If verification fails: Apologize, explain you cannot proceed, and end the call.
   - If verification succeeds: Continue to transaction details.

5. TRANSACTION DETAILS: Read the suspicious transaction clearly:
   "We detected a transaction on your card ending in [masked_card] for [amount] at [merchant] 
   in [location] on [timestamp]. The category was [category] from [source]."

6. CONFIRMATION: Ask clearly: "Did you authorize this transaction? Please answer yes or no."

7. DECISION: Based on their answer, call confirm_decision(case_id, decision) tool:
   - If YES (confirmed_safe): "Thank you for confirming. We've marked this as legitimate. No further action needed."
   - If NO (confirmed_fraud): "Thank you for letting us know. We've marked this as fraudulent. Your card has been blocked 
     and we'll issue a replacement. A dispute has been opened and you'll see the credit in 5-7 business days."

8. CLOSING: Thank them and end the call politely.

IMPORTANT RULES:
- Keep responses short and natural (2-3 sentences max per turn)
- Never ask for full card numbers, PINs, passwords, or OTPs
- Stay calm and reassuring throughout
- Wait for user responses before proceeding
- All data is fake/demo-only"""

        super().__init__(instructions=base_instructions, tts=tts, **kwargs)

    # --------------------------- Tools --------------------------- #

    @function_tool()
    async def fetch_case(self, context: RunContext, username: str) -> str:
        """
        Fetch the pending fraud case for the given username.
        Returns JSON string with case details or error message.
        """
        logger.info("Fetching fraud case for username: %s", username)
        case = load_case_for_username(username.strip())
        
        if not case:
            return json.dumps({
                "found": False, 
                "message": f"No pending suspicious transactions found for {username}."
            })
        
        # Return sanitized case data
        sanitized = {
            "found": True,
            "id": case["id"],
            "user_name": case["user_name"],
            "security_identifier": case["security_identifier"],
            "masked_card": case["masked_card"],
            "transaction_amount": case["transaction_amount"],
            "merchant_name": case["merchant_name"],
            "location": case["location"],
            "timestamp": case["timestamp"],
            "transaction_category": case.get("transaction_category", ""),
            "transaction_source": case.get("transaction_source", ""),
            "security_question": case["security_question"],
            "status": case["status"],
        }
        
        logger.info("Found case %d for user %s", case["id"], username)
        return json.dumps(sanitized)

    @function_tool()
    async def verify_security(self, context: RunContext, case_id: int, answer: str) -> str:
        """
        Verify the security question answer for the given case_id.
        Returns a JSON string with verification result and message.
        """
        logger.info("Verifying security answer for case %d", case_id)
        
        conn = _connect_db()
        cur = conn.cursor()
        cur.execute("SELECT security_answer FROM fraud_cases WHERE id = ?", (case_id,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return json.dumps({
                "ok": False, 
                "message": "Case not found in our system."
            })
        
        expected = (row["security_answer"] or "").strip().lower()
        provided = answer.strip().lower()
        
        if expected == provided:
            logger.info("Security verification PASSED for case %d", case_id)
            return json.dumps({
                "ok": True, 
                "message": "Verification successful."
            })
        else:
            logger.warning("Security verification FAILED for case %d", case_id)
            update_fraud_case(
                case_id, 
                "verification_failed", 
                "Security question answered incorrectly during voice verification."
            )
            return json.dumps({
                "ok": False, 
                "message": "Verification failed. Cannot proceed."
            })

    @function_tool()
    async def confirm_decision(self, context: RunContext, case_id: int, decision: str) -> str:
        """
        Mark the fraud case based on user's confirmation.
        decision: 'yes' or 'no' (case insensitive)
        Returns JSON string with updated status and next steps.
        """
        logger.info("Recording fraud decision for case %d: %s", case_id, decision)
        
        dec = (decision or "").strip().lower()
        
        if dec in ("yes", "y", "yeah", "yep", "correct", "true"):
            update_fraud_case(
                case_id, 
                "confirmed_safe", 
                "Customer confirmed the transaction as legitimate via voice call."
            )
            return json.dumps({
                "status": "confirmed_safe", 
                "message": "Transaction marked as legitimate. No further action required."
            })
        
        elif dec in ("no", "n", "nope", "negative", "false", "not me"):
            update_fraud_case(
                case_id, 
                "confirmed_fraud", 
                "Customer denied the transaction. Card blocked and dispute initiated."
            )
            return json.dumps({
                "status": "confirmed_fraud", 
                "message": "Transaction marked as fraudulent. Card blocked and dispute opened."
            })
        
        else:
            update_fraud_case(
                case_id, 
                "verification_failed", 
                "Unclear response during confirmation step."
            )
            return json.dumps({
                "status": "verification_failed", 
                "message": "Unable to confirm your response. Please contact us directly."
            })

    # --------------------------- Entry dialog --------------------------- #

    async def on_enter(self) -> None:
        """Entry point when agent starts - initiate the fraud alert conversation."""
        logger.info("Fraud Alert Agent session started")
        
        await self.session.generate_reply(
            instructions=(
                f"Begin the fraud alert call. Greet the caller professionally and explain that "
                f"you're from {BANK_NAME}'s Fraud Department calling about a suspicious transaction. "
                f"Ask for their first name to look up the case. Keep your greeting brief and natural."
            )
        )

# ---------- Entrypoint and session setup ---------- #

def prewarm(proc: JobProcess):
    """Prewarm function to load VAD model before sessions start."""
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("VAD model preloaded")

async def entrypoint(ctx: JobContext):
    """Main entrypoint for the fraud alert agent."""
    import asyncio
    ctx.log_context_fields = {"room": ctx.room.name}

    # Create TTS instance inside event loop
    tts = make_murf_tts()
    logger.info("Created TTS instance")

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    logger.info("AgentSession created successfully")

    session.userdata = {}
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info("Session usage summary: %s", summary)

    ctx.add_shutdown_callback(log_usage)

    # Ensure TTS closed on shutdown
    async def _close_tts():
        try:
            close_coro = getattr(tts, "close", None)
            if close_coro:
                if inspect.iscoroutinefunction(close_coro):
                    await close_coro()
                else:
                    close_coro()
                logger.info("TTS instance closed cleanly")
        except Exception as e:
            logger.exception("Error closing Murf TTS: %s", e)

    ctx.add_shutdown_callback(_close_tts)

    # Start the fraud agent (pass the same tts instance)
    await session.start(
        agent=FraudAgent(tts=tts),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    
    await ctx.connect()
    logger.info("Fraud Alert Agent connected and ready")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm
    ))