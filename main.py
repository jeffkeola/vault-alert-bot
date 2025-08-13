import os
import time
import telegram
from datetime import datetime

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Initialize bot
bot = telegram.Bot(token=TELEGRAM_TOKEN)

def send_startup_message():
    """Send a message indicating the bot is live."""
    bot.send_message(chat_id=CHAT_ID, text="✅ Vault alert bot is LIVE and sending messages.")

def send_alert():
    """Send a vault confluence alert message."""
    now = datetime.now().strftime('%I:%M %p')
    message = f"🚨 Vault Confluence Alert 🚨\nToken: ETH\nDirection: LONG OPEN\nVaults: Martybit, Opportunity Vault\nEntry Price: $3200\nTotal Value: $116,000\n🕒 Timestamp: {now}"
    bot.send_message(chat_id=CHAT_ID, text=message)

if __name__ == "__main__":
    # Send startup notification
    send_startup_message()
    
    # Send the alert
    send_alert()
    
    print("Bot execution completed successfully!")
