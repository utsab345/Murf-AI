import logging
import json
from datetime import datetime
from pathlib import Path
import re

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

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# Create orders directory
ORDERS_DIR = Path(__file__).parent.parent / "orders"

print(f"\n{'='*70}")
print(f"📁 Orders Directory: {ORDERS_DIR.absolute()}")
print(f"{'='*70}\n")

try:
    ORDERS_DIR.mkdir(exist_ok=True, parents=True)
    logger.info(f"✅ Orders directory ready: {ORDERS_DIR.absolute()}")
    print(f"✅ Orders directory ready: {ORDERS_DIR.absolute()}\n")
    
    # TEST: Create a test file immediately to verify write permissions
    test_file = ORDERS_DIR / "test_write.txt"
    with open(test_file, "w") as f:
        f.write("Test write successful")
    print(f"✅ Write test successful: {test_file}")
    test_file.unlink()  # Delete test file
    
except Exception as e:
    logger.error(f"❌ Failed to create orders directory: {e}")
    print(f"❌ Failed to create orders directory: {e}\n")


def generate_drink_html(order: dict) -> str:
    """Generate HTML representation of the coffee drink"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Coffee Order</title>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
        }}
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 10px;
        }}
        .customer-name {{
            text-align: center;
            font-size: 28px;
            color: #667eea;
            margin-bottom: 30px;
            font-weight: bold;
        }}
        .order-details {{
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-top: 30px;
        }}
        .detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        .detail-label {{
            font-weight: 600;
            color: #555;
        }}
        .detail-value {{
            color: #667eea;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>☕ Your Coffee Order</h1>
        <div class="customer-name">{order.get('name', 'Guest')}</div>
        
        <div class="order-details">
            <div class="detail-row">
                <span class="detail-label">Drink:</span>
                <span class="detail-value">{order.get('drinkType', 'N/A').title()}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Size:</span>
                <span class="detail-value">{order.get('size', 'N/A').title()}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Milk:</span>
                <span class="detail-value">{order.get('milk', 'N/A').title()}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Extras:</span>
                <span class="detail-value">{', '.join([e.title() for e in order.get('extras', [])]) if order.get('extras') else 'None'}</span>
            </div>
        </div>
    </div>
</body>
</html>"""
    return html


class OrderState:
    """Simple order state tracker"""
    def __init__(self):
        self.drink_type = None
        self.size = None
        self.milk = None
        self.extras = []
        self.name = None
        self.saved = False
    
    def is_complete(self):
        """Check if all required fields are filled"""
        complete = all([self.drink_type, self.size, self.milk, self.name])
        if complete:
            print(f"✅ Order is COMPLETE: {self.to_dict()}")
        return complete
    
    def to_dict(self):
        return {
            "drinkType": self.drink_type,
            "size": self.size,
            "milk": self.milk,
            "extras": self.extras,
            "name": self.name
        }
    
    def save_order(self):
        """Save order to files"""
        if self.saved:
            print("⚠️ Order already saved, skipping...")
            return
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            
            # Save JSON
            json_filename = ORDERS_DIR / f"order_{timestamp}.json"
            order_data = {
                "timestamp": datetime.now().isoformat(),
                "order": self.to_dict()
            }
            
            with open(json_filename, "w") as f:
                json.dump(order_data, f, indent=2)
            
            print(f"\n{'='*70}")
            print(f"✅ JSON SAVED: {json_filename}")
            print(f"{'='*70}")
            
            # Save HTML
            html_filename = ORDERS_DIR / f"drink_{timestamp}.html"
            html_content = generate_drink_html(self.to_dict())
            
            with open(html_filename, "w") as f:
                f.write(html_content)
            
            print(f"✅ HTML SAVED: {html_filename}")
            print(f"{'='*70}\n")
            
            self.saved = True
            logger.info(f"✅ Order saved: {json_filename}")
            
            # Verify files exist
            if json_filename.exists() and html_filename.exists():
                print(f"✅ VERIFIED: Both files exist!")
                print(f"   JSON size: {json_filename.stat().st_size} bytes")
                print(f"   HTML size: {html_filename.stat().st_size} bytes")
            else:
                print(f"❌ WARNING: Files not found after save!")
                
        except Exception as e:
            print(f"❌ ERROR SAVING ORDER: {e}")
            logger.error(f"Error saving order: {e}", exc_info=True)


class CoffeeBarista(Agent):
    """Coffee shop barista agent - SIMPLE VERSION"""
    
    def __init__(self):
        super().__init__(
            instructions="""You are a friendly barista taking coffee orders.

Ask these questions ONE AT A TIME:
1. "What drink would you like?" (latte, cappuccino, espresso, americano, macchiato, flat white, cortado)
2. "What size?" (small, medium, large)
3. "What type of milk?" (whole milk, skim milk, oat milk, almond milk, soy milk, coconut milk)
4. "Would you like any extras?" (whipped cream, caramel drizzle, chocolate powder, vanilla shot, honey, or none)
5. "What's your name for the order?"

After getting ALL 5 pieces of information, say: "Perfect! Your order for [NAME] is ready: [SIZE] [DRINK] with [MILK] and [EXTRAS]. Thank you!"

Keep it simple and friendly!""",
        )
        self.order = OrderState()
        self.last_user_message = ""
        self.last_agent_message = ""

    def extract_from_text(self, text: str):
        """Extract order info from text"""
        text_lower = text.lower()
        
        # Extract drink
        drinks = ["espresso", "latte", "cappuccino", "americano", "macchiato", "flat white", "cortado"]
        for drink in drinks:
            if drink in text_lower and not self.order.drink_type:
                self.order.drink_type = drink
                print(f"✓ DRINK: {drink}")

        # Extract size
        if not self.order.size:
            if "small" in text_lower:
                self.order.size = "small"
                print(f"✓ SIZE: small")
            elif "medium" in text_lower:
                self.order.size = "medium"
                print(f"✓ SIZE: medium")
            elif "large" in text_lower:
                self.order.size = "large"
                print(f"✓ SIZE: large")

        # Extract milk
        milks = ["whole milk", "skim milk", "oat milk", "almond milk", "soy milk", "coconut milk"]
        for milk in milks:
            if milk in text_lower and not self.order.milk:
                self.order.milk = milk
                print(f"✓ MILK: {milk}")

        # Extract extras
        extras_list = ["whipped cream", "caramel drizzle", "chocolate powder", "vanilla shot", "honey"]
        for extra in extras_list:
            if extra in text_lower and extra not in self.order.extras:
                self.order.extras.append(extra)
                print(f"✓ EXTRA: {extra}")

        # No extras
        if ("no extra" in text_lower or "no thank" in text_lower or "none" in text_lower) and not self.order.extras:
            self.order.extras = []
            print("✓ NO EXTRAS")

        # Extract name
        if not self.order.name:
            # Look for capitalized words
            words = text.split()
            for word in reversed(words):
                clean = word.strip('.,!?;:')
                if clean and len(clean) > 1 and clean[0].isupper():
                    if clean not in ['I', 'My', 'The', 'A', 'Yes', 'No', 'Ok', 'Please', 'Thank', 'Thanks', 'Hello', 'Hi']:
                        self.order.name = clean
                        print(f"✓ NAME: {clean}")
                        break

    async def on_message_received(self, message) -> None:
        """Process user messages"""
        try:
            text = getattr(message, 'text', str(message))
            if text:
                print(f"\n📝 USER: {text}")
                self.last_user_message = text
                self.extract_from_text(text)
                
                # Try to save after each user message if complete
                if self.order.is_complete() and not self.order.saved:
                    print("🎯 Order complete after user message - SAVING!")
                    self.order.save_order()
                    
        except Exception as e:
            logger.error(f"Error in on_message_received: {e}", exc_info=True)

    async def on_message_sent(self, message) -> None:
        """Process agent messages"""
        try:
            text = getattr(message, 'text', str(message))
            if text:
                print(f"🤖 AGENT: {text[:200]}...")
                self.last_agent_message = text
                self.extract_from_text(text)
                
                # Check if agent is confirming/thanking
                confirm_words = ["perfect", "ready", "complete", "thank you", "all set", "saved"]
                is_confirming = any(word in text.lower() for word in confirm_words)
                
                if is_confirming and self.order.is_complete() and not self.order.saved:
                    print("🎯 Order complete in agent confirmation - SAVING!")
                    self.order.save_order()
                    
        except Exception as e:
            logger.error(f"Error in on_message_sent: {e}", exc_info=True)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("✓ VAD model loaded")


async def entrypoint(ctx: JobContext):
    print(f"\n{'='*70}")
    print("🚀 Coffee Barista Agent Starting...")
    print(f"📁 Orders will be saved to: {ORDERS_DIR.absolute()}")
    print(f"{'='*70}\n")
    
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

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    ctx.add_shutdown_callback(lambda: logger.info(f"📊 Usage: {usage_collector.get_summary()}"))

    barista = CoffeeBarista()
    
    await session.start(agent=barista, room=ctx.room, room_input_options=RoomInputOptions(
        noise_cancellation=noise_cancellation.BVC(),
    ))

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))