import asyncio
import os
from datetime import datetime
from telegram import Bot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_alert():
    bot = Bot(token=TELEGRAM_TOKEN)
    
    # Send initial message that bot is live
    await bot.send_message(chat_id=CHAT_ID, text="✅ Vault alert bot is LIVE and sending messages.")
    
    # Send the crypto vault alert
    now = datetime.now().strftime('%I:%M %p')
    message = f"🚨 Vault Confluence Alert 🚨\nToken: ETH\nDirection: LONG OPEN\nVaults: Martybit, Opportunity Vault\nEntry Price: $3200\nTotal Value: $116,000\n🕒 Timestamp: {now}"
    await bot.send_message(chat_id=CHAT_ID, text=message)

if __name__ == "__main__":
    asyncio.run(send_alert())
