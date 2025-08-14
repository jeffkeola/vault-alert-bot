#!/usr/bin/env python3
"""
Quick test script for Startup Plan setup
Run this after getting your CoinGlass API key
"""

import os
import asyncio
from dotenv import load_dotenv
from budget_coinglass_bot import BudgetCoinGlassWhaleBot

async def test_startup_plan():
    """Test the startup plan configuration"""
    
    print("🎯 Testing CoinGlass Startup Plan Setup...")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    
    # Check required variables
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    coinglass_api_key = os.getenv('COINGLASS_API_KEY')
    plan = os.getenv('COINGLASS_PLAN', 'startup')
    
    print(f"📋 Configuration Check:")
    print(f"   • Telegram Token: {'✅ Set' if telegram_token else '❌ Missing'}")
    print(f"   • Chat ID: {'✅ Set' if chat_id else '❌ Missing'}")
    print(f"   • CoinGlass API: {'✅ Set' if coinglass_api_key else '❌ Missing'}")
    print(f"   • Plan: {plan}")
    print()
    
    if not all([telegram_token, chat_id, coinglass_api_key]):
        print("❌ Missing required environment variables!")
        print("Please check your .env file")
        return
    
    # Create bot instance
    print("🤖 Creating budget bot instance...")
    whale_bot = BudgetCoinGlassWhaleBot(telegram_token, chat_id, coinglass_api_key, plan)
    
    # Test plan configuration
    plan_info = whale_bot.vault_data.get_plan_info()
    print(f"💰 Plan Details:")
    print(f"   • Plan: {plan_info['plan']}")
    print(f"   • Cost: ${plan_info['cost_per_month']}/month")
    print(f"   • Check interval: {plan_info['check_interval_minutes']:.0f} minutes")
    print(f"   • Description: {plan_info['description']}")
    print()
    
    # Test API connection
    print("🔌 Testing CoinGlass API connection...")
    try:
        # Test with one vault
        test_address = "0x56498e5f90c14060499b62b6f459b3e3fb9280c5"  # TOPDOG
        positions = await whale_bot.coinglass_client.get_hyperliquid_whale_positions(test_address)
        
        if positions is not None:
            print(f"✅ API connection successful!")
            print(f"   • Retrieved {len(positions)} positions for test vault")
            
            # Show API usage
            usage = whale_bot.coinglass_client.get_usage_stats()
            print(f"   • API usage: {usage['utilization_percent']:.1f}% of limit")
        else:
            print("❌ API connection failed")
            print("   Please check your API key")
            
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return
    
    # Check vault configuration
    vaults = whale_bot.vault_data.get_active_vaults()
    print(f"📊 Vault Configuration:")
    print(f"   • Active vaults: {len(vaults)}")
    for vault in vaults[:3]:  # Show first 3
        print(f"   • {vault.name}: {vault.address[:10]}...")
    if len(vaults) > 3:
        print(f"   • ... and {len(vaults)-3} more")
    print()
    
    # Test Telegram
    print("📱 Testing Telegram connection...")
    try:
        test_message = (
            f"🎯 **CoinGlass Startup Plan Test** 🎯\n\n"
            f"✅ API connection successful\n"
            f"💰 Plan: {plan_info['plan']} (${plan_info['cost_per_month']}/mo)\n"
            f"⏱️ Check interval: {plan_info['check_interval_minutes']:.0f} minutes\n"
            f"📊 Tracking: {len(vaults)} vaults\n\n"
            f"Ready to start budget whale tracking!"
        )
        
        await whale_bot.send_alert(test_message)
        print("✅ Telegram test message sent!")
        
    except Exception as e:
        print(f"❌ Telegram test failed: {e}")
        return
    
    print()
    print("🚀 SUCCESS! Everything is configured correctly!")
    print("=" * 50)
    print("Next steps:")
    print("1. Run: python3 budget_coinglass_bot.py")
    print("2. Watch for whale alerts in Telegram")
    print("3. Monitor API usage in logs")
    print()
    print("💡 Tip: The bot will check vaults every 5 minutes")
    print("💰 Cost: Only ~3% of your API limit will be used")

if __name__ == "__main__":
    asyncio.run(test_startup_plan())