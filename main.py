#!/usr/bin/env python3
"""
Hyperliquid Advanced Position Monitor - Main Entry Point
Launches the advanced Telegram bot with position size tracking and confluence detection.
"""

import asyncio
import sys
import os
from bot import main

if __name__ == "__main__":
    print("🚀 Starting Advanced Hyperliquid Position Monitor...")
    print("Features: Position SIZE tracking, Confluence detection, Anti-spam protection")
    
    # Check environment variables
    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        print("❌ ERROR: TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)
    
    if not os.getenv('TELEGRAM_CHAT_ID'):
        print("❌ ERROR: TELEGRAM_CHAT_ID environment variable not set")
        sys.exit(1)
    
    try:
        # Run the advanced bot
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot error: {e}")
        sys.exit(1)
