#!/usr/bin/env python3
"""
🎯 Simple runner for Clean CoinGlass Whale Bot v3.0
Loads environment variables and starts the bot
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import and run the bot
from coinglass_bot import main
import asyncio

if __name__ == "__main__":
    print("🚀 Starting Clean CoinGlass Whale Bot v3.0...")
    print("📋 Make sure you have set these environment variables:")
    print("   - TELEGRAM_BOT_TOKEN")
    print("   - TELEGRAM_CHAT_ID")
    print("   - COINGLASS_API_KEY")
    print()
    
    asyncio.run(main())