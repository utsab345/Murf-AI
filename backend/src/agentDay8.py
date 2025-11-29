# Voice Game Master Agent (Day 8) - FINAL VERSION
# Primary Goal: D&D-style voice Game Master running a story in Eldoria

import logging
import os
import inspect
import asyncio
import re
import json
from typing import List, Dict, Any
from datetime import datetime

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("game-master")
logger.setLevel(logging.INFO)
load_dotenv(".env.local")

# ---------- Robust TTS helpers ---------- #

_MAX_TTS_CHARS = 700

async def _split_into_chunks(text: str, max_chars: int = _MAX_TTS_CHARS) -> List[str]:
    """Split text into manageable chunks for TTS."""
    text = (text or "").strip()
    if not text:
        return []
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: List[str] = []
    current = ""
    
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(current) + len(s) + 1 <= max_chars:
            current = (current + " " + s).strip() if current else s
        else:
            if current:
                chunks.append(current)
            if len(s) <= max_chars:
                current = s
            else:
                words = s.split()
                piece = ""
                for w in words:
                    if len(piece) + len(w) + 1 <= max_chars:
                        piece = (piece + " " + w).strip() if piece else w
                    else:
                        if piece:
                            chunks.append(piece)
                        piece = w
                if piece:
                    current = piece
                else:
                    current = ""
    if current:
        chunks.append(current)
    return chunks

async def speak_text(session: AgentSession, tts, text: str, retries: int = 2):
    """Speak text with chunking and retry logic."""
    if not text or not text.strip():
        return

    chunks = await _split_into_chunks(text, _MAX_TTS_CHARS)
    if not chunks:
        return

    for chunk in chunks:
        success = False
        for attempt in range(retries + 1):
            try:
                if hasattr(tts, "stream_text"):
                    async for _frame in tts.stream_text(chunk):
                        pass
                    success = True
                    break
                if hasattr(tts, "synthesize"):
                    synth = tts.synthesize(chunk)
                    if inspect.isawaitable(synth):
                        await synth
                    else:
                        for _ in synth:
                            pass
                    success = True
                    break
                if hasattr(tts, "generate_audio"):
                    gen = tts.generate_audio(chunk)
                    if inspect.isawaitable(gen):
                        await gen
                    else:
                        for _ in gen:
                            pass
                    success = True
                    break
                raise RuntimeError("No known streaming method on TTS plugin")
            except Exception as e:
                logger.warning(f"TTS attempt {attempt + 1} failed: {repr(e)}")
                await asyncio.sleep(0.6 * (attempt + 1))
        
        if not success:
            # Fallback to silero if available
            try:
                if 'silero' in globals() and hasattr(silero, 'TTS'):
                    sil = silero.TTS()
                    if hasattr(sil, 'stream_text'):
                        async for _ in sil.stream_text(chunk):
                            pass
                    else:
                        maybe = sil.synthesize(chunk)
                        if inspect.isawaitable(maybe):
                            await maybe
                        else:
                            for _ in maybe:
                                pass
                    success = True
            except Exception as e2:
                logger.exception(f"Fallback Silero TTS failed: {e2}")

# ---------- Game Master Agent ---------- #

class GameMasterAgent(Agent):
    """D&D-style Game Master that runs an interactive adventure."""
    
    def __init__(self, *, tts=None, **kwargs):
        # Enhanced system prompt with clear voice-optimized instructions
        base_instructions = """
You are an immersive Dungeon Master (GM) running a fantasy adventure in the world of Eldoria.

THE WORLD OF ELDORIA:
- A land of ancient magic, mysterious ruins, and dangerous creatures
- The kingdom is at peace, but dark forces stir in the wilderness
- Magic is rare but powerful; most folk are simple traders, farmers, or adventurers

YOUR ROLE AS GAME MASTER:
1. Describe scenes vividly but CONCISELY (2-3 sentences maximum per response)
2. Use dramatic, atmospheric language - paint a picture with words
3. React logically to player actions - reward creativity, add consequences for recklessness
4. Track continuity - remember names, locations, and past events
5. ALWAYS end with a clear question prompting the player's next action

CRITICAL VOICE RULES:
- Keep responses SHORT (under 50 words when possible)
- Speak naturally as if you're at a table with friends
- Use pauses for dramatic effect (via punctuation)
- End EVERY turn with a direct question: "What do you do?" or "How do you respond?"
- Never write stage directions like *opens door* - just describe what happens

STORY STRUCTURE:
- Start with a hook (mysterious stranger at tavern)
- Build tension gradually
- Introduce NPCs with distinct personalities
- Create small wins and setbacks
- Drive toward a clear goal or revelation

THE CURRENT SCENARIO:
The player has just woken up in "The Rusty Tankard" tavern. A hooded figure beckons them from across the room. This stranger will offer a quest if approached.

Begin the adventure now. Set the scene and ask what the player does.
"""
        super().__init__(instructions=base_instructions, tts=tts, **kwargs)
        
        # Simple game state tracking
        self.game_state = {
            "session_start": datetime.now().isoformat(),
            "turn_count": 0,
            "current_location": "The Rusty Tankard Tavern",
            "met_npcs": [],
            "key_events": [],
            "player_name": None,
            "inventory": []
        }
        
        logger.info("GameMasterAgent initialized with Eldoria setting")

    async def on_enter(self) -> None:
        """Called when agent enters the room - start the adventure."""
        logger.info("=== NEW ADVENTURE STARTING IN ELDORIA ===")
        logger.info(f"Initial game state: {json.dumps(self.game_state, indent=2)}")
        
        opening_scene = (
            "Welcome, traveler, to Eldoria. "
            "You wake in the Rusty Tankard tavern, the scent of roasted meat and ale in the air. "
            "Across the dimly lit room, a hooded figure raises one hand, beckoning you closer. "
            "What do you do?"
        )
        
        self.game_state["turn_count"] += 1
        self.game_state["key_events"].append("Woke up in The Rusty Tankard")
        
        await speak_text(self.session, self.session.tts, opening_scene)
        logger.info(f"Turn {self.game_state['turn_count']}: Opening scene delivered")

    def update_game_state(self, event: str, location: str = None, npc: str = None):
        """Update game state tracking."""
        self.game_state["turn_count"] += 1
        self.game_state["key_events"].append(event)
        
        if location:
            self.game_state["current_location"] = location
        if npc and npc not in self.game_state["met_npcs"]:
            self.game_state["met_npcs"].append(npc)
        
        logger.info(f"Turn {self.game_state['turn_count']}: {event}")
        logger.info(f"Current location: {self.game_state['current_location']}")
        if self.game_state["met_npcs"]:
            logger.info(f"NPCs met: {', '.join(self.game_state['met_npcs'])}")

# ---------- Entrypoint ---------- #

def prewarm(proc: JobProcess):
    """Prewarm function to load VAD model."""
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("VAD model prewarmed")

async def entrypoint(ctx: JobContext):
    """Main entrypoint for the agent."""
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info(f"Starting Game Master agent in room: {ctx.room.name}")

    # Initialize Murf TTS with storyteller-friendly settings
    tts = murf.TTS(
        voice="en-US-matthew",  # Clear, dramatic voice
        style="Conversation",
        tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
        text_pacing=True
    )
    logger.info("Murf TTS initialized with en-US-matthew voice")

    # Create agent session with all components
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Usage tracking
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"=== SESSION COMPLETE ===")
        logger.info(f"Usage Summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    async def _close_tts():
        try:
            close_coro = getattr(tts, "close", None)
            if close_coro:
                if inspect.iscoroutinefunction(close_coro):
                    await close_coro()
                else:
                    close_coro()
            logger.info("TTS closed successfully")
        except Exception as e:
            logger.exception(f"Error closing Murf TTS: {e}")

    ctx.add_shutdown_callback(_close_tts)

    # Start the agent session
    await session.start(
        agent=GameMasterAgent(tts=tts),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    
    logger.info("Agent session started, connecting to room...")
    await ctx.connect()
    logger.info("Connected! Adventure begins...")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))