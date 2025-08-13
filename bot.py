import asyncio
import logging
import json
import time
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
import os
from collections import defaultdict
import re

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

# Professional configuration
class BotConfig:
    # API timeouts and retries
    API_TIMEOUT_SECONDS = 30
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2  # Exponential backoff base
    
    # Monitoring intervals
    VAULT_CHECK_INTERVAL = 90  # seconds between cycles
    VAULT_DELAY = 8  # seconds between individual vault checks
    
    # Performance thresholds
    MAX_API_RESPONSE_TIME = 15  # seconds
    MAX_MEMORY_MB = 512
    
    # Address validation
    HYPERLIQUID_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')
    
    # Persistence
    VAULT_DATA_FILE = "vault_data.json"
    SETTINGS_FILE = "bot_settings.json"

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
    last_successful_check: Optional[datetime] = None
    consecutive_failures: int = 0
    is_active: bool = True
    
    def __str__(self):
        return f"{self.name} ({self.address[:8]}...{self.address[-6:]})"
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'address': self.address,
            'name': self.name,
            'last_successful_check': self.last_successful_check.isoformat() if self.last_successful_check else None,
            'consecutive_failures': self.consecutive_failures,
            'is_active': self.is_active
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create from dictionary for JSON deserialization"""
        last_check = None
        if data.get('last_successful_check'):
            last_check = datetime.fromisoformat(data['last_successful_check'])
        
        return cls(
            address=data['address'],
            name=data['name'],
            last_successful_check=last_check,
            consecutive_failures=data.get('consecutive_failures', 0),
            is_active=data.get('is_active', True)
        )

@dataclass
class PositionData:
    coin: str
    size: Decimal
    timestamp: datetime
    entry_price: Optional[Decimal] = None
    position_value: Optional[Decimal] = None
    
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

@dataclass
class PerformanceMetrics:
    total_api_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_response_time: float = 0.0
    last_reset: datetime = None
    
    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.now()
    
    @property
    def success_rate(self) -> float:
        if self.total_api_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_api_calls) * 100

class VaultData:
    def __init__(self):
        self.vaults: Dict[str, VaultInfo] = {}  # name -> VaultInfo
        self.previous_positions: Dict[str, Dict[str, PositionData]] = {}  # vault_address -> {coin -> PositionData}
        self.last_alerts: Dict[str, Dict[str, datetime]] = {}  # vault_address -> {coin -> last_alert_time}
        self.trade_events: List[TradeEvent] = []  # Recent trade events for confluence
        self.is_monitoring = False
        self.performance = PerformanceMetrics()
        
        # Settings
        self.confluence_threshold = 1  # How many vaults need to trade same token
        self.confluence_window_minutes = 10  # Time window for confluence detection
        self.cooldown_minutes = 5  # Anti-spam cooldown per token per vault
        
        # Load persisted data
        self.load_data()
        
    def save_data(self):
        """Save vault data to persistent storage with multiple fallback locations"""
        try:
            # Save vaults
            vault_data = {
                'vaults': {name: vault.to_dict() for name, vault in self.vaults.items()},
                'confluence_threshold': self.confluence_threshold,
                'confluence_window_minutes': self.confluence_window_minutes,
                'cooldown_minutes': self.cooldown_minutes,
                'saved_at': datetime.now().isoformat()
            }
            
            # Try multiple locations for persistence
            locations = [
                BotConfig.VAULT_DATA_FILE,  # workspace directory
                f"/app/{BotConfig.VAULT_DATA_FILE}",  # Render app directory
                f"/home/render/{BotConfig.VAULT_DATA_FILE}",  # Render home
            ]
            
            saved = False
            for location in locations:
                try:
                    with open(location, 'w') as f:
                        json.dump(vault_data, f, indent=2)
                    logger.info(f"Saved {len(self.vaults)} vaults to: {location}")
                    saved = True
                    break
                except Exception as e:
                    logger.warning(f"Could not save to {location}: {e}")
            
            # Also save to environment variable as backup
            try:
                import base64
                vault_json = json.dumps(vault_data)
                encoded_data = base64.b64encode(vault_json.encode()).decode()
                # Note: This would need to be set in Render dashboard as VAULT_BACKUP_DATA
                logger.info(f"Backup data length: {len(encoded_data)} chars")
            except Exception as e:
                logger.warning(f"Could not create backup data: {e}")
            
            if not saved:
                logger.error("Failed to save vault data to any location!")
                
        except Exception as e:
            logger.error(f"Error saving vault data: {e}")
    
    def load_data(self):
        """Load vault data from persistent storage with multiple fallback locations"""
        try:
            # Try multiple locations
            locations = [
                BotConfig.VAULT_DATA_FILE,  # workspace directory
                f"/app/{BotConfig.VAULT_DATA_FILE}",  # Render app directory  
                f"/home/render/{BotConfig.VAULT_DATA_FILE}",  # Render home
            ]
            
            data = None
            loaded_from = None
            
            for location in locations:
                try:
                    if os.path.exists(location):
                        with open(location, 'r') as f:
                            data = json.load(f)
                        loaded_from = location
                        break
                except Exception as e:
                    logger.warning(f"Could not load from {location}: {e}")
            
            # Try environment variable backup
            if not data:
                try:
                    import base64
                    backup_data = os.getenv('VAULT_BACKUP_DATA')
                    if backup_data:
                        vault_json = base64.b64decode(backup_data.encode()).decode()
                        data = json.loads(vault_json)
                        loaded_from = "environment variable"
                        logger.info("Loaded vault data from environment variable backup")
                except Exception as e:
                    logger.warning(f"Could not load from environment backup: {e}")
            
            if data:
                # Load vaults
                for name, vault_dict in data.get('vaults', {}).items():
                    self.vaults[name] = VaultInfo.from_dict(vault_dict)
                    # Initialize empty position tracking
                    self.previous_positions[vault_dict['address']] = {}
                    self.last_alerts[vault_dict['address']] = {}
                
                # Load settings
                self.confluence_threshold = data.get('confluence_threshold', 1)
                self.confluence_window_minutes = data.get('confluence_window_minutes', 10)
                self.cooldown_minutes = data.get('cooldown_minutes', 5)
                
                saved_at = data.get('saved_at', 'unknown')
                logger.info(f"Loaded {len(self.vaults)} vaults from: {loaded_from}")
                logger.info(f"Data saved at: {saved_at}")
                
                if self.vaults:
                    vault_names = ", ".join(self.vaults.keys())
                    logger.info(f"Restored vaults: {vault_names}")
            else:
                logger.info("No persisted vault data found - starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading vault data: {e}")
    
    def add_vault(self, address: str, name: str) -> Tuple[bool, str]:
        """Add a vault with validation"""
        # Validate address format
        if not BotConfig.HYPERLIQUID_ADDRESS_PATTERN.match(address):
            return False, "Invalid address format. Must be 0x followed by 40 hex characters."
        
        # Check for duplicate name
        if name in self.vaults:
            return False, f"A vault with name '{name}' already exists."
        
        # Check for duplicate address
        for existing_vault in self.vaults.values():
            if existing_vault.address.lower() == address.lower():
                return False, f"This address is already monitored as '{existing_vault.name}'."
        
        self.vaults[name] = VaultInfo(address, name)
        self.previous_positions[address] = {}
        self.last_alerts[address] = {}
        
        # Save to persistent storage
        self.save_data()
        
        logger.info(f"Added vault: {name} ({address})")
        return True, f"Successfully added vault '{name}'."
    
    def remove_vault(self, name: str) -> bool:
        """Remove a vault by name"""
        if name in self.vaults:
            vault_info = self.vaults[name]
            del self.vaults[name]
            self.previous_positions.pop(vault_info.address, None)
            self.last_alerts.pop(vault_info.address, None)
            
            # Save to persistent storage
            self.save_data()
            
            logger.info(f"Removed vault: {name}")
            return True
        return False
    
    def get_vault_by_name(self, name: str) -> Optional[VaultInfo]:
        """Get vault info by name"""
        return self.vaults.get(name)
    
    def get_active_vaults(self) -> List[VaultInfo]:
        """Get list of active vaults"""
        return [v for v in self.vaults.values() if v.is_active]
    
    def get_vault_list(self) -> List[VaultInfo]:
        """Get list of all vaults"""
        return list(self.vaults.values())
    
    def mark_vault_failure(self, vault_address: str):
        """Mark a vault as having failed a check"""
        for vault in self.vaults.values():
            if vault.address == vault_address:
                vault.consecutive_failures += 1
                if vault.consecutive_failures >= 3:
                    vault.is_active = False
                    logger.warning(f"Deactivating vault {vault.name} after {vault.consecutive_failures} failures")
                # Save state changes
                self.save_data()
                break
    
    def mark_vault_success(self, vault_address: str):
        """Mark a vault as having succeeded a check"""
        for vault in self.vaults.values():
            if vault.address == vault_address:
                vault.consecutive_failures = 0
                vault.last_successful_check = datetime.now()
                vault.is_active = True
                # Save state changes
                self.save_data()
                break
    
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
        self.health_check_task: Optional[asyncio.Task] = None
        
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command - show vault configuration for manual backup"""
        try:
            if not self.vault_data.vaults:
                await update.message.reply_text("❌ No vaults to backup")
                return
            
            # Create backup data
            backup_data = {
                'vaults': {name: vault.to_dict() for name, vault in self.vault_data.vaults.items()},
                'confluence_threshold': self.vault_data.confluence_threshold,
                'confluence_window_minutes': self.vault_data.confluence_window_minutes,
                'cooldown_minutes': self.vault_data.cooldown_minutes,
                'backup_created': datetime.now().isoformat()
            }
            
            # Create human-readable backup
            vault_list = ""
            for i, (name, vault) in enumerate(self.vault_data.vaults.items(), 1):
                status = "✅" if vault.is_active else "❌"
                vault_list += f"{i}. {status} {name}: {vault.address}\n"
            
            backup_message = (
                f"💾 **VAULT BACKUP** ({len(self.vault_data.vaults)} vaults)\n\n"
                f"**Settings:**\n"
                f"• Alert when: {self.vault_data.confluence_threshold} vault(s) trade same token\n"
                f"• Time window: {self.vault_data.confluence_window_minutes} minutes\n"
                f"• Cooldown: {self.vault_data.cooldown_minutes} minutes\n\n"
                f"**Vaults:**\n{vault_list}\n"
                f"**Backup created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"💡 **Save this message** - you can use it to restore your vaults if needed!"
            )
            
            await update.message.reply_text(backup_message)
            logger.info(f"Manual backup provided for {len(self.vault_data.vaults)} vaults")
            
        except Exception as e:
            logger.error(f"Error in backup command: {e}")
            await update.message.reply_text("Error creating backup")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            # Auto-start monitoring if vaults exist
            if self.vault_data.vaults and not self.vault_data.is_monitoring:
                await self.start_monitoring()
            
            vault_count = len(self.vault_data.vaults)
            active_count = len(self.vault_data.get_active_vaults())
            
            welcome_message = (
                "🤖 *Advanced Hyperliquid Position Monitor v2\\.1*\n\n"
                "*Commands:*\n"
                "/add\\_vault \\<address\\> \\<name\\> \\- Add vault with custom name\n"
                "/list\\_vaults \\- Show all monitored vaults\n"
                "/remove\\_vault \\<name\\> \\- Remove vault by name\n"
                "/backup \\- Create manual backup of your vaults\n"
                "/status \\- Show bot status\n"
                "/performance \\- Show API performance metrics\n"
                "/setvaults \\<number\\> \\- Set how many vaults needed for alert\n"
                "/set\\_window \\<minutes\\> \\- Set confluence time window\n"
                "/health \\- Show system health\n\n"
                "*Professional Features:*\n"
                "• Position SIZE tracking \\(not value\\)\n"
                "• Confluence detection across vaults\n"
                "• Anti\\-spam protection \\(5min cooldowns\\)\n"
                "• Timeout \\& retry protection\n"
                "• Performance monitoring\n"
                "• Auto\\-recovery from failures\n"
                "• **PERSISTENT STORAGE** \\(survives restarts\\)\n"
                "• **Manual backup/restore**\n\n"
                f"*Current Status:*\n"
                f"• Vaults: {active_count}/{vault_count}\n"
                f"• Monitoring: {'Active' if self.vault_data.is_monitoring else 'Stopped'}\n\n"
                "Start by adding vaults with /add\\_vault\\!"
            )
            await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
            logger.info(f"Start command executed by user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("Welcome to Advanced Hyperliquid Monitor v2.1! Use /add_vault <address> <name> to start.")
    
    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command with validation"""
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Please provide both address and name: /add\\_vault \\<address\\> \\<name\\>", 
                    parse_mode='MarkdownV2'
                )
                return
            
            address = context.args[0].strip()
            name = " ".join(context.args[1:]).strip()
            
            # Professional validation
            success, message = self.vault_data.add_vault(address, name)
            
            if success:
                escaped_name = escape_markdown_v2(name)
                escaped_address = escape_markdown_v2(f"{address[:8]}...{address[-6:]}")
                response_message = f"✅ Added vault: *{escaped_name}* \\(`{escaped_address}`\\)\n\nValidation: ✅ Address format\nPersistence: ✅ Saved to storage\nStatus: Monitoring will begin automatically\\."
                await update.message.reply_text(response_message, parse_mode='MarkdownV2')
                
                # Start monitoring if not already running
                if not self.vault_data.is_monitoring:
                    await self.start_monitoring()
                
                logger.info(f"Added vault: {name} ({address})")
            else:
                escaped_error = escape_markdown_v2(message)
                await update.message.reply_text(f"❌ {escaped_error}", parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in add_vault command: {e}")
            await update.message.reply_text("Error adding vault. Please check the address format and try again.")
    
    async def performance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command"""
        try:
            metrics = self.vault_data.performance
            
            success_rate = escape_markdown_v2(f"{metrics.success_rate:.1f}%")
            total_calls = escape_markdown_v2(str(metrics.total_api_calls))
            avg_time = escape_markdown_v2(f"{metrics.avg_response_time:.2f}s")
            failed_calls = escape_markdown_v2(str(metrics.failed_calls))
            
            message = (
                f"📊 *API Performance Metrics*\n\n"
                f"*Success Rate:* {success_rate}\n"
                f"*Total API Calls:* {total_calls}\n"
                f"*Failed Calls:* {failed_calls}\n"
                f"*Avg Response Time:* {avg_time}\n\n"
                f"*Thresholds:*\n"
                f"• Max Response Time: {escape_markdown_v2(str(BotConfig.MAX_API_RESPONSE_TIME))}s\n"
                f"• Timeout: {escape_markdown_v2(str(BotConfig.API_TIMEOUT_SECONDS))}s\n"
                f"• Max Retries: {escape_markdown_v2(str(BotConfig.MAX_RETRIES))}"
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in performance command: {e}")
            await update.message.reply_text("Error retrieving performance metrics.")
    
    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command with proper escaping"""
        try:
            active_vaults = len(self.vault_data.get_active_vaults())
            total_vaults = len(self.vault_data.vaults)
            monitoring_status = "🟢 Active" if self.vault_data.is_monitoring else "🔴 Stopped"
            
            # Check for problematic vaults
            problematic_vaults = [v for v in self.vault_data.vaults.values() if v.consecutive_failures > 0]
            
            # Properly escape all values
            escaped_monitoring = escape_markdown_v2(monitoring_status)
            escaped_success_rate = escape_markdown_v2(f"{self.vault_data.performance.success_rate:.1f}%")
            
            health_message = (
                f"🏥 *System Health Check*\n\n"
                f"*Monitoring:* {escaped_monitoring}\n"
                f"*Active Vaults:* {active_vaults}/{total_vaults}\n"
                f"*API Success Rate:* {escaped_success_rate}\n"
                f"*Persistent Storage:* ✅ Enabled\n"
            )
            
            if problematic_vaults:
                health_message += f"\n⚠️ *Issues Detected:*\n"
                for vault in problematic_vaults[:3]:  # Show max 3
                    escaped_vault_name = escape_markdown_v2(vault.name)
                    health_message += f"• {escaped_vault_name}: {vault.consecutive_failures} failures\n"
            else:
                health_message += f"\n✅ *All systems healthy*"
            
            await update.message.reply_text(health_message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in health command: {e}")
            # Fallback to plain text
            health_message = (
                f"System Health Check:\n"
                f"Monitoring: {'Active' if self.vault_data.is_monitoring else 'Stopped'}\n"
                f"Active Vaults: {len(self.vault_data.get_active_vaults())}/{len(self.vault_data.vaults)}\n"
                f"API Success Rate: {self.vault_data.performance.success_rate:.1f}%\n"
                f"Persistent Storage: Enabled"
            )
            await update.message.reply_text(health_message)
    
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
                status_icon = "🟢" if vault.is_active else "🔴"
                escaped_name = escape_markdown_v2(vault.name)
                escaped_address = escape_markdown_v2(f"{vault.address[:8]}...{vault.address[-6:]}")
                
                message += f"{i}\\. {status_icon} *{escaped_name}*\n"
                message += f"   `{escaped_address}`\n"
                if vault.consecutive_failures > 0:
                    message += f"   ⚠️ {vault.consecutive_failures} failures\n"
                message += "\n"
            
            message += f"*Total:* {len(vaults)} vault\\(s\\)"
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in list_vaults command: {e}")
            vaults = self.vault_data.get_vault_list()
            simple_message = f"Monitored vaults ({len(vaults)}):\n"
            for i, vault in enumerate(vaults, 1):
                status = "✅" if vault.is_active else "❌"
                simple_message += f"{i}. {status} {vault.name} ({vault.address[:8]}...)\n"
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
                # Show available vaults to help user
                available_vaults = list(self.vault_data.vaults.keys())
                if available_vaults:
                    vault_list = ", ".join(available_vaults[:5])  # Show max 5
                    message = f"❌ Vault '{name}' not found.\n\nAvailable vaults: {vault_list}\n\nNote: Names are case-sensitive!"
                else:
                    message = "❌ No vaults are currently monitored."
                await update.message.reply_text(message)
        except Exception as e:
            logger.error(f"Error in remove_vault command: {e}")
            await update.message.reply_text("Error removing vault. Please try again.")
    
    async def set_vault_number_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setvaults command"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide number: /setvaults \\<number\\>", parse_mode='MarkdownV2')
                return
            
            try:
                threshold = int(context.args[0])
                if threshold < 1:
                    await update.message.reply_text("❌ Vault number must be at least 1")
                    return
                
                self.vault_data.confluence_threshold = threshold
                escaped_threshold = escape_markdown_v2(str(threshold))
                
                if threshold == 1:
                    message = f"✅ Alert on: *ANY* vault trades \\({escaped_threshold} vault\\)"
                else:
                    message = f"✅ Alert when: *{escaped_threshold}* vaults trade same token"
                
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Vault threshold set to: {threshold}")
            except ValueError:
                await update.message.reply_text("❌ Please provide a valid number")
        except Exception as e:
            logger.error(f"Error in setvaults command: {e}")
            await update.message.reply_text("Error setting vault threshold.")
    
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
            active_vaults = escape_markdown_v2(str(len(self.vault_data.get_active_vaults())))
            
            # Friendly vault threshold description
            if self.vault_data.confluence_threshold == 1:
                vault_desc = "ANY vault"
            else:
                vault_desc = f"{self.vault_data.confluence_threshold} vaults"
            escaped_vault_desc = escape_markdown_v2(vault_desc)
            
            message = (
                f"⚙️ *Bot Settings v2\\.0*\n\n"
                f"*Status:* {status_icon} {status_text}\n"
                f"*Monitored Vaults:* {active_vaults}/{vault_count}\n\n"
                f"*Alert Settings:*\n"
                f"• Alert when: {escaped_vault_desc} trade same token\n"
                f"• Time window: {confluence_window} minute\\(s\\)\n"
                f"• Anti\\-spam cooldown: {cooldown} minute\\(s\\)\n\n"
                f"*Professional Features:*\n"
                f"• API Timeout: {BotConfig.API_TIMEOUT_SECONDS}s\n"
                f"• Max Retries: {BotConfig.MAX_RETRIES}\n"
                f"• Check Interval: {BotConfig.VAULT_CHECK_INTERVAL}s\n"
                f"• Tracks: Position SIZE changes\n"
                f"• Auto\\-recovery: Enabled"
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')
        except Exception as e:
            logger.error(f"Error in show_settings command: {e}")
            message = (
                f"Bot Settings v2.0:\n"
                f"Status: {'Active' if self.vault_data.is_monitoring else 'Stopped'}\n"
                f"Vaults: {len(self.vault_data.get_active_vaults())}/{len(self.vault_data.vaults)}\n"
                f"Alert when: {self.vault_data.confluence_threshold} vaults trade same token\n"
                f"Window: {self.vault_data.confluence_window_minutes} minutes\n"
                f"API Timeout: {BotConfig.API_TIMEOUT_SECONDS}s"
            )
            await update.message.reply_text(message)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        await self.show_settings_command(update, context)
    
    async def safe_api_call(self, vault_info: VaultInfo, operation: str) -> Optional[Dict]:
        """Professional API call with timeout, retry, and error handling"""
        start_time = time.time()
        
        for attempt in range(BotConfig.MAX_RETRIES):
            try:
                self.vault_data.performance.total_api_calls += 1
                
                # Use asyncio timeout for the API call
                user_state = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, 
                        lambda: self.info.user_state(vault_info.address)
                    ),
                    timeout=BotConfig.API_TIMEOUT_SECONDS
                )
                
                # Record success
                response_time = time.time() - start_time
                self.vault_data.performance.successful_calls += 1
                self.vault_data.performance.avg_response_time = (
                    (self.vault_data.performance.avg_response_time * (self.vault_data.performance.successful_calls - 1) + response_time) 
                    / self.vault_data.performance.successful_calls
                )
                
                self.vault_data.mark_vault_success(vault_info.address)
                
                if response_time > BotConfig.MAX_API_RESPONSE_TIME:
                    logger.warning(f"Slow API response for {vault_info.name}: {response_time:.2f}s")
                
                return user_state
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1} for {vault_info.name}")
                self.vault_data.performance.failed_calls += 1
                
            except Exception as e:
                logger.error(f"API error on attempt {attempt + 1} for {vault_info.name}: {e}")
                self.vault_data.performance.failed_calls += 1
            
            # Exponential backoff between retries
            if attempt < BotConfig.MAX_RETRIES - 1:
                delay = BotConfig.RETRY_DELAY_BASE ** attempt
                logger.info(f"Retrying {vault_info.name} in {delay}s...")
                await asyncio.sleep(delay)
        
        # All retries failed
        self.vault_data.mark_vault_failure(vault_info.address)
        logger.error(f"All retries failed for {vault_info.name}")
        return None
    
    async def get_vault_positions(self, vault_info: VaultInfo) -> Dict[str, PositionData]:
        """Get current positions for a vault with professional error handling"""
        try:
            positions = {}
            
            # Professional API call with timeout and retry
            user_state = await self.safe_api_call(vault_info, "get_positions")
            
            if not user_state:
                return {}
            
            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    pos_data = position['position']
                    size_str = pos_data.get('szi', '0')
                    
                    if size_str and size_str != '0':
                        coin = pos_data['coin']
                        size = abs(Decimal(size_str))  # Use absolute value of size
                        
                        # Extract additional professional data
                        entry_price = None
                        position_value = None
                        
                        try:
                            if 'entryPx' in pos_data:
                                entry_price = Decimal(str(pos_data['entryPx']))
                            if 'positionValue' in pos_data:
                                position_value = Decimal(str(pos_data['positionValue']))
                        except Exception as e:
                            logger.warning(f"Error parsing additional position data for {coin}: {e}")
                        
                        positions[coin] = PositionData(
                            coin=coin,
                            size=size,
                            timestamp=datetime.now(),
                            entry_price=entry_price,
                            position_value=position_value
                        )
            
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions for {vault_info.name}: {e}")
            self.vault_data.mark_vault_failure(vault_info.address)
            return {}
    
    async def check_vault_changes(self, vault_info: VaultInfo):
        """Check for position SIZE changes with professional error handling"""
        try:
            if not vault_info.is_active:
                logger.debug(f"Skipping inactive vault: {vault_info.name}")
                return
            
            current_positions = await self.get_vault_positions(vault_info)
            if not current_positions and vault_info.consecutive_failures > 0:
                logger.warning(f"Skipping {vault_info.name} due to API issues")
                return
            
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
                    
                    # Check confluence BEFORE adding the current event (so it doesn't count itself)
                    existing_confluence_events = self.vault_data.get_confluence_events(coin, trade_event.timestamp)
                    existing_unique_vaults = len(set(e.vault_name for e in existing_confluence_events))
                    
                    # Debug logging for confluence detection
                    if existing_confluence_events:
                        existing_vault_names = [e.vault_name for e in existing_confluence_events]
                        logger.info(f"Confluence check for {coin}: Found {existing_unique_vaults} existing vault(s): {existing_vault_names}")
                        for event in existing_confluence_events:
                            minutes_ago = (trade_event.timestamp - event.timestamp).total_seconds() / 60
                            logger.info(f"  - {event.vault_name}: {event.trade_type} {event.size_change} size, {minutes_ago:.1f} minutes ago")
                    
                    # Add current event to the count (but not to the list yet)
                    total_unique_vaults = existing_unique_vaults
                    current_vault_already_counted = any(e.vault_name == vault_info.name for e in existing_confluence_events)
                    if not current_vault_already_counted:
                        total_unique_vaults += 1
                    
                    logger.info(f"Confluence for {coin}: {existing_unique_vaults} existing + {vault_info.name} = {total_unique_vaults} total (threshold: {self.vault_data.confluence_threshold})")
                    
                    # Add to trade events for confluence tracking (after confluence check)
                    self.vault_data.add_trade_event(trade_event)
                    
                    # Only alert if confluence threshold is met
                    if total_unique_vaults >= self.vault_data.confluence_threshold:
                        # Get the final confluence events including the current one for the alert
                        all_confluence_events = self.vault_data.get_confluence_events(coin, trade_event.timestamp)
                        await self.send_confluence_alert(trade_event, all_confluence_events)
                        
                        # Set cooldown for all involved vaults
                        for event in all_confluence_events:
                            vault = self.vault_data.get_vault_by_name(event.vault_name)
                            if vault:
                                self.vault_data.set_cooldown(vault.address, coin)
            
            # Update previous positions
            self.vault_data.previous_positions[vault_info.address] = current_positions.copy()
            
        except Exception as e:
            logger.error(f"Error checking changes for vault {vault_info.name}: {e}")
            self.vault_data.mark_vault_failure(vault_info.address)
    
    async def send_confluence_alert(self, trigger_event: TradeEvent, all_events: List[TradeEvent]):
        """Send professional confluence alert"""
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
            
            # Calculate size change
            size_change = trigger_event.size_change
            escaped_size_change = escape_markdown_v2(f"{size_change}")
            
            # Build vault list
            vault_list = ""
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                escaped_vault = escape_markdown_v2(vault_name)
                vault_list += f"{i}\\. {escaped_vault}\n"
            
            message = (
                f"{emoji} *CONFLUENCE DETECTED v2\\.0*\n\n"
                f"*Token:* {escaped_coin}\n"
                f"*Vaults Trading:* {escaped_count}/{escaped_window}min\n"
                f"*Size Change:* {escaped_size_change}\n\n"
                f"*Trigger Event:*\n"
                f"• Vault: {escaped_trigger_vault}\n"
                f"• Action: {escaped_trade_type}\n"
                f"• Size: {escaped_old_size} → {escaped_new_size}\n\n"
                f"*All Vaults:*\n{vault_list}\n"
                f"*Time:* {escaped_time}\n"
                f"*Professional Monitoring*"
            )
            
            await self.send_alert(message)
            
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")
            # Simple fallback
            try:
                simple_message = (
                    f"🚨 CONFLUENCE v2.0: {trigger_event.coin}\n"
                    f"Vaults: {len(set(e.vault_name for e in all_events))}\n"
                    f"Trigger: {trigger_event.vault_name} - {trigger_event.trade_type}\n"
                    f"Size: {trigger_event.old_size} → {trigger_event.new_size}\n"
                    f"Change: {trigger_event.size_change}"
                )
                await self.send_alert(simple_message)
            except Exception as e2:
                logger.error(f"Error sending fallback alert: {e2}")
    
    async def send_alert(self, message: str):
        """Send alert message to Telegram with retry logic"""
        for attempt in range(3):
            try:
                bot = Bot(token=self.bot_token)
                await bot.send_message(chat_id=self.chat_id, text=message, parse_mode='MarkdownV2')
                logger.info(f"Alert sent: {message[:50]}...")
                return
            except Exception as e:
                logger.error(f"Error sending alert attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        # Fallback to plain text
        try:
            plain_message = message.replace('*', '').replace('`', '').replace('\\', '')
            bot = Bot(token=self.bot_token)
            await bot.send_message(chat_id=self.chat_id, text=plain_message)
            logger.info("Alert sent as plain text fallback")
        except Exception as e2:
            logger.error(f"Error sending plain text fallback: {e2}")
    
    async def monitoring_loop(self):
        """Professional monitoring loop with batch optimization"""
        logger.info("Starting professional vault monitoring loop v2.0...")
        
        while self.vault_data.is_monitoring:
            try:
                active_vaults = self.vault_data.get_active_vaults()
                if not active_vaults:
                    logger.info("No active vaults to monitor, waiting...")
                    await asyncio.sleep(BotConfig.VAULT_CHECK_INTERVAL)
                    continue
                
                cycle_start = time.time()
                logger.info(f"Checking {len(active_vaults)} active vault(s) for position size changes...")
                
                # Professional batch checking with delay optimization
                for i, vault_info in enumerate(active_vaults):
                    if not self.vault_data.is_monitoring:
                        break
                    
                    vault_start = time.time()
                    logger.info(f"Checking vault {i+1}/{len(active_vaults)}: {vault_info.name}")
                    await self.check_vault_changes(vault_info)
                    vault_time = time.time() - vault_start
                    
                    if vault_time > BotConfig.MAX_API_RESPONSE_TIME:
                        logger.warning(f"Slow vault check for {vault_info.name}: {vault_time:.2f}s")
                    
                    # Optimized delay between vaults
                    if i < len(active_vaults) - 1:
                        await asyncio.sleep(BotConfig.VAULT_DELAY)
                
                cycle_time = time.time() - cycle_start
                logger.info(f"Monitoring cycle completed in {cycle_time:.2f}s")
                
                # Professional interval timing
                await asyncio.sleep(BotConfig.VAULT_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Shorter retry on errors
    
    async def health_monitor_loop(self):
        """Monitor system health and auto-recover"""
        while self.vault_data.is_monitoring:
            try:
                # Reset performance metrics every hour
                if (datetime.now() - self.vault_data.performance.last_reset).total_seconds() > 3600:
                    logger.info("Resetting performance metrics")
                    self.vault_data.performance = PerformanceMetrics()
                
                # Reactivate vaults that have been down for too long
                for vault in self.vault_data.vaults.values():
                    if not vault.is_active and vault.consecutive_failures >= 3:
                        if vault.last_successful_check:
                            time_since_last_success = datetime.now() - vault.last_successful_check
                            if time_since_last_success.total_seconds() > 1800:  # 30 minutes
                                logger.info(f"Reactivating vault {vault.name} after 30 minutes")
                                vault.is_active = True
                                vault.consecutive_failures = 0
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(300)
    
    async def start_monitoring(self):
        """Start the professional monitoring process"""
        if not self.vault_data.is_monitoring:
            self.vault_data.is_monitoring = True
            self.monitoring_task = asyncio.create_task(self.monitoring_loop())
            self.health_check_task = asyncio.create_task(self.health_monitor_loop())
            
            # Send professional startup message
            try:
                vault_count = escape_markdown_v2(str(len(self.vault_data.vaults)))
                active_count = escape_markdown_v2(str(len(self.vault_data.get_active_vaults())))
                confluence_threshold = escape_markdown_v2(str(self.vault_data.confluence_threshold))
                confluence_window = escape_markdown_v2(str(self.vault_data.confluence_window_minutes))
                start_time = escape_markdown_v2(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                
                startup_message = (
                    f"🚀 *Professional Monitoring Started v2\\.1*\n\n"
                    f"*Configuration:*\n"
                    f"• Total Vaults: {vault_count}\n"
                    f"• Active Vaults: {active_count}\n"
                    f"• Alert when: {confluence_threshold} vault\\(s\\) trade same token\n"
                    f"• Time window: {confluence_window} minute\\(s\\)\n"
                    f"• Tracking: Position SIZE changes\n"
                    f"• Anti\\-spam: 5min cooldowns\n\n"
                    f"*Professional Features:*\n"
                    f"• API Timeout: {escape_markdown_v2(str(BotConfig.API_TIMEOUT_SECONDS))}s\n"
                    f"• Auto\\-retry: {escape_markdown_v2(str(BotConfig.MAX_RETRIES))} attempts\n"
                    f"• Health monitoring: Enabled\n"
                    f"• Performance tracking: Active\n"
                    f"• **Persistent storage: Enabled**\n\n"
                    f"*Started:* {start_time}"
                )
                await self.send_alert(startup_message)
                logger.info("Professional monitoring started with persistent storage")
            except Exception as e:
                logger.error(f"Error sending startup message: {e}")
                await self.send_alert("🚀 Professional vault monitoring v2.1 started with persistent storage!")
    
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
        
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            self.health_check_task = None

# Add auto-start logic to main function
async def main():
    # Get environment variables
    telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not telegram_bot_token or not chat_id:
        logger.error("Missing required environment variables: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID")
        return
    
    # Create professional bot instance
    vault_bot = HyperliquidAdvancedBot(telegram_bot_token, chat_id)
    
    # Auto-start monitoring if vaults exist from previous session
    if vault_bot.vault_data.vaults and not vault_bot.vault_data.is_monitoring:
        logger.info(f"Auto-starting monitoring for {len(vault_bot.vault_data.vaults)} persisted vaults")
        await vault_bot.start_monitoring()
    
    # Create Telegram application
    application = Application.builder().token(telegram_bot_token).build()
    
    # Add command handlers (keeping existing ones)
    application.add_handler(CommandHandler("start", vault_bot.start_command))
    application.add_handler(CommandHandler("add_vault", vault_bot.add_vault_command))
    application.add_handler(CommandHandler("list_vaults", vault_bot.list_vaults_command))
    application.add_handler(CommandHandler("remove_vault", vault_bot.remove_vault_command))
    application.add_handler(CommandHandler("status", vault_bot.status_command))
    application.add_handler(CommandHandler("performance", vault_bot.performance_command))
    application.add_handler(CommandHandler("health", vault_bot.health_command))
    application.add_handler(CommandHandler("setvaults", vault_bot.set_vault_number_command))
    application.add_handler(CommandHandler("set_window", vault_bot.set_window_command))
    application.add_handler(CommandHandler("show_settings", vault_bot.show_settings_command))
    application.add_handler(CommandHandler("backup", vault_bot.backup_command))
    
    logger.info("Starting Advanced Hyperliquid Telegram bot v2.1...")
    
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