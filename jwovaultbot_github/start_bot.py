#!/usr/bin/env python3
"""
JWOvaultbot Launcher
Simple script to start the JWOvaultbot with proper error handling
"""

import os
import sys
import logging
from jwovaultbot import main

def check_environment():
    """Check if required environment variables are set"""
    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   • {var}")
        print("\n💡 Set them using:")
        for var in missing_vars:
            print(f"   export {var}='your_value_here'")
        return False
    
    return True

def main_launcher():
    """Main launcher with error handling"""
    print("🤖 JWOvaultbot Launcher")
    print("=" * 30)
    
    # Check environment
    if not check_environment():
        sys.exit(1)
    
    # Check Azure connection (optional)
    azure_conn = os.getenv('AZURE_SQL_CONNECTION')
    if azure_conn:
        print("🟢 Azure SQL connection detected")
    else:
        print("🟡 Using local SQLite database")
    
    print("✅ Environment check passed")
    print("🚀 Starting JWOvaultbot...\n")
    
    try:
        # Start the bot
        main()
    except KeyboardInterrupt:
        print("\n👋 JWOvaultbot shutdown by user")
    except Exception as e:
        print(f"\n❌ JWOvaultbot crashed: {e}")
        logging.exception("Bot crashed with exception")

if __name__ == "__main__":
    main_launcher()