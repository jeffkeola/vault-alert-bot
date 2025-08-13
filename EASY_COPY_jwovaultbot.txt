#!/usr/bin/env python3
"""
JWOvaultbot - Advanced Crypto Vault Intelligence Bot
Monitors Hyperliquid vaults/wallets for confluence trading signals
"""

import asyncio
import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from hyperliquid.info import Info
from hyperliquid.utils import constants
import websocket
import threading

from confluence_engine import ConfluenceEngine, format_confluence_alert

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AZURE_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION")  # To be added when Azure is ready

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JWOVaultBot:
    def __init__(self):
        self.bot = None
        self.application = None
        self.hyperliquid_info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.ws_connection = None
        self.tracking_active = False
        
        # Default rules
        self.rules = {
            'confluence_count': 2,      # Number of addresses needed for alert
            'time_window': 300,         # 5 minutes in seconds
            'min_trade_value': 1000,    # Minimum $1k trade value
            'enabled': True
        }
        
        # Initialize database
        self.init_database()
        
        # Initialize confluence engine
        self.confluence_engine = ConfluenceEngine(
            database_conn=self.conn,
            rules=self.rules,
            alert_callback=self.send_confluence_alert
        )

    def init_database(self):
        """Initialize SQLite database (will migrate to Azure later)"""
        self.conn = sqlite3.connect('jwovaultbot.db', check_same_thread=False)
        self.conn.execute('PRAGMA foreign_keys = ON')
        
        # Create tables
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS tracked_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('vault', 'wallet')),
                name TEXT,
                weight REAL DEFAULT 1.0,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            );
            
            CREATE TABLE IF NOT EXISTS trade_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT UNIQUE NOT NULL,
                rule_value TEXT NOT NULL,
                updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS detected_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
                size REAL NOT NULL,
                price REAL NOT NULL,
                value_usd REAL NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                raw_data TEXT
            );
            
            CREATE TABLE IF NOT EXISTS confluence_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                addresses_count INTEGER NOT NULL,
                total_value REAL NOT NULL,
                time_window INTEGER NOT NULL,
                alert_sent BOOLEAN DEFAULT FALSE,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON detected_trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_trades_asset_direction ON detected_trades(asset, direction);
        ''')
        
        # Initialize default rules
        self.save_rules()
        self.conn.commit()
        logger.info("Database initialized successfully")

    def save_rules(self):
        """Save current rules to database"""
        for rule_name, rule_value in self.rules.items():
            self.conn.execute('''
                INSERT OR REPLACE INTO trade_rules (rule_name, rule_value, updated_date)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (rule_name, str(rule_value)))

    def load_rules(self):
        """Load rules from database"""
        cursor = self.conn.execute('SELECT rule_name, rule_value FROM trade_rules')
        for rule_name, rule_value in cursor.fetchall():
            if rule_name in ['confluence_count', 'time_window', 'min_trade_value']:
                self.rules[rule_name] = int(rule_value) if rule_value.isdigit() else float(rule_value)
            elif rule_name == 'enabled':
                self.rules[rule_name] = rule_value.lower() == 'true'
            else:
                self.rules[rule_name] = rule_value

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_msg = """
🤖 **JWOvaultbot Activated!**

🎯 **Vault Intelligence Commands:**
• `/add_vault <address>` - Track a Hyperliquid vault
• `/add_wallet <address>` - Track a wallet address  
• `/remove_vault <address>` - Stop tracking vault
• `/remove_wallet <address>` - Stop tracking wallet
• `/list_tracked` - Show all tracked addresses

⚙️ **Rule Configuration:**
• `/set_rule confluence <number>` - Addresses needed for alert
• `/set_rule time_window <seconds>` - Time window for confluence
• `/set_rule min_value <amount>` - Minimum trade value ($)
• `/show_rules` - Display current rules

📊 **Monitoring:**
• `/start_monitoring` - Begin real-time tracking
• `/stop_monitoring` - Pause tracking
• `/status` - Show bot status

🚨 **Current Rules:**
• Confluence: {confluence_count} addresses
• Time Window: {time_window}s ({time_window//60}min)
• Min Value: ${min_trade_value:,}

Ready to track vault confluence! 🚀
        """.format(**self.rules)
        
        await update.message.reply_text(welcome_msg)

    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide vault address: `/add_vault 0x123...`")
            return
        
        address = context.args[0]
        name = ' '.join(context.args[1:]) if len(context.args) > 1 else f"Vault {address[:8]}..."
        
        try:
            # Verify address exists on Hyperliquid
            user_state = self.hyperliquid_info.user_state(address)
            if not user_state:
                await update.message.reply_text(f"❌ Address {address} not found on Hyperliquid")
                return
            
            # Add to database
            self.conn.execute('''
                INSERT OR REPLACE INTO tracked_addresses (address, type, name)
                VALUES (?, ?, ?)
            ''', (address, 'vault', name))
            self.conn.commit()
            
            await update.message.reply_text(f"✅ Added vault: {name}\n📍 Address: `{address}`")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding vault: {str(e)}")

    async def add_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_wallet command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide wallet address: `/add_wallet 0x456...`")
            return
        
        address = context.args[0]
        name = ' '.join(context.args[1:]) if len(context.args) > 1 else f"Wallet {address[:8]}..."
        
        try:
            # Verify address exists on Hyperliquid
            user_state = self.hyperliquid_info.user_state(address)
            if not user_state:
                await update.message.reply_text(f"❌ Address {address} not found on Hyperliquid")
                return
            
            # Add to database
            self.conn.execute('''
                INSERT OR REPLACE INTO tracked_addresses (address, type, name)
                VALUES (?, ?, ?)
            ''', (address, 'wallet', name))
            self.conn.commit()
            
            await update.message.reply_text(f"✅ Added wallet: {name}\n📍 Address: `{address}`")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding wallet: {str(e)}")

    async def list_tracked_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_tracked command"""
        cursor = self.conn.execute('''
            SELECT address, type, name, weight, added_date, active 
            FROM tracked_addresses 
            ORDER BY type, added_date
        ''')
        
        tracked = cursor.fetchall()
        if not tracked:
            await update.message.reply_text("📭 No addresses being tracked yet.\nUse `/add_vault` or `/add_wallet` to start!")
            return
        
        msg = "📋 **Tracked Addresses:**\n\n"
        vaults = [t for t in tracked if t[1] == 'vault']
        wallets = [t for t in tracked if t[1] == 'wallet']
        
        if vaults:
            msg += "🏦 **Vaults:**\n"
            for addr, _, name, weight, added, active in vaults:
                status = "🟢" if active else "🔴"
                msg += f"{status} {name}\n   `{addr}`\n"
        
        if wallets:
            msg += "\n💼 **Wallets:**\n" 
            for addr, _, name, weight, added, active in wallets:
                status = "🟢" if active else "🔴"
                msg += f"{status} {name}\n   `{addr}`\n"
        
        msg += f"\n📊 Total: {len(tracked)} addresses"
        await update.message.reply_text(msg)

    async def set_rule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_rule command"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Usage: `/set_rule <rule> <value>`\n\n"
                "Available rules:\n"
                "• `confluence <number>` - Addresses needed\n"
                "• `time_window <seconds>` - Time window\n" 
                "• `min_value <amount>` - Minimum trade value"
            )
            return
        
        rule_name = context.args[0]
        rule_value = context.args[1]
        
        try:
            if rule_name == 'confluence':
                self.rules['confluence_count'] = int(rule_value)
                msg = f"✅ Confluence requirement set to {rule_value} addresses"
            elif rule_name == 'time_window':
                self.rules['time_window'] = int(rule_value)
                msg = f"✅ Time window set to {rule_value} seconds ({int(rule_value)//60} minutes)"
            elif rule_name == 'min_value':
                self.rules['min_trade_value'] = float(rule_value)
                msg = f"✅ Minimum trade value set to ${float(rule_value):,.0f}"
            else:
                await update.message.reply_text(f"❌ Unknown rule: {rule_name}")
                return
            
            self.save_rules()
            self.conn.commit()
            await update.message.reply_text(msg)
            
        except ValueError:
            await update.message.reply_text(f"❌ Invalid value for {rule_name}: {rule_value}")

    async def show_rules_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /show_rules command"""
        msg = f"""
⚙️ **Current Rules:**

🎯 Confluence Count: **{self.rules['confluence_count']}** addresses
⏱️ Time Window: **{self.rules['time_window']}s** ({self.rules['time_window']//60} minutes)
💰 Min Trade Value: **${self.rules['min_trade_value']:,.0f}**
🔄 Monitoring: **{"Enabled" if self.rules['enabled'] else "Disabled"}**

📝 Use `/set_rule <rule> <value>` to modify
        """
        await update.message.reply_text(msg)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        # Count tracked addresses
        cursor = self.conn.execute('SELECT COUNT(*) FROM tracked_addresses WHERE active = TRUE')
        tracked_count = cursor.fetchone()[0]
        
        # Get recent trades count
        cursor = self.conn.execute('''
            SELECT COUNT(*) FROM detected_trades 
            WHERE timestamp > datetime('now', '-1 hour')
        ''')
        recent_trades = cursor.fetchone()[0]
        
        msg = f"""
📊 **JWOvaultbot Status**

🎯 Tracked Addresses: **{tracked_count}**
📈 Recent Trades (1h): **{recent_trades}**
🔄 Monitoring: **{"Active" if self.tracking_active else "Stopped"}**
💰 Min Trade Value: **${self.rules['min_trade_value']:,.0f}**
🎪 Confluence Need: **{self.rules['confluence_count']} addresses**

⚡ Hyperliquid API: **Connected**
🤖 Bot Status: **Online**
        """
        await update.message.reply_text(msg)

    async def start_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_monitoring command"""
        if self.tracking_active:
            await update.message.reply_text("🔄 Monitoring is already active!")
            return
        
        cursor = self.conn.execute('SELECT COUNT(*) FROM tracked_addresses WHERE active = TRUE')
        tracked_count = cursor.fetchone()[0]
        
        if tracked_count == 0:
            await update.message.reply_text("❌ No addresses to track! Add vaults/wallets first.")
            return
        
        self.confluence_engine.rules = self.rules
        self.tracking_active = True
        asyncio.create_task(self.confluence_engine.start_monitoring())
        
        await update.message.reply_text(f"🚀 **Monitoring Started!** Tracking {tracked_count} addresses")

    async def stop_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_monitoring command"""
        self.tracking_active = False
        self.confluence_engine.stop_monitoring()
        await update.message.reply_text("⏹️ **Monitoring Stopped**")

    async def remove_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_vault command"""
        if not context.args:
            await update.message.reply_text("❌ Provide address: `/remove_vault 0x123...`")
            return
        
        address = context.args[0]
        self.conn.execute('DELETE FROM tracked_addresses WHERE address = ? AND type = "vault"', (address,))
        self.conn.commit()
        await update.message.reply_text(f"✅ Removed vault: {address[:8]}...")

    async def remove_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_wallet command"""
        if not context.args:
            await update.message.reply_text("❌ Provide address: `/remove_wallet 0x456...`")
            return
        
        address = context.args[0]
        self.conn.execute('DELETE FROM tracked_addresses WHERE address = ? AND type = "wallet"', (address,))
        self.conn.commit()
        await update.message.reply_text(f"✅ Removed wallet: {address[:8]}...")

    async def recent_alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /recent_alerts command"""
        alerts = self.confluence_engine.get_recent_alerts(24)
        if not alerts:
            await update.message.reply_text("📭 No recent confluence alerts")
            return
        
        msg = "📊 **Recent Alerts:**\n"
        for alert in alerts[:5]:
            msg += f"• {alert['asset']} {alert['direction']} - {alert['addresses_count']} addresses\n"
        await update.message.reply_text(msg)

    async def send_confluence_alert(self, alert):
        """Send confluence alert to Telegram"""
        try:
            message = format_confluence_alert(alert)
            await self.application.bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")

    def setup_bot(self):
        """Setup Telegram bot with command handlers"""
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("add_vault", self.add_vault_command))
        self.application.add_handler(CommandHandler("add_wallet", self.add_wallet_command))
        self.application.add_handler(CommandHandler("list_tracked", self.list_tracked_command))
        self.application.add_handler(CommandHandler("set_rule", self.set_rule_command))
        self.application.add_handler(CommandHandler("show_rules", self.show_rules_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("start_monitoring", self.start_monitoring_command))
        self.application.add_handler(CommandHandler("stop_monitoring", self.stop_monitoring_command))
        self.application.add_handler(CommandHandler("remove_vault", self.remove_vault_command))
        self.application.add_handler(CommandHandler("remove_wallet", self.remove_wallet_command))
        self.application.add_handler(CommandHandler("recent_alerts", self.recent_alerts_command))
        
        logger.info("JWOvaultbot command handlers registered")

    async def run_bot(self):
        """Start the bot"""
        logger.info("Starting JWOvaultbot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # Send startup message
        startup_msg = "🤖 **JWOvaultbot Online!**\n\nReady to track vault confluence.\nType `/start` for commands."
        await self.application.bot.send_message(chat_id=CHAT_ID, text=startup_msg)
        
        logger.info("JWOvaultbot is running!")

def main():
    """Main entry point"""
    print("🚀 Initializing JWOvaultbot...")
    
    bot = JWOVaultBot()
    bot.setup_bot()
    
    try:
        asyncio.run(bot.run_bot())
    except KeyboardInterrupt:
        print("\n👋 JWOvaultbot shutting down...")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()