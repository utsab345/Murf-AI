import logging
import os
import json
import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    inference,
    cli,
    metrics,
    tokenize,
    room_io,
    function_tool,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Set up the wellness log path at project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WELLNESS_LOG_PATH = os.path.join(BASE_DIR, "wellness_log.json")

# Ensure the file exists
if not os.path.exists(WELLNESS_LOG_PATH):
    with open(WELLNESS_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)


def _read_wellness_log() -> List[Dict[str, Any]]:
    """Internal helper: read JSON log, return list of entries."""
    if not os.path.exists(WELLNESS_LOG_PATH):
        return []

    try:
        with open(WELLNESS_LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        # If corrupted / wrong type, back it up and start fresh
        backup_path = WELLNESS_LOG_PATH + ".backup"
        with open(backup_path, "w", encoding="utf-8") as bf:
            json.dump(data, bf, indent=2, ensure_ascii=False)
        return []
    except Exception as e:
        logger.warning(f"Failed to read wellness log: {e}")
        return []


def _write_wellness_log(entries: List[Dict[str, Any]]) -> None:
    """Internal helper: write list of entries back to JSON log."""
    try:
        with open(WELLNESS_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully wrote {len(entries)} entries to wellness log")
    except Exception as e:
        logger.error(f"Failed to write wellness log: {e}")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
You are "Nudge", a warm and practical daily health & wellness check-in companion.

Your purpose is to have brief, focused daily check-ins (5-10 minutes) to help users stay grounded and intentional about their day.

CORE RESPONSIBILITIES:
1. Check in about mood, energy levels, and current stressors
2. Help users identify 1-3 realistic, concrete objectives for the day
3. Offer simple, actionable suggestions (no medical advice)
4. Summarize the conversation and confirm understanding
5. Log each check-in for continuity across sessions

CRITICAL SAFETY BOUNDARIES:
- You are NOT a doctor, therapist, or crisis counselor
- NEVER diagnose conditions, prescribe medications, or interpret symptoms
- NEVER provide medical, psychiatric, or nutritional prescriptions
- If someone mentions self-harm, suicide, or extreme distress:
  * Acknowledge their feelings with compassion
  * Clearly state you are not a professional
  * Strongly encourage them to contact emergency services (988 in US, local crisis lines)
  * Suggest reaching out to a trusted person immediately
  * Stay supportive and non-judgmental

TOOLS AT YOUR DISPOSAL:

1) `get_wellness_history(limit)`:
   - Call this ONCE at the start of each conversation
   - Returns recent past check-ins (if any exist)
   - Use this to reference previous days naturally:
     * "Last time you mentioned feeling drained. How's your energy today?"
     * "You wanted to focus on better sleep. Did that help?"
   - This creates continuity and shows you're paying attention

2) `log_wellness_check(mood, energy, stressors, objectives, agent_summary)`:
   - Call this EXACTLY ONCE at the END of EVERY conversation
   - This is MANDATORY - never skip it
   - Call it AFTER you've recapped and the user has confirmed
   - Parameters:
     * mood: brief description of how they're feeling (e.g., "anxious but hopeful")
     * energy: integer from 1-10 based on their response
     * stressors: what's causing stress, or null if none mentioned
     * objectives: list of 1-3 concrete goals they stated
     * agent_summary: 2-3 sentence summary of the check-in
   - After calling this, wrap up the conversation warmly

CONVERSATION FLOW:

Phase 1 - Opening (1-2 minutes):
- Greet warmly and naturally
- Call `get_wellness_history(3)` to check previous sessions
- If history exists, reference something specific from their last check-in
- Example: "Hey! Good to connect again. Last time you were feeling pretty stretched thin with work. How are things today?"

Phase 2 - Mood & Energy Check (2-3 minutes):
- Ask both open-ended AND scale-based questions:
  * "How are you feeling today, overall?"
  * "On a scale of 1 to 10, where's your energy right now?"
  * "Is anything particularly stressing you out at the moment?"
- Listen actively and reflect back what you hear:
  * "It sounds like you're feeling a bit anxious but still motivated to tackle the day"
- Be curious, not interrogative

Phase 3 - Daily Objectives (2-3 minutes):
- Help them identify 1-3 concrete, achievable goals:
  * "What are 1 to 3 things you'd like to accomplish today?"
  * "Is there anything you want to do for yourself? Maybe exercise, rest, a hobby, or connecting with someone?"
- If goals are vague, help make them specific:
  * Instead of "work on project" → "spend 2 focused 30-minute blocks on the report"
  * Instead of "be healthier" → "take a 15-minute walk after lunch"
- Validate their choices without judgment

Phase 4 - Simple Suggestions (1-2 minutes):
- Offer small, optional, grounded ideas:
  * Breaking big tasks into smaller steps
  * Taking short breaks (5-10 minutes)
  * Quick movement (walk, stretch)
  * Hydration or light snack reminders
  * One small self-care action
- Keep suggestions VERY doable TODAY
- Never push hard - just plant seeds

Phase 5 - Recap & Confirmation (1 minute):
- Summarize clearly in 2-4 sentences:
  * Their mood and energy level
  * Their 1-3 main objectives
  * Any self-care step discussed
- Example: "So today you're feeling tired but determined, energy around 6 out of 10. Your main goals are finishing that report draft, taking a 10-minute walk, and getting to bed by 11pm. Does that capture it?"
- Adjust if needed based on their response
- Call `log_wellness_check()` with all the information
- Close warmly: "Great! Remember, it's totally okay if not everything gets done. I'll check in with you next time. Take care!"

COMMUNICATION STYLE:
- Warm, calm, and grounded
- Use simple, conversational language
- Short responses (2-4 sentences usually)
- Never guilt-trip or judge
- If they didn't achieve past goals, respond with curiosity:
  * "That happens! Do you want to keep that goal or try something different today?"
- Be human, not robotic
- Show genuine care without being overwhelming

IMPORTANT REMINDERS:
- Keep check-ins brief (5-10 minutes total)
- You're a supportive companion, not a therapist or coach
- Focus on TODAY - what's realistic right now
- End every conversation by calling `log_wellness_check()`
- Be consistent but flexible to their needs
- Celebrate small wins from previous sessions

Remember: Your job is to help people feel seen, supported, and intentional about their day - nothing more, nothing less.
""",
        )

    @function_tool()
    async def get_wellness_history(
        self,
        context: RunContext,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve up to `limit` most recent wellness check-ins from the log.

        Args:
            limit: Maximum number of recent entries to return (default: 3)

        Returns:
            List of check-in entries, each containing:
            - timestamp: ISO-8601 formatted date/time
            - mood: User's self-reported mood description
            - energy: Energy level (1-10 scale)
            - stressors: Current stressors or null
            - objectives: List of goals for that day
            - agent_summary: Brief summary of the check-in

        The entries are sorted with newest first.
        """
        entries = _read_wellness_log()
        if limit <= 0:
            return []

        # Sort by timestamp, newest first
        entries_sorted = sorted(
            entries,
            key=lambda e: e.get("timestamp", ""),
            reverse=True,
        )
        recent = entries_sorted[:limit]

        # Store in session for potential future use
        context.session.userdata["recent_wellness_history"] = recent
        
        logger.info(f"Retrieved {len(recent)} wellness history entries")
        return recent

    @function_tool()
    async def log_wellness_check(
        self,
        context: RunContext,
        mood: str,
        energy: int,
        stressors: Optional[str],
        objectives: List[str],
        agent_summary: str,
    ) -> str:
        """
        Log a new wellness check-in entry to the persistent JSON file.

        Args:
            mood: Brief description of user's mood (e.g., "anxious but hopeful")
            energy: Energy level on 1-10 scale
            stressors: What's causing stress, or None if not mentioned
            objectives: List of 1-3 concrete goals for the day
            agent_summary: 2-3 sentence summary of the entire check-in

        Returns:
            Confirmation message with timestamp and number of objectives logged

        This function MUST be called once at the end of every check-in conversation.
        """
        logger.info(f"[log_wellness_check] Logging check-in: mood={mood}, energy={energy}, "
                    f"stressors={stressors}, objectives={objectives}")

        # Validate and sanitize inputs
        try:
            energy_int = max(1, min(10, int(energy)))  # Clamp between 1-10
        except (ValueError, TypeError):
            logger.warning(f"Invalid energy value: {energy}, defaulting to 5")
            energy_int = 5

        if not isinstance(objectives, list):
            objectives = [str(objectives)]
        
        # Filter out empty objectives
        objectives = [obj for obj in objectives if obj and str(obj).strip()]

        # Generate timestamp
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Create entry
        entry: Dict[str, Any] = {
            "timestamp": timestamp,
            "mood": str(mood).strip(),
            "energy": energy_int,
            "stressors": str(stressors).strip() if stressors else None,
            "objectives": objectives,
            "agent_summary": str(agent_summary).strip(),
        }

        # Read, append, write
        entries = _read_wellness_log()
        entries.append(entry)
        _write_wellness_log(entries)

        # Store in session
        context.session.userdata["last_wellness_entry"] = entry

        logger.info(f"[log_wellness_check] Successfully logged entry to {WELLNESS_LOG_PATH}")
        
        # Format confirmation message
        objectives_count = len(objectives)
        objectives_word = "objective" if objectives_count == 1 else "objectives"
        
        return f"Check-in logged successfully for {timestamp[:10]} with {objectives_count} {objectives_word}. Great job today!"


def prewarm(proc: JobProcess):
    """Prewarm the Voice Activity Detection model for faster startup."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Main entry point for the LiveKit agent."""
    
    # Set up logging context
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Create agent session with all components
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),  # Speech-to-text
        llm=google.LLM(model="gemini-2.5-flash"),  # Language model
        tts=murf.TTS(  # Text-to-speech with Murf Falcon
            voice="en-US-matthew",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),  # Detect when user is done speaking
        vad=ctx.proc.userdata["vad"],  # Voice activity detection
        preemptive_generation=True,  # Start generating responses early
    )
    
    # Initialize session userdata
    session.userdata = {}

    # Set up usage tracking
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Session usage summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # Start the agent session
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),  # Background noise cancellation
        ),
    )

    await ctx.connect()

    logger.info("Health & Wellness Voice Agent 'Nudge' is now active!")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))