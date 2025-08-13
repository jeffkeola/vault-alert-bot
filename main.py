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
    
    # Send the crypto vault alert with individual vault details
    now = datetime.now().strftime('%I:%M %p')
    message = f"""🚨 Vault Confluence Alert 🚨
📊 Token: ETH
📈 Direction: LONG OPEN

🏦 VAULT BREAKDOWN:
━━━━━━━━━━━━━━━━━━━━
🔸 Martybit Vault
   Entry Price: $3,180
   Total Value: $68,000

🔹 Opportunity Vault  
   Entry Price: $3,220
   Total Value: $48,000

━━━━━━━━━━━━━━━━━━━━
💰 Combined Total: $116,000
🕒 Timestamp: {now}"""
    
    await bot.send_message(chat_id=CHAT_ID, text=message)

if __name__ == "__main__":
    asyncio.run(send_alert())
