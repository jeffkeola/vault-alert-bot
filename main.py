import telegram
import os

bot = telegram.Bot(token=os.environ['BOT_TOKEN'])

bot.send_message(chat_id=os.environ['TELEGRAM_CHAT_ID'], text="✅ Vault alert bot is LIVE and sending messages.")

# re-deploying to trigger Python 3.10

import os
import time
import telegram
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = telegram.Bot(token=TELEGRAM_TOKEN)

def send_alert():
    now = datetime.now().strftime('%I:%M %p')
    message = f"🚨 Vault Confluence Alert 🚨\nToken: ETH\nDirection: LONG OPEN\nVaults: Martybit, Opportunity Vault\nEntry Price: $3200\nTotal Value: $116,000\n🕒 Timestamp: {now}"
    bot.send_message(chat_id=CHAT_ID, text=message)

if __name__ == "__main__":
    send_alert()
