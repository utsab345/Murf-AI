import logging
import json
import inspect
import asyncio
import re
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

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
    function_tool,
    RunContext
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("shopping-agent")
logger.setLevel(logging.INFO)
load_dotenv(".env.local")

# ==========================================
# MERCHANT LAYER (Commerce Logic)
# ==========================================

# Define paths for data persistence
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "day9_data")
PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")
ORDERS_PATH = os.path.join(DATA_DIR, "orders.json")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Seed Data for Catalog
SEED_CATALOG = [
    {
        "id": "mug-001",
        "name": "Stoneware Coffee Mug",
        "description": "Hand-crafted stoneware mug, perfect for hot coffee.",
        "price": 800,
        "currency": "INR",
        "category": "mug",
        "attributes": {"color": "white", "material": "stoneware"}
    },
    {
        "id": "mug-002",
        "name": "Matte Black Travel Mug",
        "description": "Insulated travel mug to keep your drinks hot.",
        "price": 1200,
        "currency": "INR",
        "category": "mug",
        "attributes": {"color": "black", "material": "stainless steel"}
    },
    {
        "id": "hoodie-001",
        "name": "Classic Cotton Hoodie",
        "description": "Soft, comfortable cotton hoodie for everyday wear.",
        "price": 2500,
        "currency": "INR",
        "category": "apparel",
        "attributes": {"color": "black", "size": ["S", "M", "L", "XL"]}
    },
    {
        "id": "hoodie-002",
        "name": "Vintage Logo Hoodie",
        "description": "Retro style hoodie with vintage logo print.",
        "price": 3200,
        "currency": "INR",
        "category": "apparel",
        "attributes": {"color": "grey", "size": ["M", "L"]}
    },
    {
        "id": "tshirt-001",
        "name": "Basic White Tee",
        "description": "Essential white t-shirt, 100% organic cotton.",
        "price": 900,
        "currency": "INR",
        "category": "apparel",
        "attributes": {"color": "white", "size": ["S", "M", "L"]}
    },
     {
        "id": "tshirt-002",
        "name": "Graphic Print Tee",
        "description": "Cool graphic tee for a casual look.",
        "price": 1100,
        "currency": "INR",
        "category": "apparel",
        "attributes": {"color": "blue", "size": ["M", "L", "XL"]}
    }
]

class Merchant:
    def __init__(self):
        self._ensure_data()

    def _ensure_data(self):
        """Ensure catalog and orders files exist."""
        if not os.path.exists(PRODUCTS_PATH):
            with open(PRODUCTS_PATH, "w", encoding="utf-8") as f:
                json.dump(SEED_CATALOG, f, indent=2)
        
        if not os.path.exists(ORDERS_PATH):
            with open(ORDERS_PATH, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def _load_products(self) -> List[Dict[str, Any]]:
        with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_orders(self) -> List[Dict[str, Any]]:
        with open(ORDERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_orders(self, orders: List[Dict[str, Any]]):
        with open(ORDERS_PATH, "w", encoding="utf-8") as f:
            json.dump(orders, f, indent=2)

    def list_products(self, query: str = None, category: str = None, max_price: float = None) -> List[Dict[str, Any]]:
        """
        List products with optional filtering.
        """
        products = self._load_products()
        results = []

        for p in products:
            # Filter by Category
            if category and p.get("category", "").lower() != category.lower():
                continue
            
            # Filter by Price
            if max_price is not None and p.get("price", 0) > max_price:
                continue

            # Filter by Query (Name or Description)
            if query:
                q = query.lower()
                if q not in p.get("name", "").lower() and q not in p.get("description", "").lower():
                    continue
            
            results.append(p)
        
        return results

    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        products = self._load_products()
        for p in products:
            if p["id"] == product_id:
                return p
        return None

    def create_order(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create an order from a list of items.
        items: [{"product_id": "...", "quantity": 1}, ...]
        """
        products = self._load_products()
        orders = self._load_orders()
        
        order_items = []
        total_amount = 0
        currency = "INR" # Defaulting for simplicity

        for item in items:
            pid = item.get("product_id")
            qty = item.get("quantity", 1)
            
            # Find product details
            product = next((p for p in products if p["id"] == pid), None)
            if not product:
                continue # Skip invalid products
            
            line_total = product["price"] * qty
            total_amount += line_total
            currency = product["currency"]

            order_items.append({
                "product_id": pid,
                "name": product["name"],
                "quantity": qty,
                "unit_price": product["price"],
                "total": line_total,
                "currency": currency
            })

        if not order_items:
            raise ValueError("No valid items in order")

        order = {
            "id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "items": order_items,
            "total_amount": total_amount,
            "currency": currency,
            "status": "created"
        }

        orders.append(order)
        self._save_orders(orders)
        return order

    def get_last_order(self) -> Optional[Dict[str, Any]]:
        orders = self._load_orders()
        if not orders:
            return None
        # Assuming append-only, last is latest
        return orders[-1]

# Singleton instance for the agent to use
merchant = Merchant()

# ==========================================
# AGENT LAYER (Voice & Tools)
# ==========================================

# ---------- Robust TTS helpers (Same as Day 8) ---------- #

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

# ---------- Shopping Agent ---------- #

class ShoppingAgent(Agent):
    """Voice-driven shopping assistant using ACP-lite merchant layer."""
    
    def __init__(self, *, tts=None, **kwargs):
        base_instructions = """
You are a helpful Voice Shopping Assistant for a boutique store.
Your goal is to help users browse products and place orders using the available tools.

CAPABILITIES:
1. List products: You can search for products by name, category, or price.
2. Place orders: You can create orders for specific items.
3. Check history: You can tell the user about their last order.

BEHAVIOR GUIDELINES:
- Be concise and friendly. Voice responses should be short (1-2 sentences).
- When listing products, mention the name and price. Don't list IDs unless asked.
- Before placing an order, confirm the item and price with the user.
- If the user asks for something vague (e.g., "clothes"), ask for more specifics or offer to list categories.
- Use the tools provided to fetch real data. Do not make up products.

EXAMPLE FLOW:
User: "Do you have any mugs?"
You: (Call list_products tool) "Yes, we have a Stoneware Coffee Mug for 800 INR and a Matte Black Travel Mug for 1200 INR."
User: "I'll take the stoneware one."
You: (Call place_order tool) "Great choice. That's one Stoneware Coffee Mug for 800 INR. Order placed! Your Order ID is ORD-1234."
"""
        super().__init__(instructions=base_instructions, tts=tts, **kwargs)
        logger.info("ShoppingAgent initialized")

    @function_tool()
    async def list_products(self, context: RunContext, query: str = None, category: str = None, max_price: float = None) -> str:
        """
        Search for products in the catalog.
        Args:
            query: Search term for name or description (e.g., "hoodie", "black").
            category: Filter by category (e.g., "mug", "apparel").
            max_price: Filter by maximum price.
        """
        logger.info(f"Tool call: list_products(query={query}, category={category}, max_price={max_price})")
        products = merchant.list_products(query=query, category=category, max_price=max_price)
        
        if not products:
            return "No products found matching those criteria."
        
        # Format for the LLM to read easily
        result = []
        for p in products:
            result.append(f"{p['name']} ({p['category']}): {p['price']} {p['currency']} - ID: {p['id']}")
        
        return "\n".join(result)

    @function_tool()
    async def place_order(self, context: RunContext, product_id: str, quantity: int = 1) -> str:
        """
        Place an order for a specific product.
        Args:
            product_id: The ID of the product to buy (e.g., "mug-001").
            quantity: Number of items to buy.
        """
        logger.info(f"Tool call: place_order(product_id={product_id}, quantity={quantity})")
        
        # Verify product exists first
        product = merchant.get_product(product_id)
        if not product:
            return f"Error: Product with ID {product_id} not found."

        try:
            items = [{"product_id": product_id, "quantity": quantity}]
            order = merchant.create_order(items)
            return f"Order placed successfully! Order ID: {order['id']}. Total: {order['total_amount']} {order['currency']}."
        except Exception as e:
            logger.error(f"Order creation failed: {e}")
            return "Sorry, I couldn't place that order due to a system error."

    @function_tool()
    async def get_last_order(self, context: RunContext) -> str:
        """
        Retrieve details of the most recent order placed.
        """
        logger.info("Tool call: get_last_order")
        order = merchant.get_last_order()
        if not order:
            return "You haven't placed any orders yet."
        
        items_str = ", ".join([f"{i['quantity']}x {i['name']}" for i in order['items']])
        return f"Your last order ({order['id']}) was for {items_str}. Total: {order['total_amount']} {order['currency']}."

    async def on_enter(self) -> None:
        """Called when agent enters the room."""
        logger.info("Agent entered room")
        greeting = "Hello! I'm your shopping assistant. I can help you find mugs, hoodies, and t-shirts. What are you looking for today?"
        await speak_text(self.session, self.session.tts, greeting)

# ---------- Entrypoint ---------- #

def prewarm(proc: JobProcess):
    """Prewarm function to load VAD model."""
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("VAD model prewarmed")

async def entrypoint(ctx: JobContext):
    """Main entrypoint for the agent."""
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info(f"Starting Shopping Agent in room: {ctx.room.name}")

    # Initialize Murf TTS
    tts = murf.TTS(
        voice="en-US-matthew",
        style="Conversation",
        tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
        text_pacing=True
    )
    logger.info("Murf TTS initialized")

    # Create agent session
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
        agent=ShoppingAgent(tts=tts),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    
    logger.info("Agent session started, connecting to room...")
    await ctx.connect()
    logger.info("Connected!")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
