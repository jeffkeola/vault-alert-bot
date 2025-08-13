#!/usr/bin/env python3
"""
JWOvaultbot V2 - Crypto Trading Intelligence System
Enhanced version using userFills API for more accurate trade detection
"""

import os
import asyncio
import logging
import sqlite3
from typing import Dict, List
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Import both versions
from confluence_engine import ConfluenceEngine as ConfluenceEngineV1, format_confluence_alert as format_v1
from confluence_engine_v2 import ConfluenceEngineV2, format_confluence_alert as format_v2

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID'))

# Bot version setting - change this to switch between engines
USE_V2 = True  # Set to False to use V1 (position monitoring), True for V2 (userFills)

class JWOVaultBotV2:
    def __init__(self):
        logger.info("🚀 Initializing JWOvaultbot V2...")
        
        # Initialize database
        self.init_database()
        
        # Set up rules with default values
        self.rules = {
            'confluence_count': 2,
            'time_window': 300,  # 5 minutes in seconds
            'min_trade_value': 1000,
            'polling_interval': 30
        }
        
        # Initialize the appropriate confluence engine
        if USE_V2:
            logger.info("Using ConfluenceEngine V2 (userFills API)")
            self.confluence_engine = ConfluenceEngineV2(
                db_path="jwovaultbot.db",
                alert_callback=self.send_confluence_alert
            )
            self.format_alert = format_v2
        else:
            logger.info("Using ConfluenceEngine V1 (position monitoring)")
            self.confluence_engine = ConfluenceEngineV1(
                db_path="jwovaultbot.db",
                alert_callback=self.send_confluence_alert
            )
            self.format_alert = format_v1
        
        # Initialize bot
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.setup_handlers()
        
        logger.info("JWOvaultbot command handlers registered")

    def init_database(self):
        """Initialize database tables"""
        try:
            db = sqlite3.connect("jwovaultbot.db")
            
            # Main tables (shared between V1 and V2)
            db.execute('''
                CREATE TABLE IF NOT EXISTS tracked_addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            db.execute('''
                CREATE TABLE IF NOT EXISTS bot_rules (
                    rule_name TEXT PRIMARY KEY,
                    rule_value TEXT NOT NULL,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            db.commit()
            db.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def setup_handlers(self):
        """Set up Telegram command handlers"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("add_vault", self.add_vault_command))
        self.application.add_handler(CommandHandler("add_wallet", self.add_wallet_command))
        self.application.add_handler(CommandHandler("remove_vault", self.remove_vault_command))
        self.application.add_handler(CommandHandler("remove_wallet", self.remove_wallet_command))
        self.application.add_handler(CommandHandler("list_tracked", self.list_tracked_command))
        self.application.add_handler(CommandHandler("set_rule", self.set_rule_command))
        self.application.add_handler(CommandHandler("show_rules", self.show_rules_command))
        self.application.add_handler(CommandHandler("start_monitoring", self.start_monitoring_command))
        self.application.add_handler(CommandHandler("stop_monitoring", self.stop_monitoring_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("version", self.version_command))
        self.application.add_handler(CommandHandler("switch_version", self.switch_version_command))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        version_info = "V2 (userFills)" if USE_V2 else "V1 (positions)"
        
        welcome_msg = f"""🤖 **JWOvaultbot V2 Activated!**

**Current Version:** {version_info}

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

🔧 **Version Control:**
• `/version` - Show current engine version
• `/switch_version` - Toggle between V1/V2 engines

🚨 **Current Rules:**
• Confluence: {self.rules['confluence_count']} addresses
• Time Window: {self.rules['time_window']}s ({self.rules['time_window']//60}min)
• Min Value: ${self.rules['min_trade_value']:,}

Ready to track vault confluence! 🚀"""
        
        await update.message.reply_text(welcome_msg)

    async def version_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current engine version"""
        version_info = "V2 (userFills API)" if USE_V2 else "V1 (position monitoring)"
        
        await update.message.reply_text(f"""🔧 **Engine Version Info**

**Currently Using:** {version_info}

**V1 Features:**
• Position change monitoring
• 30-second polling interval
• Detects net position changes

**V2 Features:**
• Direct userFills API monitoring  
• Real-time trade detection
• Exact trade timestamps & prices
• More accurate confluence detection

**Note:** Restart required to switch versions permanently.
Use `/switch_version` to change for next restart.""")

    async def switch_version_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Instructions for switching engine versions"""
        current = "V2" if USE_V2 else "V1"
        next_version = "V1" if USE_V2 else "V2"
        
        await update.message.reply_text(f"""🔄 **Version Switching**

**Currently:** {current}
**To Switch To:** {next_version}

**Manual Steps:**
1. Edit `jwovaultbot_v2.py`
2. Change `USE_V2 = {USE_V2}` to `USE_V2 = {not USE_V2}`
3. Redeploy on Render
4. Restart the bot

**Both versions store data separately:**
• V1 uses `trades` and `confluence_alerts` tables
• V2 uses `trades_v2` and `confluence_alerts_v2` tables

This allows easy comparison and rollback! 📊""")

    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide vault address.\n\nUsage: `/add_vault <address>`")
            return
        
        address = context.args[0]
        name = f"Vault-{address[:8]}"
        
        try:
            db = sqlite3.connect("jwovaultbot.db")
            db.execute('''
                INSERT OR REPLACE INTO tracked_addresses (address, type, name, active)
                VALUES (?, ?, ?, 1)
            ''', (address, 'vault', name))
            db.commit()
            db.close()
            
            await update.message.reply_text(f"✅ Added vault: {name}\nAddress: `{address}`")
            logger.info(f"Added vault: {address}")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding vault: {e}")
            logger.error(f"Error adding vault: {e}")

    async def add_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_wallet command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide wallet address.\n\nUsage: `/add_wallet <address>`")
            return
        
        address = context.args[0]
        name = f"Wallet-{address[:8]}"
        
        try:
            db = sqlite3.connect("jwovaultbot.db")
            db.execute('''
                INSERT OR REPLACE INTO tracked_addresses (address, type, name, active)
                VALUES (?, ?, ?, 1)
            ''', (address, 'wallet', name))
            db.commit()
            db.close()
            
            await update.message.reply_text(f"✅ Added wallet: {name}\nAddress: `{address}`")
            logger.info(f"Added wallet: {address}")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding wallet: {e}")
            logger.error(f"Error adding wallet: {e}")

    async def remove_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_vault command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide vault address.\n\nUsage: `/remove_vault <address>`")
            return
        
        address = context.args[0]
        
        try:
            db = sqlite3.connect("jwovaultbot.db")
            cursor = db.execute('UPDATE tracked_addresses SET active = 0 WHERE address = ? AND type = ?', (address, 'vault'))
            
            if cursor.rowcount > 0:
                await update.message.reply_text(f"✅ Removed vault: {address[:8]}...")
                logger.info(f"Removed vault: {address}")
            else:
                await update.message.reply_text(f"❌ Vault not found: {address[:8]}...")
                
            db.commit()
            db.close()
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error removing vault: {e}")
            logger.error(f"Error removing vault: {e}")

    async def remove_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_wallet command"""
        if not context.args:
            await update.message.reply_text("❌ Please provide wallet address.\n\nUsage: `/remove_wallet <address>`")
            return
        
        address = context.args[0]
        
        try:
            db = sqlite3.connect("jwovaultbot.db")
            cursor = db.execute('UPDATE tracked_addresses SET active = 0 WHERE address = ? AND type = ?', (address, 'wallet'))
            
            if cursor.rowcount > 0:
                await update.message.reply_text(f"✅ Removed wallet: {address[:8]}...")
                logger.info(f"Removed wallet: {address}")
            else:
                await update.message.reply_text(f"❌ Wallet not found: {address[:8]}...")
                
            db.commit()
            db.close()
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error removing wallet: {e}")
            logger.error(f"Error removing wallet: {e}")

    async def list_tracked_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_tracked command"""
        try:
            db = sqlite3.connect("jwovaultbot.db")
            cursor = db.execute('SELECT address, type, name FROM tracked_addresses WHERE active = 1')
            tracked = cursor.fetchall()
            db.close()
            
            if not tracked:
                await update.message.reply_text("📝 No addresses currently tracked.\n\nUse `/add_vault` or `/add_wallet` to start tracking.")
                return
            
            message_lines = ["📝 **Tracked Addresses:**\n"]
            
            vaults = [item for item in tracked if item[1] == 'vault']
            wallets = [item for item in tracked if item[1] == 'wallet']
            
            if vaults:
                message_lines.append("🏦 **Vaults:**")
                for address, _, name in vaults:
                    message_lines.append(f"• {name}: `{address}`")
                message_lines.append("")
            
            if wallets:
                message_lines.append("👛 **Wallets:**")
                for address, _, name in wallets:
                    message_lines.append(f"• {name}: `{address}`")
            
            await update.message.reply_text("\n".join(message_lines))
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error listing tracked addresses: {e}")
            logger.error(f"Error listing tracked: {e}")

    async def set_rule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_rule command"""
        if len(context.args) < 2:
            await update.message.reply_text("""❌ Please provide rule name and value.

**Usage Examples:**
• `/set_rule confluence 3` - Need 3 addresses for alert
• `/set_rule time_window 600` - 10 minute time window  
• `/set_rule min_value 5000` - $5000 minimum trade value""")
            return
        
        rule_name = context.args[0]
        rule_value = context.args[1]
        
        try:
            # Validate and convert value
            if rule_name == 'confluence':
                value = int(rule_value)
                if value < 2:
                    raise ValueError("Confluence count must be at least 2")
                self.rules['confluence_count'] = value
                self.confluence_engine.update_rules('confluence_count', value)
                
            elif rule_name == 'time_window':
                value = int(rule_value)
                if value < 60:
                    raise ValueError("Time window must be at least 60 seconds")
                self.rules['time_window'] = value
                self.confluence_engine.update_rules('time_window', value)
                
            elif rule_name == 'min_value':
                value = float(rule_value)
                if value < 0:
                    raise ValueError("Minimum value must be positive")
                self.rules['min_trade_value'] = value
                self.confluence_engine.update_rules('min_trade_value', value)
                
            else:
                await update.message.reply_text(f"❌ Unknown rule: {rule_name}\n\nValid rules: confluence, time_window, min_value")
                return
            
            # Store in database
            db = sqlite3.connect("jwovaultbot.db")
            db.execute('''
                INSERT OR REPLACE INTO bot_rules (rule_name, rule_value)
                VALUES (?, ?)
            ''', (rule_name, str(value)))
            db.commit()
            db.close()
            
            await update.message.reply_text(f"✅ Updated rule: {rule_name} = {value}")
            logger.info(f"Updated rule: {rule_name} = {value}")
            
        except ValueError as e:
            await update.message.reply_text(f"❌ Invalid value: {e}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error setting rule: {e}")
            logger.error(f"Error setting rule: {e}")

    async def show_rules_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /show_rules command"""
        time_minutes = self.rules['time_window'] // 60
        version_info = "V2 (userFills)" if USE_V2 else "V1 (positions)"
        
        message = f"""⚙️ **Current Detection Rules** ({version_info})

🎯 **Confluence Count:** {self.rules['confluence_count']} addresses
⏱️ **Time Window:** {self.rules['time_window']} seconds ({time_minutes} minutes)
💰 **Minimum Trade Value:** ${self.rules['min_trade_value']:,}

**How it works:**
When {self.rules['confluence_count']} or more tracked addresses make similar trades (same asset, same direction) within {time_minutes} minutes, and each trade is worth at least ${self.rules['min_trade_value']:,}, you'll get an alert! 🚨

**Change rules with:**
• `/set_rule confluence <number>`
• `/set_rule time_window <seconds>`
• `/set_rule min_value <amount>`"""
        
        await update.message.reply_text(message)

    async def start_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_monitoring command"""
        try:
            # Check if we have tracked addresses
            db = sqlite3.connect("jwovaultbot.db")
            cursor = db.execute('SELECT COUNT(*) FROM tracked_addresses WHERE active = 1')
            count = cursor.fetchone()[0]
            db.close()
            
            if count == 0:
                await update.message.reply_text("❌ No addresses tracked. Add some vaults or wallets first!\n\nUse `/add_vault` or `/add_wallet`")
                return
            
            version_info = "V2 (userFills)" if USE_V2 else "V1 (positions)"
            
            # Start monitoring in background
            asyncio.create_task(self.confluence_engine.start_monitoring())
            
            await update.message.reply_text(f"""✅ **Monitoring Started!** ({version_info})

🔍 Now tracking {count} addresses for confluence patterns.

**Active Rules:**
• Need {self.rules['confluence_count']} addresses for alert
• Time window: {self.rules['time_window']//60} minutes  
• Minimum trade: ${self.rules['min_trade_value']:,}

You'll receive alerts when smart money moves together! 🧠💰""")
            
            logger.info(f"Started monitoring {count} addresses")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error starting monitoring: {e}")
            logger.error(f"Error starting monitoring: {e}")

    async def stop_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_monitoring command"""
        try:
            self.confluence_engine.stop_monitoring()
            await update.message.reply_text("⏸️ **Monitoring Stopped**\n\nUse `/start_monitoring` to resume tracking.")
            logger.info("Stopped monitoring")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error stopping monitoring: {e}")
            logger.error(f"Error stopping monitoring: {e}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        try:
            # Get tracked addresses count
            db = sqlite3.connect("jwovaultbot.db")
            cursor = db.execute('SELECT COUNT(*) FROM tracked_addresses WHERE active = 1')
            tracked_count = cursor.fetchone()[0]
            
            # Get recent alerts count (last 24 hours)
            table_name = "confluence_alerts_v2" if USE_V2 else "confluence_alerts"
            cursor = db.execute(f'''
                SELECT COUNT(*) FROM {table_name}
                WHERE created_date > datetime('now', '-24 hours')
            ''')
            alerts_24h = cursor.fetchone()[0]
            db.close()
            
            version_info = "V2 (userFills)" if USE_V2 else "V1 (positions)"
            monitoring_status = "🟢 Active" if self.confluence_engine.monitoring_active else "🔴 Stopped"
            
            status_msg = f"""📊 **Bot Status** ({version_info})

🤖 **Monitoring:** {monitoring_status}
📍 **Tracked Addresses:** {tracked_count}
🚨 **Alerts (24h):** {alerts_24h}

⚙️ **Current Rules:**
• Confluence: {self.rules['confluence_count']} addresses
• Time Window: {self.rules['time_window']//60} minutes
• Min Trade: ${self.rules['min_trade_value']:,}

**Commands:**
• `/start_monitoring` - Start tracking
• `/stop_monitoring` - Stop tracking  
• `/list_tracked` - Show addresses
• `/show_rules` - View detection rules"""
            
            await update.message.reply_text(status_msg)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error getting status: {e}")
            logger.error(f"Error getting status: {e}")

    async def send_confluence_alert(self, alert):
        """Send confluence alert to Telegram"""
        try:
            message = self.format_alert(alert)
            await self.application.bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")

    async def run_bot(self):
        """Start the bot"""
        logger.info("Starting JWOvaultbot V2...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # Send startup message
        version_info = "V2 (userFills)" if USE_V2 else "V1 (positions)"
        startup_msg = f"🤖 **JWOvaultbot V2 Online!** ({version_info})\n\nReady to track vault confluence.\nType `/start` for commands."
        await self.application.bot.send_message(chat_id=CHAT_ID, text=startup_msg)
        
        logger.info("JWOvaultbot V2 is running!")
        
        # Keep running forever
        while True:
            await asyncio.sleep(1)

def main():
    """Main function"""
    try:
        bot = JWOVaultBotV2()
        asyncio.run(bot.run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise

if __name__ == "__main__":
    main()