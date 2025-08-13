import asyncio
import logging
import json
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
import os
from collections import defaultdict

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

def escape_markdown_v2(text: str) -> str:
    """Escape special characters for MarkdownV2"""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

@dataclass
class VaultInfo:
    address: str
    name: str
    
    def __str__(self):
        return f"{self.name} ({self.address[:8]}...{self.address[-6:]})"

@dataclass
class PositionData:
    coin: str
    size: Decimal
    timestamp: datetime
    
@dataclass
class TradeEvent:
    vault_name: str
    vault_address: str
    coin: str
    old_size: Decimal
    new_size: Decimal
    timestamp: datetime
    
    @property
    def size_change(self) -> Decimal:
        return abs(self.new_size - self.old_size)
    
    @property
    def trade_type(self) -> str:
        if self.old_size == 0:
            return "OPEN"
        elif self.new_size == 0:
            return "CLOSE"
        elif self.new_size > self.old_size:
            return "INCREASE"
        else:
            return "DECREASE"

class VaultData:
    def __init__(self):
        self.vaults: Dict[str, VaultInfo] = {}  # name -> VaultInfo
        self.previous_positions: Dict[str, Dict[str, PositionData]] = {}  # vault_address -> {coin -> PositionData}
        self.last_alerts: Dict[str, Dict[str, datetime]] = {}  # vault_address -> {coin -> last_alert_time}
        self.trade_events: List[TradeEvent] = []  # Recent trade events for confluence
        self.is_monitoring = False
        
        # Settings
        self.confluence_threshold = 1  # How many vaults need to trade same token
        self.confluence_window_minutes = 10  # Time window for confluence detection
        self.cooldown_minutes = 5  # Anti-spam cooldown per token per vault
        
    def add_vault(self, address: str, name: str) -> bool:
        """Add a vault with custom name"""
        if name not in self.vaults:
            self.vaults[name] = VaultInfo(address, name)
            self.previous_positions[address] = {}
            self.last_alerts[address] = {}
            return True
        return False
    
    def remove_vault(self, name: str) -> bool:
        """Remove a vault by name"""
        if name in self.vaults:
            vault_info = self.vaults[name]
            del self.vaults[name]
            self.previous_positions.pop(vault_info.address, None)
            self.last_alerts.pop(vault_info.address, None)
            return True
        return False
    
    def get_vault_by_name(self, name: str) -> Optional[VaultInfo]:
        """Get vault info by name"""
        return self.vaults.get(name)
    
    def get_vault_list(self) -> List[VaultInfo]:
        """Get list of all vaults"""
        return list(self.vaults.values())
    
    def is_cooldown_active(self, vault_address: str, coin: str) -> bool:
        """Check if cooldown is active for a specific token on a vault"""
        if vault_address not in self.last_alerts:
            return False
        if coin not in self.last_alerts[vault_address]:
            return False
        
        last_alert = self.last_alerts[vault_address][coin]
        cooldown_end = last_alert + timedelta(minutes=self.cooldown_minutes)
        return datetime.now() < cooldown_end
    
    def set_cooldown(self, vault_address: str, coin: str):
        """Set cooldown for a specific token on a vault"""
        if vault_address not in self.last_alerts:
            self.last_alerts[vault_address] = {}
        self.last_alerts[vault_address][coin] = datetime.now()
    
    def add_trade_event(self, event: TradeEvent):
        """Add a trade event for confluence tracking"""
        self.trade_events.append(event)
        # Clean up old events outside the confluence window
        cutoff_time = datetime.now() - timedelta(minutes=self.confluence_window_minutes)
        self.trade_events = [e for e in self.trade_events if e.timestamp > cutoff_time]
    
    def get_confluence_events(self, coin: str, current_time: datetime) -> List[TradeEvent]:
        """Get recent trade events for the same coin within confluence window"""
        cutoff_time = current_time - timedelta(minutes=self.confluence_window_minutes)
        return [e for e in self.trade_events if e.coin == coin and e.timestamp > cutoff_time]

class HyperliquidAdvancedBot:
    def __init__(self, telegram_bot_token: str, chat_id: str):
        self.bot_token = telegram_bot_token
        self.chat_id = chat_id
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.vault_data = VaultData()
        self.monitoring_task: Optional[asyncio.Task] = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            welcome_message = (
                "🤖 *Advanced Hyperliquid Position Monitor*\n\n"
                "*Commands:*\n"
                "/add\\_vault \\<address\\> \\<name\\> \\- Add vault with custom name\n"
                "/list\\_vaults \\- Show all monitored vaults\n"
                "/remove\\_vault \\<name\\> \\- Remove vault by name\n"
                "/status \\- Show bot status\n"
                "/set\\_confluence \\<number\\> \\- Set confluence threshold\n"
                "/set\\_window \\<minutes\\> \\- Set confluence time window\n"
                "/show\\_settings \\- Show current settings\n\n"
                "*Features:*\n"
                "• Tracks position SIZE changes \\(not value\\)\n"
                "• Confluence detection across vaults\n"
                "• Anti\\-spam protection \\(5min cooldowns\\)\n"
                "• Custom vault names\n\n"
                "Start by adding vaults with /add\\_vault\\!"
            )
            await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
            logger.info(f"Start command executed by user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("Welcome to Advanced Hyperliquid Monitor! Use /add_vault <address> <name> to start.")
    
    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command"""
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Please provide both address and name: /add\\_vault \\<address\\> \\<name\\>", 
                    parse_mode='MarkdownV2'
                )
                return
            
            address = context.args[0].strip()
            name = " ".join(context.args[1:]).strip()
            
            # Basic validation
            if len(address) < 10:
                await update.message.reply_text("❌ Invalid address format")
                return
            
            if len(name) < 1:
                await update.message.reply_text("❌ Name cannot be empty")
                return
            
            if self.vault_data.add_vault(address, name):
                escaped_name = escape_markdown_v2(name)
                escaped_address = escape_markdown_v2(f"{address[:8]}...{address[-6:]}")
                message = f"✅ Added vault: *{escaped_name}* \\(`{escaped_address}`\\)\n\nMonitoring will begin automatically\\."
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                
                # Start monitoring if not already running
                if not self.vault_data.is_monitoring:
                    await self.start_monitoring()
                
                logger.info(f"Added vault: {name} ({address})")
            else:
                await update.message.reply_text("⚠️ A vault with this name already exists")
        except Exception as e:
            logger.error(f"Error in add_vault command: {e}")
            await update.message.reply_text("Error adding vault. Please try again.")
    
    async def list_vaults_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_vaults command"""
        try:
            vaults = self.vault_data.get_vault_list()
            
            if not vaults:
                message = "📭 No vaults being monitored\\.\n\nUse /add\\_vault \\<address\\> \\<name\\> to add one\\."
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                return
            
            message = "📊 *Monitored Vaults:*\n\n"
            for i, vault in enumerate(vaults, 1):
                escaped_name = escape_markdown_v2(vault.name)
                escaped_address = escape_markdown_v2(f"{vault.address[:8]}...{vault.address[-6:]}")
                message += f"{i}\\. *{escaped_name}*\n   `{escaped_address}`\n\n"
            
            message += f"*Total:* {len(vaults)} vault\\(s\\)"
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in list_vaults command: {e}")
            vaults = self.vault_data.get_vault_list()
            simple_message = f"Monitored vaults ({len(vaults)}):\n"
            for i, vault in enumerate(vaults, 1):
                simple_message += f"{i}. {vault.name} ({vault.address[:8]}...)\n"
            await update.message.reply_text(simple_message)
    
    async def remove_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_vault command"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide vault name: /remove\\_vault \\<name\\>", parse_mode='MarkdownV2')
                return
            
            name = " ".join(context.args).strip()
            
            if self.vault_data.remove_vault(name):
                escaped_name = escape_markdown_v2(name)
                message = f"✅ Removed vault: *{escaped_name}*"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Removed vault: {name}")
            else:
                await update.message.reply_text("❌ Vault not found")
        except Exception as e:
            logger.error(f"Error in remove_vault command: {e}")
            await update.message.reply_text("Error removing vault. Please try again.")
    
    async def set_confluence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_confluence command"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide number: /set\\_confluence \\<number\\>", parse_mode='MarkdownV2')
                return
            
            try:
                threshold = int(context.args[0])
                if threshold < 1:
                    await update.message.reply_text("❌ Confluence threshold must be at least 1")
                    return
                
                self.vault_data.confluence_threshold = threshold
                escaped_threshold = escape_markdown_v2(str(threshold))
                message = f"✅ Confluence threshold set to: *{escaped_threshold}* vault\\(s\\)"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Confluence threshold set to: {threshold}")
            except ValueError:
                await update.message.reply_text("❌ Please provide a valid number")
        except Exception as e:
            logger.error(f"Error in set_confluence command: {e}")
            await update.message.reply_text("Error setting confluence threshold.")
    
    async def set_window_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_window command"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide minutes: /set\\_window \\<minutes\\>", parse_mode='MarkdownV2')
                return
            
            try:
                minutes = int(context.args[0])
                if minutes < 1:
                    await update.message.reply_text("❌ Time window must be at least 1 minute")
                    return
                
                self.vault_data.confluence_window_minutes = minutes
                escaped_minutes = escape_markdown_v2(str(minutes))
                message = f"✅ Confluence window set to: *{escaped_minutes}* minute\\(s\\)"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Confluence window set to: {minutes} minutes")
            except ValueError:
                await update.message.reply_text("❌ Please provide a valid number")
        except Exception as e:
            logger.error(f"Error in set_window command: {e}")
            await update.message.reply_text("Error setting confluence window.")
    
    async def show_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /show_settings command"""
        try:
            status_icon = "🟢" if self.vault_data.is_monitoring else "🔴"
            status_text = "Active" if self.vault_data.is_monitoring else "Stopped"
            
            confluence_threshold = escape_markdown_v2(str(self.vault_data.confluence_threshold))
            confluence_window = escape_markdown_v2(str(self.vault_data.confluence_window_minutes))
            cooldown = escape_markdown_v2(str(self.vault_data.cooldown_minutes))
            vault_count = escape_markdown_v2(str(len(self.vault_data.vaults)))
            
            message = (
                f"⚙️ *Bot Settings*\n\n"
                f"*Status:* {status_icon} {status_text}\n"
                f"*Monitored Vaults:* {vault_count}\n\n"
                f"*Detection Settings:*\n"
                f"• Confluence Threshold: {confluence_threshold} vault\\(s\\)\n"
                f"• Confluence Window: {confluence_window} minute\\(s\\)\n"
                f"• Anti\\-spam Cooldown: {cooldown} minute\\(s\\)\n\n"
                f"*Monitoring:*\n"
                f"• Check Interval: 90 seconds\n"
                f"• Vault Delay: 10 seconds\n"
                f"• Tracks: Position SIZE changes"
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in show_settings command: {e}")
            message = (
                f"Bot Settings:\n"
                f"Status: {'Active' if self.vault_data.is_monitoring else 'Stopped'}\n"
                f"Vaults: {len(self.vault_data.vaults)}\n"
                f"Confluence: {self.vault_data.confluence_threshold} vaults\n"
                f"Window: {self.vault_data.confluence_window_minutes} minutes\n"
                f"Cooldown: {self.vault_data.cooldown_minutes} minutes"
            )
            await update.message.reply_text(message)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        await self.show_settings_command(update, context)
    
    async def get_vault_positions(self, vault_info: VaultInfo) -> Dict[str, PositionData]:
        """Get current positions for a vault (tracking SIZE not value)"""
        try:
            positions = {}
            
            # Get user state for the vault address
            user_state = self.info.user_state(vault_info.address)
            
            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    pos_data = position['position']
                    size_str = pos_data.get('szi', '0')
                    
                    if size_str and size_str != '0':
                        coin = pos_data['coin']
                        size = abs(Decimal(size_str))  # Use absolute value of size
                        
                        positions[coin] = PositionData(
                            coin=coin,
                            size=size,
                            timestamp=datetime.now()
                        )
            
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions for {vault_info.name}: {e}")
            return {}
    
    async def check_vault_changes(self, vault_info: VaultInfo):
        """Check for position SIZE changes for a specific vault"""
        try:
            current_positions = await self.get_vault_positions(vault_info)
            previous_positions = self.vault_data.previous_positions.get(vault_info.address, {})
            
            # Check for size changes in existing positions
            all_coins = set(current_positions.keys()) | set(previous_positions.keys())
            
            for coin in all_coins:
                current_pos = current_positions.get(coin)
                previous_pos = previous_positions.get(coin)
                
                current_size = current_pos.size if current_pos else Decimal('0')
                previous_size = previous_pos.size if previous_pos else Decimal('0')
                
                # Check if position size changed
                if current_size != previous_size:
                    # Check cooldown
                    if self.vault_data.is_cooldown_active(vault_info.address, coin):
                        logger.info(f"Skipping alert for {coin} on {vault_info.name} - cooldown active")
                        continue
                    
                    # Create trade event
                    trade_event = TradeEvent(
                        vault_name=vault_info.name,
                        vault_address=vault_info.address,
                        coin=coin,
                        old_size=previous_size,
                        new_size=current_size,
                        timestamp=datetime.now()
                    )
                    
                    # Add to trade events for confluence tracking
                    self.vault_data.add_trade_event(trade_event)
                    
                    # Check confluence
                    confluence_events = self.vault_data.get_confluence_events(coin, trade_event.timestamp)
                    unique_vaults = len(set(e.vault_name for e in confluence_events))
                    
                    # Only alert if confluence threshold is met
                    if unique_vaults >= self.vault_data.confluence_threshold:
                        await self.send_confluence_alert(trade_event, confluence_events)
                        
                        # Set cooldown for all involved vaults
                        for event in confluence_events:
                            vault = self.vault_data.get_vault_by_name(event.vault_name)
                            if vault:
                                self.vault_data.set_cooldown(vault.address, coin)
            
            # Update previous positions
            self.vault_data.previous_positions[vault_info.address] = current_positions.copy()
            
        except Exception as e:
            logger.error(f"Error checking changes for vault {vault_info.name}: {e}")
    
    async def send_confluence_alert(self, trigger_event: TradeEvent, all_events: List[TradeEvent]):
        """Send confluence alert when multiple vaults trade the same token"""
        try:
            # Get unique vaults involved
            unique_vaults = list(set(e.vault_name for e in all_events))
            confluence_count = len(unique_vaults)
            
            # Determine alert emoji based on trade type
            if trigger_event.trade_type == "OPEN":
                emoji = "🟢"
            elif trigger_event.trade_type == "CLOSE":
                emoji = "🔴"
            elif trigger_event.trade_type == "INCREASE":
                emoji = "📈"
            else:  # DECREASE
                emoji = "📉"
            
            # Escape values for MarkdownV2
            escaped_coin = escape_markdown_v2(trigger_event.coin)
            escaped_count = escape_markdown_v2(str(confluence_count))
            escaped_window = escape_markdown_v2(str(self.vault_data.confluence_window_minutes))
            escaped_trigger_vault = escape_markdown_v2(trigger_event.vault_name)
            escaped_old_size = escape_markdown_v2(f"{trigger_event.old_size}")
            escaped_new_size = escape_markdown_v2(f"{trigger_event.new_size}")
            escaped_trade_type = escape_markdown_v2(trigger_event.trade_type)
            escaped_time = escape_markdown_v2(datetime.now().strftime('%H:%M:%S'))
            
            # Build vault list
            vault_list = ""
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                escaped_vault = escape_markdown_v2(vault_name)
                vault_list += f"{i}\\. {escaped_vault}\n"
            
            message = (
                f"{emoji} *CONFLUENCE DETECTED*\n\n"
                f"*Token:* {escaped_coin}\n"
                f"*Vaults Trading:* {escaped_count}/{escaped_window}min\n\n"
                f"*Trigger Event:*\n"
                f"• Vault: {escaped_trigger_vault}\n"
                f"• Action: {escaped_trade_type}\n"
                f"• Size: {escaped_old_size} → {escaped_new_size}\n\n"
                f"*All Vaults:*\n{vault_list}\n"
                f"*Time:* {escaped_time}"
            )
            
            await self.send_alert(message)
            
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")
            # Simple fallback
            try:
                simple_message = (
                    f"🚨 CONFLUENCE: {trigger_event.coin}\n"
                    f"Vaults: {len(set(e.vault_name for e in all_events))}\n"
                    f"Trigger: {trigger_event.vault_name} - {trigger_event.trade_type}\n"
                    f"Size: {trigger_event.old_size} → {trigger_event.new_size}"
                )
                await self.send_alert(simple_message)
            except Exception as e2:
                logger.error(f"Error sending fallback alert: {e2}")
    
    async def send_alert(self, message: str):
        """Send alert message to Telegram"""
        try:
            bot = Bot(token=self.bot_token)
            await bot.send_message(chat_id=self.chat_id, text=message, parse_mode='MarkdownV2')
            logger.info(f"Alert sent: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending alert with MarkdownV2: {e}")
            # Fallback to plain text
            try:
                plain_message = message.replace('*', '').replace('`', '').replace('\\', '')
                bot = Bot(token=self.bot_token)
                await bot.send_message(chat_id=self.chat_id, text=plain_message)
                logger.info("Alert sent as plain text fallback")
            except Exception as e2:
                logger.error(f"Error sending plain text fallback: {e2}")
    
    async def monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("Starting advanced vault monitoring loop...")
        
        while self.vault_data.is_monitoring:
            try:
                vaults = self.vault_data.get_vault_list()
                if not vaults:
                    logger.info("No vaults to monitor, waiting...")
                    await asyncio.sleep(90)
                    continue
                
                logger.info(f"Checking {len(vaults)} vault(s) for position size changes...")
                
                # Check each vault with 10-second delay between them
                for i, vault_info in enumerate(vaults):
                    if not self.vault_data.is_monitoring:
                        break
                    
                    logger.info(f"Checking vault {i+1}/{len(vaults)}: {vault_info.name}")
                    await self.check_vault_changes(vault_info)
                    
                    # Add delay between vaults (except for the last one)
                    if i < len(vaults) - 1:
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
            try:
                vault_count = escape_markdown_v2(str(len(self.vault_data.vaults)))
                confluence_threshold = escape_markdown_v2(str(self.vault_data.confluence_threshold))
                confluence_window = escape_markdown_v2(str(self.vault_data.confluence_window_minutes))
                start_time = escape_markdown_v2(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                
                startup_message = (
                    f"🚀 *Advanced Monitoring Started*\n\n"
                    f"*Configuration:*\n"
                    f"• Vaults: {vault_count}\n"
                    f"• Confluence: {confluence_threshold} vault\\(s\\)\n"
                    f"• Window: {confluence_window} minute\\(s\\)\n"
                    f"• Tracking: Position SIZE changes\n"
                    f"• Anti\\-spam: 5min cooldowns\n\n"
                    f"*Started:* {start_time}"
                )
                await self.send_alert(startup_message)
            except Exception as e:
                logger.error(f"Error sending startup message: {e}")
                await self.send_alert("🚀 Advanced vault monitoring started!")
    
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
    vault_bot = HyperliquidAdvancedBot(telegram_bot_token, chat_id)
    
    # Create Telegram application
    application = Application.builder().token(telegram_bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", vault_bot.start_command))
    application.add_handler(CommandHandler("add_vault", vault_bot.add_vault_command))
    application.add_handler(CommandHandler("list_vaults", vault_bot.list_vaults_command))
    application.add_handler(CommandHandler("remove_vault", vault_bot.remove_vault_command))
    application.add_handler(CommandHandler("status", vault_bot.status_command))
    application.add_handler(CommandHandler("set_confluence", vault_bot.set_confluence_command))
    application.add_handler(CommandHandler("set_window", vault_bot.set_window_command))
    application.add_handler(CommandHandler("show_settings", vault_bot.show_settings_command))
    
    logger.info("Starting Advanced Hyperliquid Telegram bot...")
    
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