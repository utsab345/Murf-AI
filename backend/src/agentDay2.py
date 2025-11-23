import logging
import os
import json
import datetime
from typing import Optional, List
from pathlib import Path

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

# CRITICAL FIX: Find the correct orders directory
def get_orders_directory():
    """Get the orders directory path"""
    # Try multiple possible locations
    possible_paths = [
        Path(__file__).parent.parent / "orders",  # backend/orders
        Path(__file__).parent.parent.parent / "orders",  # project_root/orders
        Path.cwd() / "backend" / "orders",
        Path.cwd() / "orders",
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.info(f"✅ Found orders directory: {path.absolute()}")
            return path
    
    # Create in backend/orders
    orders_dir = Path(__file__).parent.parent / "orders"
    orders_dir.mkdir(exist_ok=True, parents=True)
    logger.info(f"📁 Created orders directory: {orders_dir.absolute()}")
    return orders_dir

ORDERS_DIR = get_orders_directory()

print(f"\n{'='*70}")
print(f"📁 Orders Directory: {ORDERS_DIR.absolute()}")
print(f"{'='*70}\n")


def generate_order_html(order: dict) -> str:
    """Generate beautiful HTML visualization of the order"""
    timestamp = datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>☕ Coffee Order - {order.get('name', 'Guest')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 25px;
            padding: 50px;
            box-shadow: 0 25px 70px rgba(0,0,0,0.3);
            max-width: 550px;
            width: 100%;
            animation: slideIn 0.6s ease-out;
        }}
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(40px) scale(0.95); }}
            to {{ opacity: 1; transform: translateY(0) scale(1); }}
        }}
        h1 {{
            text-align: center;
            color: #333;
            font-size: 2.8em;
            margin-bottom: 15px;
            font-weight: 900;
        }}
        .brand {{
            text-align: center;
            color: #667eea;
            font-size: 1.3em;
            font-weight: 700;
            margin-bottom: 35px;
            text-transform: uppercase;
            letter-spacing: 3px;
        }}
        .customer-name {{
            text-align: center;
            font-size: 2.5em;
            color: #667eea;
            margin-bottom: 40px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        .order-details {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 20px;
            padding: 30px;
            box-shadow: inset 0 3px 12px rgba(0,0,0,0.08);
        }}
        .detail-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 18px 0;
            border-bottom: 2px solid #dee2e6;
        }}
        .detail-row:last-child {{ border-bottom: none; }}
        .detail-label {{
            font-weight: 700;
            color: #495057;
            font-size: 1.15em;
            text-transform: uppercase;
            letter-spacing: 1px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .emoji {{
            font-size: 1.5em;
        }}
        .detail-value {{
            color: #667eea;
            font-weight: 800;
            font-size: 1.4em;
            text-transform: capitalize;
        }}
        .extras-value {{
            color: #ff6b6b;
            font-weight: 700;
            font-size: 1.1em;
        }}
        .timestamp {{
            text-align: center;
            color: #6c757d;
            font-size: 0.95em;
            margin-top: 35px;
            padding-top: 25px;
            border-top: 2px solid #dee2e6;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>☕ Coffee Order</h1>
        <div class="brand">Falcon Brew</div>
        <div class="customer-name">{order.get('name', 'Guest')}</div>
        
        <div class="order-details">
            <div class="detail-row">
                <span class="detail-label"><span class="emoji">☕</span>Drink</span>
                <span class="detail-value">{order.get('drinkType', 'N/A')}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label"><span class="emoji">📏</span>Size</span>
                <span class="detail-value">{order.get('size', 'N/A')}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label"><span class="emoji">🥛</span>Milk</span>
                <span class="detail-value">{order.get('milk', 'N/A')}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label"><span class="emoji">✨</span>Extras</span>
                <span class="extras-value">{', '.join([e.title() for e in order.get('extras', [])]) if order.get('extras') else 'None'}</span>
            </div>
        </div>
        
        <div class="timestamp">Order placed on {timestamp}</div>
    </div>
</body>
</html>"""
    return html


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a friendly coffee shop barista for Falcon Brew.

CRITICAL: You MUST collect ALL 4 required fields for every order:
1. drinkType (latte, cappuccino, espresso, americano, etc.)
2. size (small, medium, large)
3. milk (whole, skim, oat, almond, soy, coconut)
4. name (customer's name)
5. extras (optional - whipped cream, caramel, chocolate, vanilla, honey)

WORKFLOW - FOLLOW EXACTLY:
Step 1: Greet warmly
Step 2: Ask ONE question at a time to collect missing fields
Step 3: After EACH customer response, call update_order() with the new info
Step 4: When ALL 4 fields are filled, say: "Perfect! Let me save that for you" and IMMEDIATELY call save_order()
Step 5: After save_order returns, confirm: "All set! Your order is ready."

RULES:
- Call update_order() every time you learn a new detail
- NEVER skip calling save_order() when order is complete
- Ask for extras BEFORE asking for name
- Keep it conversational and brief
- If customer gives multiple details at once (e.g. "large oat milk latte"), extract all of them and call update_order once with all fields

Example conversation:
Customer: "I want a latte"
You: [call update_order(drinkType="latte")] "Great choice! What size?"
Customer: "Medium"
You: [call update_order(size="medium")] "Perfect. What type of milk?"
Customer: "Oat milk"
You: [call update_order(milk="oat milk")] "Nice! Any extras like whipped cream?"
Customer: "No thanks"
You: [call update_order(extras=[])] "Got it! Name for the order?"
Customer: "Sarah"
You: [call update_order(name="Sarah")] "Perfect! Let me save that for you" [MUST call save_order() NOW] "All set! Your medium latte with oat milk is ready, Sarah!"
""",
        )

    @function_tool()
    async def update_order(
        self,
        context: RunContext,
        drinkType: str = "",
        size: str = "",
        milk: str = "",
        extras: Optional[List[str]] = None,
        name: str = "",
    ) -> str:
        """
        Update the current coffee order.

        Call this whenever the customer provides ANY order details
        (drinkType, size, milk, extras, or name).

        You can call this multiple times as you collect more information.
        Only send the fields that changed.
        """
        # initialize order state if missing
        userdata = context.session.userdata
        order = userdata.get("order")
        if order is None:
            order = {
                "drinkType": "",
                "size": "",
                "milk": "",
                "extras": [],
                "name": "",
            }
            userdata["order"] = order

        if drinkType:
            order["drinkType"] = drinkType
            logger.info(f"✓ Updated drinkType: {drinkType}")
        if size:
            order["size"] = size
            logger.info(f"✓ Updated size: {size}")
        if milk:
            order["milk"] = milk
            logger.info(f"✓ Updated milk: {milk}")
        if extras is not None:
            order["extras"] = extras
            logger.info(f"✓ Updated extras: {extras}")
        if name:
            order["name"] = name
            logger.info(f"✓ Updated name: {name}")

        missing = [
            key
            for key in ("drinkType", "size", "milk", "name")
            if not order.get(key)
        ]

        logger.info(f"📊 Current order: {json.dumps(order, indent=2)}")
        logger.info(f"⚠️ Missing fields: {missing}")
        
        if not missing:
            logger.info("✅ ORDER IS COMPLETE! Agent should call save_order() next.")

        response = {
            "status": "success",
            "order": order,
            "missing_fields": missing,
        }
        
        if not missing:
            response["message"] = "Order is complete! You MUST call save_order() immediately."
        
        return json.dumps(response)

    @function_tool()
    async def reset_order(self, context: RunContext) -> str:
        """
        Clear the current order and start over.

        Use this if the customer wants to change their whole order.
        """
        context.session.userdata["order"] = {
            "drinkType": "",
            "size": "",
            "milk": "",
            "extras": [],
            "name": "",
        }
        logger.info("🔄 Order reset")
        return "Order has been reset. Start a fresh order with the customer."

    @function_tool()
    async def save_order(self, context: RunContext) -> str:
        """
        Save the current completed order to JSON and HTML files.

        Only call this AFTER all fields are filled and you've
        verbally confirmed the order with the customer.
        """
        order = context.session.userdata.get("order")

        if not order:
            return "There is no active order to save."

        missing = [
            key
            for key in ("drinkType", "size", "milk", "name")
            if not order.get(key)
        ]

        if missing:
            return (
                "Order is not complete yet. Missing fields: "
                + ", ".join(missing)
            )

        # Make sure extras is at least an empty list
        if order.get("extras") is None:
            order["extras"] = []

        try:
            # Use UTC timestamp to avoid clashes
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = (order.get("name") or "guest").replace(" ", "_")
            
            print(f"\n{'='*70}")
            print(f"🎯 SAVING ORDER NOW!")
            print(f"{'='*70}")
            print(f"Order: {json.dumps(order, indent=2)}")
            print(f"Target directory: {ORDERS_DIR}")
            
            # Save JSON
            json_filename = ORDERS_DIR / f"order_{timestamp}_{safe_name}.json"
            order_data = {
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "order": order
            }
            
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(order_data, f, indent=2)

            print(f"✅ JSON SAVED: {json_filename}")
            print(f"   Exists: {json_filename.exists()}")
            print(f"   Size: {json_filename.stat().st_size} bytes")
            
            logger.info(f"\n{'='*70}")
            logger.info(f"✅ JSON SAVED: {json_filename}")
            logger.info(f"   File size: {json_filename.stat().st_size} bytes")
            
            # Save HTML
            html_filename = ORDERS_DIR / f"drink_{timestamp}_{safe_name}.html"
            html_content = generate_order_html(order)
            
            with open(html_filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            
            print(f"✅ HTML SAVED: {html_filename}")
            print(f"   Exists: {html_filename.exists()}")
            print(f"   Size: {html_filename.stat().st_size} bytes")
            print(f"{'='*70}\n")
            
            logger.info(f"✅ HTML SAVED: {html_filename}")
            logger.info(f"   File size: {html_filename.stat().st_size} bytes")
            logger.info(f"{'='*70}\n")

            context.session.userdata["last_saved_order_file"] = str(json_filename)

            # Short human-readable summary
            summary = (
                f"✅ Order saved successfully! {order['name']}: "
                f"{order['size']} {order['drinkType']} with {order['milk']} milk"
            )
            if order["extras"]:
                summary += f", extras: {', '.join(order['extras'])}"

            return summary
            
        except Exception as e:
            error_msg = f"❌ Error saving order: {str(e)}"
            print(f"\n{error_msg}")
            print(f"Traceback: {e}")
            logger.error(error_msg, exc_info=True)
            return error_msg


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew", 
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    session.userdata = {}

    # Metrics collection
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"📊 Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))