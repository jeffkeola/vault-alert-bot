import os
import asyncio
import logging
import json
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Optional, Set

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class VaultData:
    def __init__(self):
        self.addresses: Set[str] = set()
        self.previous_positions: Dict[str, Dict[str, Decimal]] = {}
        self.is_monitoring = False
        self.threshold = Decimal('1000')  # $1000 threshold
        
    def add_vault(self, address: str) -> bool:
        """Add a vault address to monitor"""
        if address not in self.addresses:
            self.addresses.add(address)
            self.previous_positions[address] = {}
            return True
        return False
    
    def remove_vault(self, address: str) -> bool:
        """Remove a vault address from monitoring"""
        if address in self.addresses:
            self.addresses.remove(address)
            self.previous_positions.pop(address, None)
            return True
        return False
    
    def get_vault_list(self) -> List[str]:
        """Get list of monitored vault addresses"""
        return list(self.addresses)

class HyperliquidVaultBot:
    def __init__(self, telegram_bot_token: str, chat_id: str):
        self.bot_token = telegram_bot_token
        self.chat_id = chat_id
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.vault_data = VaultData()
        self.monitoring_task: Optional[asyncio.Task] = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = (
            "🤖 *Hyperliquid Vault Monitor Bot*\n\n"
            "*Available Commands:*\n"
            "/start - Show this help message\n"
            "/add\\_vault <address> - Add vault address to monitor\n"
            "/list\\_vaults - Show all monitored vaults\n"
            "/status - Show bot status and settings\n\n"
            "*Settings:*\n"
            f"• Alert Threshold: ${self.vault_data.threshold:,}\n"
            "• Check Interval: 90 seconds\n"
            "• Address Delay: 10 seconds\n\n"
            "Start by adding vault addresses with /add\\_vault command!"
        )
        await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
        logger.info(f"Start command executed by user {update.effective_user.id}")
    
    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command"""
        if not context.args:
            await update.message.reply_text("Please provide a vault address: /add_vault <address>")
            return
        
        address = context.args[0].strip()
        
        # Basic validation
        if len(address) < 10:
            await update.message.reply_text("❌ Invalid address format")
            return
        
        if self.vault_data.add_vault(address):
            message = f"✅ Added vault address: `{address}`\n\nMonitoring will begin automatically."
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            
            # Start monitoring if not already running
            if not self.vault_data.is_monitoring:
                await self.start_monitoring()
            
            logger.info(f"Added vault address: {address}")
        else:
            await update.message.reply_text("⚠️ This address is already being monitored")
    
    async def list_vaults_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_vaults command"""
        vaults = self.vault_data.get_vault_list()
        
        if not vaults:
            await update.message.reply_text("📭 No vault addresses being monitored.\n\nUse /add_vault <address> to add one.")
            return
        
        message = "*Monitored Vault Addresses:*\n\n"
        for i, address in enumerate(vaults, 1):
            message += f"{i}\\. `{address}`\n"
        
        message += f"\n*Total:* {len(vaults)} vault\\(s\\)"
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        status_icon = "🟢" if self.vault_data.is_monitoring else "🔴"
        status_text = "Active" if self.vault_data.is_monitoring else "Stopped"
        
        message = (
            f"🤖 *Bot Status:* {status_icon} {status_text}\n\n"
            f"*Configuration:*\n"
            f"• Alert Threshold: ${self.vault_data.threshold:,}\n"
            f"• Check Interval: 90 seconds\n"
            f"• Address Delay: 10 seconds\n"
            f"• Monitored Vaults: {len(self.vault_data.addresses)}\n\n"
            f"*Last Check:* {datetime.now().strftime('%Y\\-%-m\\-%-d %H:%M:%S')}"
        )
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    
    async def get_vault_positions(self, address: str) -> Dict[str, Decimal]:
        """Get current vault positions for a specific address"""
        try:
            positions = {}
            
            # Get user state for the specific address
            user_state = self.info.user_state(address)
            
            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    pos_data = position['position']
                    if pos_data['szi'] != '0':
                        coin = pos_data['coin']
                        size = Decimal(pos_data['szi'])
                        entry_px = Decimal(pos_data['entryPx'] or '0')
                        unrealized_pnl = Decimal(pos_data['unrealizedPnl'])
                        
                        # Calculate position value
                        position_value = abs(size * entry_px) + unrealized_pnl
                        positions[coin] = position_value
                        
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return {}
    
    async def check_vault_changes(self, address: str):
        """Check for significant position changes for a specific vault"""
        try:
            current_positions = await self.get_vault_positions(address)
            previous_positions = self.vault_data.previous_positions.get(address, {})
            
            # Check existing positions for changes
            for coin, current_value in current_positions.items():
                previous_value = previous_positions.get(coin, Decimal('0'))
                change = abs(current_value - previous_value)
                
                if change >= self.vault_data.threshold:
                    change_percent = (change / previous_value * 100) if previous_value > 0 else 0
                    direction = "📈" if current_value > previous_value else "📉"
                    
                    message = (
                        f"{direction} *VAULT POSITION ALERT*\n\n"
                        f"*Vault:* `{address[:8]}...{address[-6:]}`\n"
                        f"*Coin:* {coin}\n"
                        f"*Previous:* ${previous_value:,.2f}\n"
                        f"*Current:* ${current_value:,.2f}\n"
                        f"*Change:* ${change:,.2f} \\({change_percent:.2f}%\\)\n"
                        f"*Time:* {datetime.now().strftime('%H:%M:%S')}"
                    )
                    
                    await self.send_alert(message)
            
            # Check for new positions
            for coin in current_positions:
                if coin not in previous_positions:
                    message = (
                        f"🆕 *NEW POSITION OPENED*\n\n"
                        f"*Vault:* `{address[:8]}...{address[-6:]}`\n"
                        f"*Coin:* {coin}\n"
                        f"*Value:* ${current_positions[coin]:,.2f}\n"
                        f"*Time:* {datetime.now().strftime('%H:%M:%S')}"
                    )
                    await self.send_alert(message)
            
            # Check for closed positions
            for coin in previous_positions:
                if coin not in current_positions:
                    message = (
                        f"❌ *POSITION CLOSED*\n\n"
                        f"*Vault:* `{address[:8]}...{address[-6:]}`\n"
                        f"*Coin:* {coin}\n"
                        f"*Previous Value:* ${previous_positions[coin]:,.2f}\n"
                        f"*Time:* {datetime.now().strftime('%H:%M:%S')}"
                    )
                    await self.send_alert(message)
            
            # Update previous positions for this address
            self.vault_data.previous_positions[address] = current_positions.copy()
            
        except Exception as e:
            logger.error(f"Error checking changes for vault {address}: {e}")
    
    async def send_alert(self, message: str):
        """Send alert message to Telegram"""
        try:
            bot = Bot(token=self.bot_token)
            await bot.send_message(chat_id=self.chat_id, text=message, parse_mode='MarkdownV2')
            logger.info(f"Alert sent: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending alert: {e}")
    
    async def monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("Starting vault monitoring loop...")
        
        while self.vault_data.is_monitoring:
            try:
                if not self.vault_data.addresses:
                    logger.info("No vault addresses to monitor, waiting...")
                    await asyncio.sleep(90)
                    continue
                
                logger.info(f"Checking {len(self.vault_data.addresses)} vault(s)...")
                
                # Check each vault with 10-second delay between them
                for i, address in enumerate(self.vault_data.addresses):
                    if not self.vault_data.is_monitoring:
                        break
                    
                    logger.info(f"Checking vault {i+1}/{len(self.vault_data.addresses)}: {address[:8]}...")
                    await self.check_vault_changes(address)
                    
                    # Add delay between addresses (except for the last one)
                    if i < len(self.vault_data.addresses) - 1:
                        await asyncio.sleep(10)
                
                # Wait 90 seconds before next round
                await asyncio.sleep(90)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(90)
    
    async def start_monitoring(self):
        """Start the monitoring process"""
        if not self.vault_data.is_monitoring:
            self.vault_data.is_monitoring = True
            self.monitoring_task = asyncio.create_task(self.monitoring_loop())
            
            # Send startup message
            startup_message = (
                f"🚀 *Vault Monitoring Started*\n\n"
                f"*Settings:*\n"
                f"• Threshold: ${self.vault_data.threshold:,}\n"
                f"• Interval: 90 seconds\n"
                f"• Address Delay: 10 seconds\n"
                f"• Vaults: {len(self.vault_data.addresses)}\n"
                f"*Started:* {datetime.now().strftime('%Y\\-%-m\\-%-d %H:%M:%S')}"
            )
            await self.send_alert(startup_message)
    
    async def stop_monitoring(self):
        """Stop the monitoring process"""
        self.vault_data.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None

async def main():
    # Get environment variables
    telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not telegram_bot_token or not chat_id:
        logger.error("Missing required environment variables: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID")
        return
    
    # Create bot instance
    vault_bot = HyperliquidVaultBot(telegram_bot_token, chat_id)
    
    # Create Telegram application
    application = Application.builder().token(telegram_bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", vault_bot.start_command))
    application.add_handler(CommandHandler("add_vault", vault_bot.add_vault_command))
    application.add_handler(CommandHandler("list_vaults", vault_bot.list_vaults_command))
    application.add_handler(CommandHandler("status", vault_bot.status_command))
    
    logger.info("Starting Telegram bot...")
    
    try:
        # Start the bot
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        # Cleanup
        await vault_bot.stop_monitoring()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())