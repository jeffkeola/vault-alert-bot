import asyncio
import os
from telegram import Bot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def get_chat_id():
    bot = Bot(token=TELEGRAM_TOKEN)
    
    try:
        # Get updates (recent messages)
        updates = await bot.get_updates()
        
        if updates:
            print("Recent messages to your bot:")
            for update in updates:
                if update.message:
                    chat_id = update.message.chat_id
                    username = update.message.from_user.username or "No username"
                    text = update.message.text or "No text"
                    print(f"Chat ID: {chat_id}")
                    print(f"From: @{username}")
                    print(f"Message: {text}")
                    print("-" * 40)
        else:
            print("No recent messages found.")
            print("Please:")
            print("1. Find your bot on Telegram")
            print("2. Send it any message (like 'hello')")
            print("3. Run this script again")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_chat_id())