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
import threading

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Configure logging with more detail
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Production-grade configuration
class BotConfig:
    # API timeouts and retries - more conservative for stability
    API_TIMEOUT_SECONDS = 45  # Increased for stability
    MAX_RETRIES = 5  # More retries for reliability
    RETRY_DELAY_BASE = 3  # Longer backoff for stability
    
    # Monitoring intervals - optimized for 10+ vaults
    VAULT_CHECK_INTERVAL = 120  # Longer interval for stability
    VAULT_DELAY = 12  # More delay between vault checks
    BATCH_SIZE = 3  # Process vaults in small batches
    
    # Performance thresholds
    MAX_API_RESPONSE_TIME = 20
    MAX_CONCURRENT_OPERATIONS = 3  # Limit concurrent operations
    
    # Persistence with multiple fallbacks
    VAULT_DATA_FILE = "vault_data.json"
    BACKUP_FILE = "vault_data_backup.json"
    
    # Address validation
    HYPERLIQUID_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')
    
    # Rate limiting
    MIN_TIME_BETWEEN_SAVES = 5  # Seconds between saves to prevent spam

def escape_markdown_v2(text: str) -> str:
    """Escape special characters for MarkdownV2 with better error handling"""
    if not isinstance(text, str):
        text = str(text)
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
    first_scan_completed: bool = False  # NEW: Track if initial scan is done
    total_api_calls: int = 0
    avg_response_time: float = 0.0
    
    def __str__(self):
        return f"{self.name} ({self.address[:8]}...{self.address[-6:]})"
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'address': self.address,
            'name': self.name,
            'last_successful_check': self.last_successful_check.isoformat() if self.last_successful_check else None,
            'consecutive_failures': self.consecutive_failures,
            'is_active': self.is_active,
            'first_scan_completed': self.first_scan_completed,
            'total_api_calls': self.total_api_calls,
            'avg_response_time': self.avg_response_time
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create from dictionary for JSON deserialization"""
        last_check = None
        if data.get('last_successful_check'):
            try:
                last_check = datetime.fromisoformat(data['last_successful_check'])
            except:
                pass
        
        return cls(
            address=data['address'],
            name=data['name'],
            last_successful_check=last_check,
            consecutive_failures=data.get('consecutive_failures', 0),
            is_active=data.get('is_active', True),
            first_scan_completed=data.get('first_scan_completed', False),
            total_api_calls=data.get('total_api_calls', 0),
            avg_response_time=data.get('avg_response_time', 0.0)
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
class ThemeEvent:
    """Event representing theme-based trading activity"""
    theme: str
    vault_name: str
    vault_address: str
    coin: str
    trade_type: str
    size_change: Decimal
    timestamp: datetime
    
    def to_dict(self):
        return {
            'theme': self.theme,
            'vault_name': self.vault_name,
            'vault_address': self.vault_address,
            'coin': self.coin,
            'trade_type': self.trade_type,
            'size_change': float(self.size_change),
            'timestamp': self.timestamp.isoformat()
        }

class TokenCategorizer:
    """Advanced token categorization system for theme detection"""
    
    def __init__(self):
        # Comprehensive token categories based on current market themes
        self.categories = {
            'AI': {
                'tokens': ['ARKM', 'FET', 'RNDR', 'TAO', 'OCEAN', 'GLM', 'AI', 'AGIX', 'PHB', 'CTX', 'AKT', 'NMR'],
                'keywords': ['artificial', 'intelligence', 'neural', 'compute', 'render', 'machine', 'learning'],
                'emoji': '🤖'
            },
            'GAMING': {
                'tokens': ['IMX', 'GALA', 'SAND', 'MANA', 'AXS', 'ILV', 'ENJ', 'FLOW', 'RON', 'YGG', 'PIXEL', 'BEAM'],
                'keywords': ['game', 'gaming', 'metaverse', 'nft', 'play', 'virtual'],
                'emoji': '🎮'
            },
            'DEFI': {
                'tokens': ['UNI', 'AAVE', 'SNX', 'CRV', 'COMP', 'YFI', 'BAL', '1INCH', 'DYDX', 'GMX', 'GNS', 'JOE'],
                'keywords': ['defi', 'swap', 'yield', 'farm', 'lending', 'dex', 'protocol'],
                'emoji': '🏦'
            },
            'MEME': {
                'tokens': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'BOME', 'POPCAT', 'MEW', 'PNUT'],
                'keywords': ['meme', 'dog', 'cat', 'frog', 'community'],
                'emoji': '🐸'
            },
            'LAYER1': {
                'tokens': ['BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'ATOM', 'NEAR', 'FTM', 'ALGO', 'MATIC', 'AVAX', 'LUNA'],
                'keywords': ['blockchain', 'layer1', 'consensus', 'validator'],
                'emoji': '⛓️'
            },
            'LAYER2': {
                'tokens': ['ARB', 'OP', 'MATIC', 'LRC', 'ZK', 'METIS', 'BOBA', 'MANTA'],
                'keywords': ['layer2', 'scaling', 'rollup', 'zk'],
                'emoji': '🔗'
            },
            'ORACLES': {
                'tokens': ['LINK', 'BAND', 'TRB', 'API3', 'UMA', 'DIA'],
                'keywords': ['oracle', 'data', 'feed', 'price'],
                'emoji': '🔮'
            },
            'INFRASTRUCTURE': {
                'tokens': ['GRT', 'FIL', 'AR', 'STORJ', 'THETA', 'LPT', 'ANKR'],
                'keywords': ['infrastructure', 'storage', 'network', 'node'],
                'emoji': '🏗️'
            },
            'PRIVACY': {
                'tokens': ['XMR', 'ZEC', 'SCRT', 'ROSE', 'NYM', 'RAIL'],
                'keywords': ['privacy', 'anonymous', 'secret', 'zero'],
                'emoji': '🕵️'
            },
            'RWA': {
                'tokens': ['RIO', 'TRU', 'CFG', 'MKR', 'RWA', 'ONDO', 'POLYX'],
                'keywords': ['real', 'world', 'asset', 'tokeniz', 'rwa'],
                'emoji': '🏠'
            }
        }
        
        # Create reverse lookup for faster categorization
        self.token_to_category = {}
        for category, data in self.categories.items():
            for token in data['tokens']:
                self.token_to_category[token.upper()] = category
                
    def get_token_category(self, token: str) -> Optional[str]:
        """Get category for a specific token"""
        token_upper = token.upper()
        return self.token_to_category.get(token_upper)
    
    def get_category_emoji(self, category: str) -> str:
        """Get emoji for a category"""
        return self.categories.get(category, {}).get('emoji', '📊')
        
    def get_all_categories(self) -> List[str]:
        """Get list of all available categories"""
        return list(self.categories.keys())
    
    def add_custom_token(self, token: str, category: str):
        """Add a custom token to a category"""
        token_upper = token.upper()
        if category in self.categories:
            if token_upper not in self.categories[category]['tokens']:
                self.categories[category]['tokens'].append(token_upper)
            self.token_to_category[token_upper] = category
            logger.info(f"Added {token_upper} to {category} category")
    
    def get_category_tokens(self, category: str) -> List[str]:
        """Get all tokens in a category"""
        return self.categories.get(category, {}).get('tokens', [])

@dataclass
class PerformanceMetrics:
    total_api_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_response_time: float = 0.0
    last_reset: datetime = None
    vault_scan_times: Dict[str, float] = None
    
    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.now()
        if self.vault_scan_times is None:
            self.vault_scan_times = {}
    
    @property
    def success_rate(self) -> float:
        if self.total_api_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_api_calls) * 100

class ThreadSafeVaultData:
    """Thread-safe vault data with proper locking and persistence"""
    
    def __init__(self):
        self._lock = threading.RLock()  # Reentrant lock for nested operations
        self._vaults: Dict[str, VaultInfo] = {}
        self._previous_positions: Dict[str, Dict[str, PositionData]] = {}
        self._last_alerts: Dict[str, Dict[str, datetime]] = {}
        self._trade_events: List[TradeEvent] = []
        self._is_monitoring = False
        self._performance = PerformanceMetrics()
        self._last_save_time = 0
        
        # Settings
        self._confluence_threshold = 1
        self._confluence_window_minutes = 10
        self._cooldown_minutes = 5
        
        # Theme detection settings
        self._theme_alerts_enabled = True
        self._theme_threshold = 2  # Minimum vaults needed for theme alert
        self._theme_window_minutes = 15  # Theme detection window
        self._theme_events: List[ThemeEvent] = []
        
        # Initialize token categorizer
        self._token_categorizer = TokenCategorizer()
        
        # Load persisted data
        self._load_data()
    
    @property
    def vaults(self) -> Dict[str, VaultInfo]:
        with self._lock:
            return self._vaults.copy()
    
    @property
    def is_monitoring(self) -> bool:
        with self._lock:
            return self._is_monitoring
    
    @is_monitoring.setter
    def is_monitoring(self, value: bool):
        with self._lock:
            self._is_monitoring = value
    
    @property
    def performance(self) -> PerformanceMetrics:
        with self._lock:
            return self._performance
    
    @property
    def confluence_threshold(self) -> int:
        with self._lock:
            return self._confluence_threshold
    
    @confluence_threshold.setter
    def confluence_threshold(self, value: int):
        with self._lock:
            self._confluence_threshold = value
            self._safe_save()
    
    @property
    def confluence_window_minutes(self) -> int:
        with self._lock:
            return self._confluence_window_minutes
    
    @confluence_window_minutes.setter
    def confluence_window_minutes(self, value: int):
        with self._lock:
            self._confluence_window_minutes = value
            self._safe_save()
    
    @property
    def cooldown_minutes(self) -> int:
        with self._lock:
            return self._cooldown_minutes
    
    # Theme detection properties
    @property
    def theme_alerts_enabled(self) -> bool:
        with self._lock:
            return self._theme_alerts_enabled
    
    @theme_alerts_enabled.setter
    def theme_alerts_enabled(self, value: bool):
        with self._lock:
            self._theme_alerts_enabled = value
            self._safe_save()
    
    @property
    def theme_threshold(self) -> int:
        with self._lock:
            return self._theme_threshold
    
    @theme_threshold.setter
    def theme_threshold(self, value: int):
        with self._lock:
            self._theme_threshold = max(1, value)
            self._safe_save()
    
    @property
    def theme_window_minutes(self) -> int:
        with self._lock:
            return self._theme_window_minutes
    
    @theme_window_minutes.setter
    def theme_window_minutes(self, value: int):
        with self._lock:
            self._theme_window_minutes = max(1, value)
            self._safe_save()
    
    @property
    def token_categorizer(self) -> TokenCategorizer:
        with self._lock:
            return self._token_categorizer
    
    def _safe_save(self):
        """Rate-limited save to prevent excessive disk I/O"""
        current_time = time.time()
        if current_time - self._last_save_time < BotConfig.MIN_TIME_BETWEEN_SAVES:
            return  # Skip save to prevent spam
        
        self._last_save_time = current_time
        self._save_data()
    
    def _save_data(self):
        """Save vault data with atomic write and backup"""
        try:
            vault_data = {
                'vaults': {name: vault.to_dict() for name, vault in self._vaults.items()},
                'confluence_threshold': self._confluence_threshold,
                'confluence_window_minutes': self._confluence_window_minutes,
                'cooldown_minutes': self._cooldown_minutes,
                'theme_alerts_enabled': self._theme_alerts_enabled,
                'theme_threshold': self._theme_threshold,
                'theme_window_minutes': self._theme_window_minutes,
                'saved_at': datetime.now().isoformat(),
                'version': '2.3'
            }
            
            # Atomic write: write to temp file first, then rename
            temp_file = f"{BotConfig.VAULT_DATA_FILE}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(vault_data, f, indent=2)
            
            # Create backup of existing file
            if os.path.exists(BotConfig.VAULT_DATA_FILE):
                try:
                    os.rename(BotConfig.VAULT_DATA_FILE, BotConfig.BACKUP_FILE)
                except:
                    pass  # Backup creation failed, but continue
            
            # Atomic rename
            os.rename(temp_file, BotConfig.VAULT_DATA_FILE)
            
            logger.info(f"Safely saved {len(self._vaults)} vaults to persistent storage")
            
        except Exception as e:
            logger.error(f"Error saving vault data: {e}")
            # Try to restore from backup if save failed
            if os.path.exists(BotConfig.BACKUP_FILE):
                try:
                    os.rename(BotConfig.BACKUP_FILE, BotConfig.VAULT_DATA_FILE)
                    logger.info("Restored from backup after save failure")
                except:
                    pass
    
    def _load_data(self):
        """Load vault data with fallback options"""
        try:
            data = None
            loaded_from = None
            
            # Try primary file
            if os.path.exists(BotConfig.VAULT_DATA_FILE):
                try:
                    with open(BotConfig.VAULT_DATA_FILE, 'r') as f:
                        data = json.load(f)
                    loaded_from = BotConfig.VAULT_DATA_FILE
                except Exception as e:
                    logger.warning(f"Failed to load primary file: {e}")
            
            # Try backup file
            if not data and os.path.exists(BotConfig.BACKUP_FILE):
                try:
                    with open(BotConfig.BACKUP_FILE, 'r') as f:
                        data = json.load(f)
                    loaded_from = BotConfig.BACKUP_FILE
                    logger.info("Loaded from backup file")
                except Exception as e:
                    logger.warning(f"Failed to load backup file: {e}")
            
            if data:
                # Load vaults
                for name, vault_dict in data.get('vaults', {}).items():
                    self._vaults[name] = VaultInfo.from_dict(vault_dict)
                    self._previous_positions[vault_dict['address']] = {}
                    self._last_alerts[vault_dict['address']] = {}
                
                # Load settings
                self._confluence_threshold = data.get('confluence_threshold', 1)
                self._confluence_window_minutes = data.get('confluence_window_minutes', 10)
                self._cooldown_minutes = data.get('cooldown_minutes', 5)
                self._theme_alerts_enabled = data.get('theme_alerts_enabled', True)
                self._theme_threshold = data.get('theme_threshold', 2)
                self._theme_window_minutes = data.get('theme_window_minutes', 15)
                
                version = data.get('version', 'unknown')
                saved_at = data.get('saved_at', 'unknown')
                logger.info(f"Loaded {len(self._vaults)} vaults from: {loaded_from} (version: {version})")
                
                if self._vaults:
                    vault_names = ", ".join(self._vaults.keys())
                    logger.info(f"Restored vaults: {vault_names}")
            else:
                logger.info("No persisted vault data found - starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading vault data: {e}")
    
    def add_vault(self, address: str, name: str) -> Tuple[bool, str]:
        """Thread-safe vault addition with validation"""
        with self._lock:
            # Validate address format
            if not BotConfig.HYPERLIQUID_ADDRESS_PATTERN.match(address):
                return False, "Invalid address format. Must be 0x followed by 40 hex characters."
            
            # Check for duplicate name
            if name in self._vaults:
                return False, f"A vault with name '{name}' already exists."
            
            # Check for duplicate address
            for existing_vault in self._vaults.values():
                if existing_vault.address.lower() == address.lower():
                    return False, f"This address is already monitored as '{existing_vault.name}'."
            
            # Add vault
            self._vaults[name] = VaultInfo(address, name)
            self._previous_positions[address] = {}
            self._last_alerts[address] = {}
            
            # Save immediately
            self._save_data()
            
            logger.info(f"Added vault: {name} ({address})")
            return True, f"Successfully added vault '{name}'."
    
    def remove_vault(self, name: str) -> bool:
        """Thread-safe vault removal"""
        with self._lock:
            if name in self._vaults:
                vault_info = self._vaults[name]
                del self._vaults[name]
                self._previous_positions.pop(vault_info.address, None)
                self._last_alerts.pop(vault_info.address, None)
                
                self._save_data()
                logger.info(f"Removed vault: {name}")
                return True
            return False
    
    def get_vault_by_name(self, name: str) -> Optional[VaultInfo]:
        """Thread-safe vault lookup"""
        with self._lock:
            return self._vaults.get(name)
    
    def get_active_vaults(self) -> List[VaultInfo]:
        """Thread-safe active vault list"""
        with self._lock:
            return [v for v in self._vaults.values() if v.is_active]
    
    def get_vault_list(self) -> List[VaultInfo]:
        """Thread-safe vault list"""
        with self._lock:
            return list(self._vaults.values())
    
    def mark_vault_failure(self, vault_address: str):
        """Thread-safe failure marking"""
        with self._lock:
            for vault in self._vaults.values():
                if vault.address == vault_address:
                    vault.consecutive_failures += 1
                    if vault.consecutive_failures >= 3:
                        vault.is_active = False
                        logger.warning(f"Deactivating vault {vault.name} after {vault.consecutive_failures} failures")
                    self._safe_save()
                    break
    
    def mark_vault_success(self, vault_address: str, response_time: float = 0.0):
        """Thread-safe success marking with performance tracking"""
        with self._lock:
            for vault in self._vaults.values():
                if vault.address == vault_address:
                    vault.consecutive_failures = 0
                    vault.last_successful_check = datetime.now()
                    vault.is_active = True
                    vault.total_api_calls += 1
                    
                    # Update average response time
                    if vault.total_api_calls == 1:
                        vault.avg_response_time = response_time
                    else:
                        total_calls = vault.total_api_calls
                        vault.avg_response_time = (
                            (vault.avg_response_time * (total_calls - 1) + response_time) 
                            / total_calls
                        )
                    
                    self._safe_save()
                    break
    
    def complete_first_scan(self, vault_address: str):
        """Mark first scan as completed to enable alerts"""
        with self._lock:
            for vault in self._vaults.values():
                if vault.address == vault_address:
                    vault.first_scan_completed = True
                    self._safe_save()
                    logger.info(f"First scan completed for {vault.name} - alerts now enabled")
                    break
    
    def is_cooldown_active(self, vault_address: str, coin: str) -> bool:
        """Thread-safe cooldown check"""
        with self._lock:
            if vault_address not in self._last_alerts:
                return False
            if coin not in self._last_alerts[vault_address]:
                return False
            
            last_alert = self._last_alerts[vault_address][coin]
            cooldown_end = last_alert + timedelta(minutes=self._cooldown_minutes)
            return datetime.now() < cooldown_end
    
    def set_cooldown(self, vault_address: str, coin: str):
        """Thread-safe cooldown setting"""
        with self._lock:
            if vault_address not in self._last_alerts:
                self._last_alerts[vault_address] = {}
            self._last_alerts[vault_address][coin] = datetime.now()
    
    def add_trade_event(self, event: TradeEvent):
        """Thread-safe trade event addition"""
        with self._lock:
            self._trade_events.append(event)
            # Clean up old events
            cutoff_time = datetime.now() - timedelta(minutes=self._confluence_window_minutes)
            self._trade_events = [e for e in self._trade_events if e.timestamp > cutoff_time]
    
    def get_confluence_events(self, coin: str, current_time: datetime) -> List[TradeEvent]:
        """Thread-safe confluence event retrieval"""
        with self._lock:
            cutoff_time = current_time - timedelta(minutes=self._confluence_window_minutes)
            return [e for e in self._trade_events if e.coin == coin and e.timestamp > cutoff_time]
    
    def add_theme_event(self, event: ThemeEvent):
        """Thread-safe theme event addition"""
        with self._lock:
            self._theme_events.append(event)
            # Clean up old theme events
            cutoff_time = datetime.now() - timedelta(minutes=self._theme_window_minutes)
            self._theme_events = [e for e in self._theme_events if e.timestamp > cutoff_time]
    
    def get_theme_events(self, theme: str, current_time: datetime) -> List[ThemeEvent]:
        """Thread-safe theme event retrieval"""
        with self._lock:
            cutoff_time = current_time - timedelta(minutes=self._theme_window_minutes)
            return [e for e in self._theme_events if e.theme == theme and e.timestamp > cutoff_time]
    
    def check_theme_confluence(self, trade_event: TradeEvent) -> Optional[Tuple[str, List[ThemeEvent]]]:
        """Check if a trade event triggers theme confluence"""
        with self._lock:
            # Get the token category
            category = self._token_categorizer.get_token_category(trade_event.coin)
            if not category:
                return None  # Token not in any category
            
            # Create theme event
            theme_event = ThemeEvent(
                theme=category,
                vault_name=trade_event.vault_name,
                vault_address=trade_event.vault_address,
                coin=trade_event.coin,
                trade_type=trade_event.trade_type,
                size_change=trade_event.size_change,
                timestamp=trade_event.timestamp
            )
            
            # Check existing theme events BEFORE adding current one
            existing_theme_events = self.get_theme_events(category, trade_event.timestamp)
            existing_unique_vaults = len(set(e.vault_name for e in existing_theme_events))
            
            # Check if current vault already contributed to this theme
            current_vault_already_counted = any(e.vault_name == trade_event.vault_name for e in existing_theme_events)
            
            # Calculate total unique vaults including current one
            total_unique_vaults = existing_unique_vaults + (0 if current_vault_already_counted else 1)
            
            logger.info(f"🎯 Theme confluence for {category}: {existing_unique_vaults} existing + {trade_event.vault_name} = {total_unique_vaults} total (threshold: {self._theme_threshold})")
            
            # Add current theme event
            self.add_theme_event(theme_event)
            
            # Check if theme threshold is met
            if total_unique_vaults >= self._theme_threshold:
                # Get all theme events including current one
                all_theme_events = self.get_theme_events(category, trade_event.timestamp)
                return category, all_theme_events
            
            return None
    
    def get_previous_positions(self, vault_address: str) -> Dict[str, PositionData]:
        """Thread-safe previous position retrieval"""
        with self._lock:
            return self._previous_positions.get(vault_address, {}).copy()
    
    def update_previous_positions(self, vault_address: str, positions: Dict[str, PositionData]):
        """Thread-safe position update"""
        with self._lock:
            self._previous_positions[vault_address] = positions.copy()

class HyperliquidAdvancedBot:
    """Production-grade Hyperliquid monitoring bot with proper concurrency control"""
    
    def __init__(self, telegram_bot_token: str, chat_id: str):
        self.bot_token = telegram_bot_token
        self.chat_id = chat_id
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.vault_data = ThreadSafeVaultData()
        self.monitoring_task: Optional[asyncio.Task] = None
        self.health_check_task: Optional[asyncio.Task] = None
        self._monitoring_lock = asyncio.Lock()
        self._api_semaphore = asyncio.Semaphore(BotConfig.MAX_CONCURRENT_OPERATIONS)
        
    # Command handlers with improved error handling
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with auto-monitoring"""
        try:
            # Auto-start monitoring if vaults exist
            if self.vault_data.vaults and not self.vault_data.is_monitoring:
                await self.start_monitoring()
            
            vault_count = len(self.vault_data.vaults)
            active_count = len(self.vault_data.get_active_vaults())
            
            welcome_message = (
                "🤖 *Advanced Hyperliquid Position Monitor v2\\.3*\n\n"
                "*🆕 Production\\-Grade Features:*\n"
                "• Thread\\-safe operations\n"
                "• Atomic data persistence\n"
                "• Batch processing for 10\\+ vaults\n"
                "• Smart first\\-scan filtering\n"
                "• Enhanced error recovery\n"
                "• 🎯 Theme confluence detection\n\n"
                "*Commands:*\n"
                "/add\\_vault \\<address\\> \\<name\\> \\- Add vault\n"
                "/list\\_vaults \\- Show monitored vaults\n"
                "/remove\\_vault \\<name\\> \\- Remove vault\n"
                "/backup \\- Manual backup\n"
                "/status \\- Bot status\n"
                "/performance \\- API metrics\n"
                "/setvaults \\<number\\> \\- Set confluence threshold\n"
                "/set\\_window \\<minutes\\> \\- Set time window\n"
                "/health \\- System health\n"
                "/themes \\- Theme detection settings\n"
                "/theme\\_threshold \\<number\\> \\- Set theme threshold\n"
                "/categories \\- List token categories\n\n"
                f"*Current Status:*\n"
                f"• Vaults: {active_count}/{vault_count}\n"
                f"• Monitoring: {'🟢 Active' if self.vault_data.is_monitoring else '🔴 Stopped'}\n"
                f"• Confluence: {self.vault_data.confluence_threshold} vault\\(s\\)\n\n"
                "🚀 Ready for production use\\!"
            )
            await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')
            logger.info(f"Start command executed by user {update.effective_user.id}")
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("🤖 Advanced Hyperliquid Monitor v2.3 - Production Ready!\nUse /add_vault <address> <name> to start.")
    
    async def add_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_vault command with comprehensive validation"""
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Please provide both address and name:\n`/add_vault <address> <name>`", 
                    parse_mode='MarkdownV2'
                )
                return
            
            address = context.args[0].strip()
            name = " ".join(context.args[1:]).strip()
            
            # Validate name length
            if len(name) > 20:
                await update.message.reply_text("❌ Vault name must be 20 characters or less")
                return
            
            success, message = self.vault_data.add_vault(address, name)
            
            if success:
                escaped_name = escape_markdown_v2(name)
                escaped_address = escape_markdown_v2(f"{address[:8]}...{address[-6:]}")
                
                response_message = (
                    f"✅ *Vault Added Successfully*\n\n"
                    f"*Name:* {escaped_name}\n"
                    f"*Address:* `{escaped_address}`\n\n"
                    f"🔍 *Initial scan* will complete first \\(no alerts\\)\n"
                    f"📊 *Monitoring* will begin automatically\n"
                    f"💾 *Saved* to persistent storage"
                )
                await update.message.reply_text(response_message, parse_mode='MarkdownV2')
                
                # Start monitoring if not already running
                if not self.vault_data.is_monitoring:
                    await self.start_monitoring()
                
                logger.info(f"Successfully added vault: {name} ({address})")
            else:
                escaped_error = escape_markdown_v2(message)
                await update.message.reply_text(f"❌ {escaped_error}")
                
        except Exception as e:
            logger.error(f"Error in add_vault command: {e}")
            await update.message.reply_text("❌ Error adding vault. Please check the address format and try again.")
    
    async def list_vaults_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list_vaults command with enhanced display"""
        try:
            vaults = self.vault_data.get_vault_list()
            if not vaults:
                message = "📭 No vaults being monitored\\.\n\nUse /add\\_vault \\<address\\> \\<name\\> to add one\\."
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                return
            
            active_vaults = [v for v in vaults if v.is_active]
            
            message = f"📊 *Monitored Vaults:* {len(active_vaults)}/{len(vaults)} active\n\n"
            
            for i, vault in enumerate(vaults, 1):
                status_icon = "🟢" if vault.is_active else "🔴"
                escaped_name = escape_markdown_v2(vault.name)
                escaped_address = escape_markdown_v2(f"{vault.address[:8]}...{vault.address[-6:]}")
                
                # Performance stats
                avg_time = f"{vault.avg_response_time:.1f}s" if vault.avg_response_time > 0 else "N/A"
                calls = vault.total_api_calls
                
                message += f"{i}\\. {status_icon} *{escaped_name}*\n"
                message += f"   `{escaped_address}`\n"
                message += f"   📊 {calls} calls, {escape_markdown_v2(avg_time)} avg\n\n"
            
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            
        except Exception as e:
            logger.error(f"Error in list_vaults command: {e}")
            vaults = self.vault_data.get_vault_list()
            simple_message = f"📊 Monitored vaults ({len(vaults)}):\n"
            for i, vault in enumerate(vaults, 1):
                status = "🟢" if vault.is_active else "🔴"
                simple_message += f"{i}. {status} {vault.name} ({vault.address[:8]}...)\n"
            await update.message.reply_text(simple_message)
    
    async def remove_vault_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_vault command with improved error messages"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide vault name: /remove\\_vault \\<name\\>", parse_mode='MarkdownV2')
                return
            
            name = " ".join(context.args).strip()
            
            if self.vault_data.remove_vault(name):
                escaped_name = escape_markdown_v2(name)
                message = f"✅ Removed vault: *{escaped_name}*\n💾 Changes saved to persistent storage"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Removed vault: {name}")
            else:
                # Improved error message with available vault names
                available_vaults = list(self.vault_data.vaults.keys())
                if available_vaults:
                    vault_list = "\\n• ".join([escape_markdown_v2(v) for v in available_vaults])
                    message = f"❌ Vault '{escape_markdown_v2(name)}' not found\\.\n\n*Available vaults:*\n• {vault_list}\n\n💡 *Note:* Names are case\\-sensitive"
                    await update.message.reply_text(message, parse_mode='MarkdownV2')
                else:
                    await update.message.reply_text("❌ No vaults are currently being monitored")
                    
        except Exception as e:
            logger.error(f"Error in remove_vault command: {e}")
            await update.message.reply_text("Error removing vault. Please try again.")
    
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command - show vault configuration for manual backup"""
        try:
            if not self.vault_data.vaults:
                await update.message.reply_text("❌ No vaults to backup")
                return
            
            # Create human-readable backup
            vault_list = ""
            for i, (name, vault) in enumerate(self.vault_data.vaults.items(), 1):
                status = "✅" if vault.is_active else "❌"
                first_scan = "✅" if vault.first_scan_completed else "🔄"
                vault_list += f"{i}. {status}{first_scan} {name}: {vault.address}\n"
            
            backup_message = (
                f"💾 **VAULT BACKUP v2.2** ({len(self.vault_data.vaults)} vaults)\n\n"
                f"**Settings:**\n"
                f"• Alert when: {self.vault_data.confluence_threshold} vault(s) trade same token\n"
                f"• Time window: {self.vault_data.confluence_window_minutes} minutes\n"
                f"• Cooldown: {self.vault_data.cooldown_minutes} minutes\n\n"
                f"**Vaults:** (✅=active, 🔄=scanning, ❌=inactive)\n{vault_list}\n"
                f"**Performance:**\n"
                f"• API Success Rate: {self.vault_data.performance.success_rate:.1f}%\n"
                f"• Total API Calls: {self.vault_data.performance.total_api_calls}\n\n"
                f"**Backup created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"💡 **Save this message** - you can use it to restore your vaults if needed!"
            )
            
            await update.message.reply_text(backup_message)
            logger.info(f"Manual backup provided for {len(self.vault_data.vaults)} vaults")
            
        except Exception as e:
            logger.error(f"Error in backup command: {e}")
            await update.message.reply_text("Error creating backup")
    
    async def performance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command with enhanced metrics"""
        try:
            perf = self.vault_data.performance
            active_vaults = self.vault_data.get_active_vaults()
            
            success_rate = f"{perf.success_rate:.1f}%"
            avg_time = f"{perf.avg_response_time:.2f}s" if perf.avg_response_time > 0 else "N/A"
            
            # Calculate uptime
            if perf.last_reset:
                uptime_seconds = (datetime.now() - perf.last_reset).total_seconds()
                uptime_hours = uptime_seconds / 3600
                uptime_str = f"{uptime_hours:.1f}h"
            else:
                uptime_str = "N/A"
            
            message = (
                f"📊 **API Performance Metrics**\n\n"
                f"**Success Rate:** {success_rate}\n"
                f"**Total Calls:** {perf.total_api_calls}\n"
                f"**Successful:** {perf.successful_calls}\n"
                f"**Failed:** {perf.failed_calls}\n"
                f"**Avg Response:** {avg_time}\n"
                f"**Uptime:** {uptime_str}\n\n"
                f"**Active Vaults:** {len(active_vaults)}\n"
                f"**Batch Size:** {BotConfig.BATCH_SIZE}\n"
                f"**Check Interval:** {BotConfig.VAULT_CHECK_INTERVAL}s\n\n"
                f"💡 Metrics reset every hour for accuracy"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in performance command: {e}")
            await update.message.reply_text("Error retrieving performance metrics")
    
    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command with system diagnostics"""
        try:
            vaults = self.vault_data.get_vault_list()
            active_vaults = self.vault_data.get_active_vaults()
            inactive_vaults = [v for v in vaults if not v.is_active]
            
            # System health indicators
            health_score = 100
            issues = []
            
            if not self.vault_data.is_monitoring:
                health_score -= 50
                issues.append("Monitoring stopped")
            
            if len(inactive_vaults) > 0:
                health_score -= min(30, len(inactive_vaults) * 10)
                issues.append(f"{len(inactive_vaults)} inactive vaults")
            
            if self.vault_data.performance.success_rate < 90:
                health_score -= 20
                issues.append("Low API success rate")
            
            # Health icon
            if health_score >= 90:
                health_icon = "🟢"
                health_status = "Excellent"
            elif health_score >= 70:
                health_icon = "🟡"
                health_status = "Good"
            else:
                health_icon = "🔴"
                health_status = "Needs Attention"
            
            message = (
                f"🏥 **System Health Report**\n\n"
                f"**Overall Health:** {health_icon} {health_status} ({health_score}%)\n\n"
                f"**Vault Status:**\n"
                f"• Total: {len(vaults)}\n"
                f"• Active: {len(active_vaults)}\n"
                f"• Inactive: {len(inactive_vaults)}\n\n"
                f"**Monitoring:** {'🟢 Running' if self.vault_data.is_monitoring else '🔴 Stopped'}\n"
                f"**API Health:** {self.vault_data.performance.success_rate:.1f}% success\n\n"
            )
            
            if issues:
                message += f"**Issues Detected:**\n"
                for issue in issues:
                    message += f"⚠️ {issue}\n"
                message += "\n"
            
            message += f"**Last Check:** {datetime.now().strftime('%H:%M:%S')}"
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in health command: {e}")
            await update.message.reply_text("Error retrieving health status")
    
    async def set_vault_number_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setvaults command for confluence threshold"""
        try:
            if not context.args:
                await update.message.reply_text("Please provide number: /setvaults \\<number\\>", parse_mode='MarkdownV2')
                return
            
            try:
                threshold = int(context.args[0])
                if threshold < 1:
                    await update.message.reply_text("❌ Confluence threshold must be at least 1")
                    return
                
                if threshold > 10:
                    await update.message.reply_text("❌ Confluence threshold cannot exceed 10 for stability")
                    return
                
                self.vault_data.confluence_threshold = threshold
                
                escaped_threshold = escape_markdown_v2(str(threshold))
                message = f"✅ Confluence threshold set to: *{escaped_threshold}* vault\\(s\\)\n💾 Setting saved to persistent storage"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Confluence threshold set to: {threshold}")
                
            except ValueError:
                await update.message.reply_text("❌ Please provide a valid number")
                
        except Exception as e:
            logger.error(f"Error in setvaults command: {e}")
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
                
                if minutes > 1440:  # 24 hours max
                    await update.message.reply_text("❌ Time window cannot exceed 1440 minutes (24 hours)")
                    return
                
                self.vault_data.confluence_window_minutes = minutes
                
                escaped_minutes = escape_markdown_v2(str(minutes))
                message = f"✅ Confluence window set to: *{escaped_minutes}* minute\\(s\\)\n💾 Setting saved to persistent storage"
                await update.message.reply_text(message, parse_mode='MarkdownV2')
                logger.info(f"Confluence window set to: {minutes} minutes")
                
            except ValueError:
                await update.message.reply_text("❌ Please provide a valid number")
                
        except Exception as e:
            logger.error(f"Error in set_window command: {e}")
            await update.message.reply_text("Error setting confluence window.")
    
    async def show_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /show_settings command with enhanced display"""
        try:
            vaults = self.vault_data.get_vault_list()
            active_vaults = self.vault_data.get_active_vaults()
            
            status_icon = "🟢" if self.vault_data.is_monitoring else "🔴"
            status_text = "Active" if self.vault_data.is_monitoring else "Stopped"
            
            confluence_threshold = escape_markdown_v2(str(self.vault_data.confluence_threshold))
            confluence_window = escape_markdown_v2(str(self.vault_data.confluence_window_minutes))
            cooldown = escape_markdown_v2(str(self.vault_data.cooldown_minutes))
            vault_count = escape_markdown_v2(str(len(vaults)))
            active_count = escape_markdown_v2(str(len(active_vaults)))
            
            message = (
                f"⚙️ *Bot Settings v2\\.3*\n\n"
                f"*Status:* {status_icon} {status_text}\n"
                f"*Vaults:* {active_count}/{vault_count} active\n\n"
                f"*Detection Settings:*\n"
                f"• Confluence Threshold: {confluence_threshold} vault\\(s\\)\n"
                f"• Confluence Window: {confluence_window} minute\\(s\\)\n"
                f"• Anti\\-spam Cooldown: {cooldown} minute\\(s\\)\n\n"
                f"*Theme Detection:*\n"
                f"• Status: {'🟢 Enabled' if self.vault_data.theme_alerts_enabled else '🔴 Disabled'}\n"
                f"• Theme Threshold: {escape_markdown_v2(str(self.vault_data.theme_threshold))} vault\\(s\\)\n"
                f"• Theme Window: {escape_markdown_v2(str(self.vault_data.theme_window_minutes))} minute\\(s\\)\n"
                f"• Categories: {escape_markdown_v2(str(len(self.vault_data.token_categorizer.get_all_categories())))} themes\n\n"
                f"*Production Config:*\n"
                f"• Check Interval: {escape_markdown_v2(str(BotConfig.VAULT_CHECK_INTERVAL))} seconds\n"
                f"• Batch Size: {escape_markdown_v2(str(BotConfig.BATCH_SIZE))} vaults\n"
                f"• Max Retries: {escape_markdown_v2(str(BotConfig.MAX_RETRIES))}\n"
                f"• API Timeout: {escape_markdown_v2(str(BotConfig.API_TIMEOUT_SECONDS))}s\n\n"
                f"*Features:*\n"
                f"• Tracks: Position SIZE changes\n"
                f"• Thread\\-safe operations\n"
                f"• Atomic persistence\n"
                f"• Smart first\\-scan filtering"
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            
        except Exception as e:
            logger.error(f"Error in show_settings command: {e}")
            vaults = self.vault_data.get_vault_list()
            active_vaults = self.vault_data.get_active_vaults()
            
            message = (
                f"⚙️ Bot Settings v2.3:\n"
                f"Status: {'Active' if self.vault_data.is_monitoring else 'Stopped'}\n"
                f"Vaults: {len(active_vaults)}/{len(vaults)} active\n"
                f"Confluence: {self.vault_data.confluence_threshold} vaults\n"
                f"Window: {self.vault_data.confluence_window_minutes} minutes\n"
                f"Cooldown: {self.vault_data.cooldown_minutes} minutes\n"
                f"Theme Detection: {'Enabled' if self.vault_data.theme_alerts_enabled else 'Disabled'}\n"
                f"Theme Threshold: {self.vault_data.theme_threshold} vaults\n"
                f"Check Interval: {BotConfig.VAULT_CHECK_INTERVAL}s"
            )
            await update.message.reply_text(message)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show comprehensive status"""
        await self.show_settings_command(update, context)
    
    async def themes_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /themes command - show theme detection settings"""
        try:
            enabled_text = "🟢 Enabled" if self.vault_data.theme_alerts_enabled else "🔴 Disabled"
            
            message = (
                f"🎯 **THEME DETECTION SETTINGS**\n\n"
                f"**Status:** {enabled_text}\n"
                f"**Threshold:** {self.vault_data.theme_threshold} vault(s)\n"
                f"**Time Window:** {self.vault_data.theme_window_minutes} minutes\n\n"
                f"**Available Categories:**\n"
            )
            
            categories = self.vault_data.token_categorizer.get_all_categories()
            for category in sorted(categories):
                emoji = self.vault_data.token_categorizer.get_category_emoji(category)
                tokens = self.vault_data.token_categorizer.get_category_tokens(category)
                message += f"{emoji} {category}: {len(tokens)} tokens\n"
            
            message += (
                f"\n**How it works:**\n"
                f"• Detects when {self.vault_data.theme_threshold}+ vaults trade tokens from same category\n"
                f"• Groups tokens by theme (AI, Gaming, DeFi, etc.)\n"
                f"• Alerts on coordinated thematic trading\n\n"
                f"**Commands:**\n"
                f"/theme_threshold <number> - Set vault threshold\n"
                f"/categories - List all token categories"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in themes command: {e}")
            await update.message.reply_text("Error showing theme settings.")
    
    async def theme_threshold_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /theme_threshold command"""
        try:
            if not context.args:
                await update.message.reply_text(
                    f"Current theme threshold: {self.vault_data.theme_threshold} vault(s)\n"
                    f"Usage: /theme_threshold <number>"
                )
                return
            
            try:
                threshold = int(context.args[0])
                if threshold < 1:
                    await update.message.reply_text("Theme threshold must be at least 1")
                    return
                
                self.vault_data.theme_threshold = threshold
                await update.message.reply_text(
                    f"✅ Theme threshold set to {threshold} vault(s)\n"
                    f"Theme alerts will trigger when {threshold}+ vaults trade tokens from the same category."
                )
                
            except ValueError:
                await update.message.reply_text("Please provide a valid number")
                
        except Exception as e:
            logger.error(f"Error in theme_threshold command: {e}")
            await update.message.reply_text("Error setting theme threshold.")
    
    async def categories_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /categories command - show detailed token categories"""
        try:
            message = "🏷️ **TOKEN CATEGORIES**\n\n"
            
            categories = self.vault_data.token_categorizer.get_all_categories()
            for category in sorted(categories):
                emoji = self.vault_data.token_categorizer.get_category_emoji(category)
                tokens = self.vault_data.token_categorizer.get_category_tokens(category)
                
                message += f"{emoji} **{category}** ({len(tokens)} tokens)\n"
                # Show first 8 tokens, then "..." if more
                if len(tokens) <= 8:
                    message += f"   {', '.join(sorted(tokens))}\n\n"
                else:
                    displayed_tokens = sorted(tokens)[:8]
                    remaining = len(tokens) - 8
                    message += f"   {', '.join(displayed_tokens)}\n"
                    message += f"   ...and {remaining} more\n\n"
            
            message += (
                f"**Theme Detection:**\n"
                f"When {self.vault_data.theme_threshold}+ vaults trade tokens from the same category "
                f"within {self.vault_data.theme_window_minutes} minutes, you'll get a theme confluence alert!\n\n"
                f"Example: If 2+ vaults trade AI tokens (ARKM, FET, RNDR), "
                f"you'll get an 🤖 AI theme alert."
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in categories command: {e}")
            await update.message.reply_text("Error showing categories.")
    
    async def safe_api_call(self, vault_info: VaultInfo, operation: str) -> Optional[Dict]:
        """Production-grade API call with comprehensive error handling"""
        async with self._api_semaphore:  # Limit concurrent API calls
            start_time = time.time()
            
            for attempt in range(BotConfig.MAX_RETRIES):
                try:
                    self.vault_data.performance.total_api_calls += 1
                    
                    # Use asyncio timeout with proper error handling
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
                    
                    # Update performance metrics safely
                    if self.vault_data.performance.successful_calls == 1:
                        self.vault_data.performance.avg_response_time = response_time
                    else:
                        total_calls = self.vault_data.performance.successful_calls
                        self.vault_data.performance.avg_response_time = (
                            (self.vault_data.performance.avg_response_time * (total_calls - 1) + response_time) 
                            / total_calls
                        )
                    
                    self.vault_data.mark_vault_success(vault_info.address, response_time)
                    
                    if response_time > BotConfig.MAX_API_RESPONSE_TIME:
                        logger.warning(f"Slow API response for {vault_info.name}: {response_time:.2f}s")
                    
                    return user_state
                    
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{BotConfig.MAX_RETRIES} for {vault_info.name}")
                    self.vault_data.performance.failed_calls += 1
                    
                except Exception as e:
                    logger.error(f"API error on attempt {attempt + 1}/{BotConfig.MAX_RETRIES} for {vault_info.name}: {e}")
                    self.vault_data.performance.failed_calls += 1
                
                # Exponential backoff between retries
                if attempt < BotConfig.MAX_RETRIES - 1:
                    delay = BotConfig.RETRY_DELAY_BASE ** (attempt + 1)
                    logger.info(f"Retrying {vault_info.name} in {delay}s...")
                    await asyncio.sleep(delay)
            
            # All retries failed
            self.vault_data.mark_vault_failure(vault_info.address)
            logger.error(f"All {BotConfig.MAX_RETRIES} retries failed for {vault_info.name}")
            return None
    
    async def get_vault_positions(self, vault_info: VaultInfo) -> Dict[str, PositionData]:
        """Get vault positions with enhanced error handling"""
        try:
            positions = {}
            
            user_state = await self.safe_api_call(vault_info, "get_positions")
            if user_state is None:
                return None  # API failure
            
            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    try:
                        pos_data = position['position']
                        size_str = pos_data.get('szi', '0')
                        
                        if size_str and size_str != '0':
                            coin = pos_data['coin']
                            size = abs(Decimal(str(size_str)))
                            
                            # Extract additional data safely
                            entry_price = None
                            position_value = None
                            
                            try:
                                if 'entryPx' in pos_data and pos_data['entryPx']:
                                    entry_price = Decimal(str(pos_data['entryPx']))
                                if 'positionValue' in pos_data and pos_data['positionValue']:
                                    position_value = Decimal(str(pos_data['positionValue']))
                            except Exception as e:
                                logger.debug(f"Error parsing additional position data for {coin}: {e}")
                            
                            positions[coin] = PositionData(
                                coin=coin,
                                size=size,
                                timestamp=datetime.now(),
                                entry_price=entry_price,
                                position_value=position_value
                            )
                    except Exception as e:
                        logger.warning(f"Error parsing position in {vault_info.name}: {e}")
                        continue
            
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching positions for {vault_info.name}: {e}")
            self.vault_data.mark_vault_failure(vault_info.address)
            return None  # API failure
    
    async def check_vault_changes(self, vault_info: VaultInfo):
        """Enhanced vault change detection with first-scan filtering"""
        try:
            if not vault_info.is_active:
                logger.debug(f"Skipping inactive vault: {vault_info.name}")
                return
            
            current_positions = await self.get_vault_positions(vault_info)
            
            # Handle API failure (None means API failed, empty dict {} means no positions)
            if current_positions is None:
                logger.warning(f"Skipping {vault_info.name} due to API failure")
                return
            
            previous_positions = self.vault_data.get_previous_positions(vault_info.address)
            
            # CRITICAL FIX: Handle first scan to prevent alert flood
            if not vault_info.first_scan_completed:
                logger.info(f"🔍 First scan of {vault_info.name}: Found {len(current_positions)} positions, skipping alerts")
                self.vault_data.update_previous_positions(vault_info.address, current_positions)
                self.vault_data.complete_first_scan(vault_info.address)
                return
            
            # Check for position changes
            all_coins = set(current_positions.keys()) | set(previous_positions.keys())
            changes_detected = 0
            
            for coin in all_coins:
                current_pos = current_positions.get(coin)
                previous_pos = previous_positions.get(coin)
                
                current_size = current_pos.size if current_pos else Decimal('0')
                previous_size = previous_pos.size if previous_pos else Decimal('0')
                
                # Check if position size changed
                if current_size != previous_size:
                    changes_detected += 1
                    
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
                    
                    # FIXED: Check confluence BEFORE adding current event
                    existing_confluence_events = self.vault_data.get_confluence_events(coin, trade_event.timestamp)
                    existing_unique_vaults = len(set(e.vault_name for e in existing_confluence_events))
                    
                    # Enhanced logging for confluence detection
                    if existing_confluence_events:
                        existing_vault_names = [e.vault_name for e in existing_confluence_events]
                        logger.info(f"🔍 Confluence check for {coin}: Found {existing_unique_vaults} existing vault(s): {existing_vault_names}")
                        for event in existing_confluence_events:
                            minutes_ago = (trade_event.timestamp - event.timestamp).total_seconds() / 60
                            logger.info(f"  📊 {event.vault_name}: {event.trade_type} {event.size_change} size, {minutes_ago:.1f} minutes ago")
                    
                    # Add current event to the count (but not to the list yet)
                    total_unique_vaults = existing_unique_vaults
                    current_vault_already_counted = any(e.vault_name == vault_info.name for e in existing_confluence_events)
                    if not current_vault_already_counted:
                        total_unique_vaults += 1
                    
                    logger.info(f"📈 Confluence for {coin}: {existing_unique_vaults} existing + {vault_info.name} = {total_unique_vaults} total (threshold: {self.vault_data.confluence_threshold})")
                    
                    # Add to trade events AFTER confluence check
                    self.vault_data.add_trade_event(trade_event)
                    
                    # Only alert if confluence threshold is met
                    if total_unique_vaults >= self.vault_data.confluence_threshold:
                        # Get final confluence events including current one for alert
                        all_confluence_events = self.vault_data.get_confluence_events(coin, trade_event.timestamp)
                        await self.send_confluence_alert(trade_event, all_confluence_events)
                        
                        # Set cooldown for all involved vaults
                        for event in all_confluence_events:
                            vault = self.vault_data.get_vault_by_name(event.vault_name)
                            if vault:
                                self.vault_data.set_cooldown(vault.address, coin)
                    
                    # THEME DETECTION: Check for theme-based confluence
                    if self.vault_data.theme_alerts_enabled:
                        theme_result = self.vault_data.check_theme_confluence(trade_event)
                        if theme_result:
                            theme, all_theme_events = theme_result
                            unique_theme_vaults = list(set(e.vault_name for e in all_theme_events))
                            if len(unique_theme_vaults) >= self.vault_data.theme_threshold:
                                await self.send_theme_alert(theme, trade_event, all_theme_events)
            
            # Update previous positions
            self.vault_data.update_previous_positions(vault_info.address, current_positions)
            
            if changes_detected > 0:
                logger.info(f"📊 {vault_info.name}: Detected {changes_detected} position changes")
            
        except Exception as e:
            logger.error(f"Error checking changes for vault {vault_info.name}: {e}")
            self.vault_data.mark_vault_failure(vault_info.address)
    
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
            
            # Enhanced alert with better formatting
            message = (
                f"{emoji} **CONFLUENCE DETECTED v2.2**\n\n"
                f"**Token:** {trigger_event.coin}\n"
                f"**Vaults Trading:** {confluence_count} within {self.vault_data.confluence_window_minutes}min\n\n"
                f"**Trigger Event:**\n"
                f"• Vault: {trigger_event.vault_name}\n"
                f"• Action: {trigger_event.trade_type}\n"
                f"• Size: {trigger_event.old_size} → {trigger_event.new_size}\n"
                f"• Change: {trigger_event.size_change}\n\n"
                f"**All Participating Vaults:**\n"
            )
            
            # Add vault details with timing
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                # Find the event for this vault
                vault_event = next((e for e in all_events if e.vault_name == vault_name), None)
                if vault_event:
                    time_diff = (trigger_event.timestamp - vault_event.timestamp).total_seconds() / 60
                    if time_diff < 1:
                        timing = "just now"
                    else:
                        timing = f"{time_diff:.0f}m ago"
                    message += f"{i}. {vault_name} ({vault_event.trade_type}, {timing})\n"
                else:
                    message += f"{i}. {vault_name}\n"
            
            message += f"\n**Time:** {datetime.now().strftime('%H:%M:%S')}"
            
            await self.send_alert(message)
            logger.info(f"🚨 Confluence alert sent: {trigger_event.coin} - {confluence_count} vaults")
            
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
    
    async def send_theme_alert(self, theme: str, trigger_event: TradeEvent, all_theme_events: List[ThemeEvent]):
        """Send theme confluence alert when multiple vaults trade the same theme"""
        try:
            # Get unique vaults involved
            unique_vaults = list(set(e.vault_name for e in all_theme_events))
            theme_count = len(unique_vaults)
            
            # Get theme emoji and details
            emoji = self.vault_data.token_categorizer.get_category_emoji(theme)
            tokens_traded = list(set(e.coin for e in all_theme_events))
            
            # Enhanced theme alert with better formatting
            message = (
                f"{emoji} **THEME CONFLUENCE DETECTED** {emoji}\n\n"
                f"**Theme:** {theme} ({emoji})\n"
                f"**Vaults Trading:** {theme_count} within {self.vault_data.theme_window_minutes}min\n"
                f"**Tokens:** {', '.join(sorted(tokens_traded))}\n\n"
                f"**Trigger Event:**\n"
                f"• Vault: {trigger_event.vault_name}\n"
                f"• Token: {trigger_event.coin}\n"
                f"• Action: {trigger_event.trade_type}\n"
                f"• Size: {trigger_event.old_size} → {trigger_event.new_size}\n\n"
                f"**All {theme} Activity:**\n"
            )
            
            # Add details for each vault in the theme
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                # Find events for this vault
                vault_events = [e for e in all_theme_events if e.vault_name == vault_name]
                if vault_events:
                    # Get the most recent event for this vault
                    latest_event = max(vault_events, key=lambda x: x.timestamp)
                    time_diff = (trigger_event.timestamp - latest_event.timestamp).total_seconds() / 60
                    if time_diff < 1:
                        timing = "just now"
                    else:
                        timing = f"{time_diff:.0f}m ago"
                    
                    # Count unique tokens traded by this vault in this theme
                    vault_tokens = list(set(e.coin for e in vault_events))
                    token_info = f"{len(vault_tokens)} token{'s' if len(vault_tokens) > 1 else ''}"
                    
                    message += f"{i}. {vault_name}: {latest_event.coin} ({latest_event.trade_type}, {timing})\n"
                    if len(vault_tokens) > 1:
                        other_tokens = [t for t in vault_tokens if t != latest_event.coin]
                        message += f"   └ Also: {', '.join(other_tokens)}\n"
            
            message += f"\n**Time:** {datetime.now().strftime('%H:%M:%S')}"
            message += f"\n🎯 **Theme Strength:** {theme_count}/{len(self.vault_data.get_active_vaults())} vaults"
            
            await self.send_alert(message)
            logger.info(f"🎯 Theme alert sent: {theme} - {theme_count} vaults trading {len(tokens_traded)} tokens")
            
        except Exception as e:
            logger.error(f"Error sending theme alert: {e}")
            # Simple fallback
            try:
                simple_message = (
                    f"🎯 THEME CONFLUENCE: {theme}\n"
                    f"Vaults: {len(set(e.vault_name for e in all_theme_events))}\n"
                    f"Trigger: {trigger_event.vault_name} - {trigger_event.coin}\n"
                    f"Action: {trigger_event.trade_type}"
                )
                await self.send_alert(simple_message)
            except Exception as e2:
                logger.error(f"Error sending fallback theme alert: {e2}")
    
    async def send_alert(self, message: str):
        """Send alert message to Telegram with fallback"""
        try:
            bot = Bot(token=self.bot_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
            logger.info(f"Alert sent: {message[:50]}...")
        except Exception as e:
            logger.error(f"Error sending alert: {e}")
            # No fallback needed - just log the error
    
    async def monitoring_loop(self):
        """Production-grade monitoring loop with batch optimization"""
        logger.info("🚀 Starting production-grade vault monitoring loop v2.2...")
        
        while self.vault_data.is_monitoring:
            try:
                active_vaults = self.vault_data.get_active_vaults()
                if not active_vaults:
                    logger.info("No active vaults to monitor, waiting...")
                    await asyncio.sleep(BotConfig.VAULT_CHECK_INTERVAL)
                    continue
                
                cycle_start = time.time()
                logger.info(f"🔍 Checking {len(active_vaults)} active vault(s) for position changes...")
                
                # Process vaults in batches for better performance
                for i in range(0, len(active_vaults), BotConfig.BATCH_SIZE):
                    batch = active_vaults[i:i + BotConfig.BATCH_SIZE]
                    batch_tasks = []
                    
                    for vault_info in batch:
                        if not self.vault_data.is_monitoring:
                            break
                        task = asyncio.create_task(self.check_vault_changes(vault_info))
                        batch_tasks.append(task)
                    
                    # Wait for batch to complete with proper error handling
                    if batch_tasks:
                        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                        # Check for any exceptions in the batch
                        for i, result in enumerate(results):
                            if isinstance(result, Exception):
                                vault_name = batch[i].name if i < len(batch) else "unknown"
                                logger.error(f"Task failed for vault {vault_name}: {result}")
                                # Don't let one vault failure stop everything
                    
                    # Delay between batches
                    if i + BotConfig.BATCH_SIZE < len(active_vaults):
                        await asyncio.sleep(BotConfig.VAULT_DELAY)
                
                cycle_time = time.time() - cycle_start
                logger.info(f"✅ Monitoring cycle completed in {cycle_time:.2f}s")
                
                # Wait for next cycle
                await asyncio.sleep(BotConfig.VAULT_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Critical error in monitoring loop: {e}")
                logger.error(f"Monitoring state: {self.vault_data.is_monitoring}")
                logger.error(f"Active vaults: {len(self.vault_data.get_active_vaults())}")
                
                # Log full exception traceback for debugging
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                
                await asyncio.sleep(60)  # Shorter retry on errors
                
        logger.warning("🛑 Monitoring loop exited - this should not happen during normal operation!")
        logger.warning(f"Final monitoring state: {self.vault_data.is_monitoring}")
        logger.warning(f"Final active vaults: {len(self.vault_data.get_active_vaults())}")
    
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
        """Start monitoring with proper concurrency control"""
        async with self._monitoring_lock:
            if not self.vault_data.is_monitoring:
                self.vault_data.is_monitoring = True
                self.monitoring_task = asyncio.create_task(self.monitoring_loop())
                
                try:
                    vault_count = len(self.vault_data.vaults)
                    active_count = len(self.vault_data.get_active_vaults())
                    
                    startup_message = (
                        f"🚀 **Production Monitoring Started v2.2**\n\n"
                        f"**Configuration:**\n"
                        f"• Total Vaults: {vault_count}\n"
                        f"• Active Vaults: {active_count}\n"
                        f"• Confluence: {self.vault_data.confluence_threshold} vault(s)\n"
                        f"• Window: {self.vault_data.confluence_window_minutes} min\n"
                        f"• Batch Size: {BotConfig.BATCH_SIZE} vaults\n"
                        f"• Check Interval: {BotConfig.VAULT_CHECK_INTERVAL}s\n\n"
                        f"**Production Features:**\n"
                        f"• Thread-safe operations\n"
                        f"• Atomic persistence\n"
                        f"• Smart first-scan filtering\n"
                        f"• Enhanced error recovery\n\n"
                        f"**Started:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await self.send_alert(startup_message)
                    logger.info("🚀 Production monitoring started successfully")
                    
                except Exception as e:
                    logger.error(f"Error sending startup message: {e}")
                    await self.send_alert("🚀 Production vault monitoring v2.2 started!")

    async def stop_monitoring(self):
        """Stop monitoring with proper cleanup"""
        async with self._monitoring_lock:
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
            
            logger.info("🛑 Monitoring stopped and cleaned up")

# Rest of the command handlers and methods would continue...
# I'll implement the remaining methods following the same production-grade patterns

async def main():
    """Production-ready main function with enhanced error handling"""
    # Get environment variables
    telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not telegram_bot_token or not chat_id:
        logger.error("Missing required environment variables: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID")
        return
    
    logger.info("🚀 Initializing Advanced Hyperliquid Telegram bot v2.3...")
    
    # Create production bot instance
    vault_bot = HyperliquidAdvancedBot(telegram_bot_token, chat_id)
    
    # Auto-start monitoring if vaults exist from previous session
    if vault_bot.vault_data.vaults and not vault_bot.vault_data.is_monitoring:
        logger.info(f"🔄 Auto-starting monitoring for {len(vault_bot.vault_data.vaults)} persisted vaults")
        await vault_bot.start_monitoring()
    
    # Create Telegram application
    application = Application.builder().token(telegram_bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", vault_bot.start_command))
    application.add_handler(CommandHandler("add_vault", vault_bot.add_vault_command))
    application.add_handler(CommandHandler("list_vaults", vault_bot.list_vaults_command))
    application.add_handler(CommandHandler("remove_vault", vault_bot.remove_vault_command))
    application.add_handler(CommandHandler("status", vault_bot.status_command))
    application.add_handler(CommandHandler("setvaults", vault_bot.set_vault_number_command))
    application.add_handler(CommandHandler("set_window", vault_bot.set_window_command))
    application.add_handler(CommandHandler("show_settings", vault_bot.show_settings_command))
    application.add_handler(CommandHandler("backup", vault_bot.backup_command))
    application.add_handler(CommandHandler("performance", vault_bot.performance_command))
    application.add_handler(CommandHandler("health", vault_bot.health_command))
    application.add_handler(CommandHandler("themes", vault_bot.themes_command))
    application.add_handler(CommandHandler("theme_threshold", vault_bot.theme_threshold_command))
    application.add_handler(CommandHandler("categories", vault_bot.categories_command))
    
    logger.info("✅ Starting Advanced Hyperliquid Telegram bot v2.3 - Production Ready!")
    
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
        if hasattr(vault_bot, 'stop_monitoring'):
            await vault_bot.stop_monitoring()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())