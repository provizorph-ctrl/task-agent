import os
import threading
from app import app
from bot import run_bot
from database import init_db

def start_bot():
    try:
        run_bot()
    except Exception as e:
        print(f"Bot error: {e}")

if __name__ == "__main__":
    init_db()

    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    print("Telegram bot started!")

    port = int(os.environ.get("PORT", 5000))
    print(f"Web server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
