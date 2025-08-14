#!/usr/bin/env python3
"""
🎯 Clean Hyperliquid Whale Tracking Bot using CoinGlass API
Built for professional whale tracking with theme detection
"""

import asyncio
import logging
import json
import time
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, asdict
import threading
import requests
from collections import defaultdict

# Telegram imports
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes, Update

# Configure professional logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===========================
# CONFIGURATION
# ===========================

class BotConfig:
    """Clean configuration for CoinGlass whale tracking"""
    
    # CoinGlass API settings
    COINGLASS_API_BASE = "https://fapi.coinglass.com"
    API_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    # Monitoring intervals
    CHECK_INTERVAL = 60  # Check every minute (CoinGlass updates ≤ 1min)
    BATCH_SIZE = 5  # Process vaults in batches
    
    # Theme detection settings
    DEFAULT_THEME_THRESHOLD = 2
    DEFAULT_THEME_WINDOW = 15  # minutes
    DEFAULT_CONFLUENCE_THRESHOLD = 2
    DEFAULT_CONFLUENCE_WINDOW = 10  # minutes
    
    # Data persistence
    VAULT_DATA_FILE = "coinglass_vault_data.json"
    BACKUP_FILE = "coinglass_vault_backup.json"
    
    # Rate limiting
    MIN_SAVE_INTERVAL = 5  # seconds

# ===========================
# DATA MODELS
# ===========================

@dataclass
class VaultInfo:
    """Clean vault information model"""
    address: str
    name: str
    is_active: bool = True
    last_check: Optional[datetime] = None
    consecutive_failures: int = 0
    
    def __str__(self):
        return f"{self.name} ({self.address[:8]}...)"
    
    def to_dict(self):
        return {
            'address': self.address,
            'name': self.name,
            'is_active': self.is_active,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'consecutive_failures': self.consecutive_failures
        }
    
    @classmethod
    def from_dict(cls, data):
        last_check = None
        if data.get('last_check'):
            try:
                last_check = datetime.fromisoformat(data['last_check'])
            except:
                pass
        
        return cls(
            address=data['address'],
            name=data['name'],
            is_active=data.get('is_active', True),
            last_check=last_check,
            consecutive_failures=data.get('consecutive_failures', 0)
        )

@dataclass
class Position:
    """Position data from CoinGlass"""
    vault_address: str
    vault_name: str
    symbol: str
    size: Decimal
    entry_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class TradeEvent:
    """Clean trade event model"""
    vault_name: str
    vault_address: str
    symbol: str
    old_size: Decimal
    new_size: Decimal
    timestamp: datetime
    entry_price: Optional[Decimal] = None
    
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
    """Theme-based trading event"""
    theme: str
    vault_name: str
    vault_address: str
    symbol: str
    trade_type: str
    size_change: Decimal
    timestamp: datetime

# ===========================
# TOKEN CATEGORIZATION
# ===========================

class TokenCategorizer:
    """Advanced token categorization for theme detection"""
    
    def __init__(self):
        self.categories = {
            'AI': {
                'tokens': ['ARKM', 'FET', 'RNDR', 'TAO', 'OCEAN', 'GLM', 'AI', 'AGIX', 'PHB', 'CTX', 'AKT', 'NMR'],
                'emoji': '🤖'
            },
            'GAMING': {
                'tokens': ['IMX', 'GALA', 'SAND', 'MANA', 'AXS', 'ILV', 'ENJ', 'FLOW', 'RON', 'YGG', 'PIXEL', 'BEAM'],
                'emoji': '🎮'
            },
            'DEFI': {
                'tokens': ['UNI', 'AAVE', 'SNX', 'CRV', 'COMP', 'YFI', 'BAL', '1INCH', 'DYDX', 'GMX', 'GNS', 'JOE'],
                'emoji': '🏦'
            },
            'MEME': {
                'tokens': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'BOME', 'POPCAT', 'MEW', 'PNUT'],
                'emoji': '🐸'
            },
            'LAYER1': {
                'tokens': ['BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'ATOM', 'NEAR', 'FTM', 'ALGO', 'MATIC', 'AVAX', 'LUNA'],
                'emoji': '⛓️'
            },
            'LAYER2': {
                'tokens': ['ARB', 'OP', 'MATIC', 'LRC', 'ZK', 'METIS', 'BOBA', 'MANTA'],
                'emoji': '🔗'
            },
            'ORACLES': {
                'tokens': ['LINK', 'BAND', 'TRB', 'API3', 'UMA', 'DIA'],
                'emoji': '🔮'
            },
            'INFRASTRUCTURE': {
                'tokens': ['GRT', 'FIL', 'AR', 'STORJ', 'THETA', 'LPT', 'ANKR'],
                'emoji': '🏗️'
            },
            'PRIVACY': {
                'tokens': ['XMR', 'ZEC', 'SCRT', 'ROSE', 'NYM', 'RAIL'],
                'emoji': '🕵️'
            },
            'RWA': {
                'tokens': ['RIO', 'TRU', 'CFG', 'MKR', 'RWA', 'ONDO', 'POLYX'],
                'emoji': '🏠'
            }
        }
        
        # Create reverse lookup
        self.token_to_category = {}
        for category, data in self.categories.items():
            for token in data['tokens']:
                self.token_to_category[token.upper()] = category
    
    def get_token_category(self, token: str) -> Optional[str]:
        return self.token_to_category.get(token.upper())
    
    def get_category_emoji(self, category: str) -> str:
        return self.categories.get(category, {}).get('emoji', '📊')
    
    def get_all_categories(self) -> List[str]:
        return list(self.categories.keys())

# ===========================
# COINGLASS API CLIENT
# ===========================

class CoinGlassClient:
    """Professional CoinGlass API client"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = BotConfig.COINGLASS_API_BASE
        self.session = requests.Session()
        self.session.headers.update({
            'CG-API-KEY': api_key,
            'Content-Type': 'application/json'
        })
    
    async def get_hyperliquid_whale_positions(self, address: str) -> Optional[List[Dict]]:
        """Get whale positions for a specific Hyperliquid address"""
        try:
            url = f"{self.base_url}/api/hyperliquid/whale-position"
            params = {'address': address}
            
            response = await self._make_request(url, params)
            if response and response.get('success'):
                return response.get('data', [])
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching whale positions for {address}: {e}")
            return None
    
    async def get_hyperliquid_whale_alerts(self, limit: int = 100) -> Optional[List[Dict]]:
        """Get recent whale alerts from Hyperliquid"""
        try:
            url = f"{self.base_url}/api/hyperliquid/whale-alert"
            params = {'limit': limit}
            
            response = await self._make_request(url, params)
            if response and response.get('success'):
                return response.get('data', [])
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching whale alerts: {e}")
            return None
    
    async def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make async HTTP request with retries"""
        for attempt in range(BotConfig.MAX_RETRIES):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: self.session.get(url, params=params, timeout=BotConfig.API_TIMEOUT)
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limited
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(f"API request failed: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt < BotConfig.MAX_RETRIES - 1:
                    await asyncio.sleep(BotConfig.RETRY_DELAY * (attempt + 1))
        
        return None

# ===========================
# VAULT DATA MANAGER
# ===========================

class VaultDataManager:
    """Thread-safe vault data management"""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._vaults: Dict[str, VaultInfo] = {}
        self._previous_positions: Dict[str, Dict[str, Position]] = {}
        self._trade_events: List[TradeEvent] = []
        self._theme_events: List[ThemeEvent] = []
        self._last_save_time = 0
        
        # Settings
        self._theme_threshold = BotConfig.DEFAULT_THEME_THRESHOLD
        self._theme_window = BotConfig.DEFAULT_THEME_WINDOW
        self._confluence_threshold = BotConfig.DEFAULT_CONFLUENCE_THRESHOLD
        self._confluence_window = BotConfig.DEFAULT_CONFLUENCE_WINDOW
        self._theme_alerts_enabled = True
        
        # Initialize categorizer
        self._categorizer = TokenCategorizer()
        
        # Load persisted data
        self._load_data()
    
    def add_vault(self, address: str, name: str) -> Tuple[bool, str]:
        """Add vault with validation"""
        with self._lock:
            if not address.startswith('0x') or len(address) != 42:
                return False, "Invalid Ethereum address format"
            
            if any(v.address.lower() == address.lower() for v in self._vaults.values()):
                return False, "Vault already exists"
            
            vault = VaultInfo(address=address.lower(), name=name)
            self._vaults[name] = vault
            self._previous_positions[address.lower()] = {}
            
            self._safe_save()
            logger.info(f"Added vault: {vault}")
            return True, f"Successfully added {name}"
    
    def get_active_vaults(self) -> List[VaultInfo]:
        """Get list of active vaults"""
        with self._lock:
            return [v for v in self._vaults.values() if v.is_active]
    
    def add_trade_event(self, event: TradeEvent):
        """Add trade event with cleanup"""
        with self._lock:
            self._trade_events.append(event)
            cutoff = datetime.now() - timedelta(minutes=self._confluence_window)
            self._trade_events = [e for e in self._trade_events if e.timestamp > cutoff]
    
    def check_confluence(self, trade_event: TradeEvent) -> Optional[List[TradeEvent]]:
        """Check for token confluence"""
        with self._lock:
            cutoff = trade_event.timestamp - timedelta(minutes=self._confluence_window)
            existing_events = [
                e for e in self._trade_events 
                if e.symbol == trade_event.symbol and e.timestamp > cutoff
            ]
            
            unique_vaults = len(set(e.vault_name for e in existing_events))
            current_vault_counted = any(e.vault_name == trade_event.vault_name for e in existing_events)
            total_vaults = unique_vaults + (0 if current_vault_counted else 1)
            
            self.add_trade_event(trade_event)
            
            if total_vaults >= self._confluence_threshold:
                all_events = [
                    e for e in self._trade_events 
                    if e.symbol == trade_event.symbol and e.timestamp > cutoff
                ]
                return all_events
            
            return None
    
    def check_theme_confluence(self, trade_event: TradeEvent) -> Optional[Tuple[str, List[ThemeEvent]]]:
        """Check for theme confluence"""
        with self._lock:
            category = self._categorizer.get_token_category(trade_event.symbol)
            if not category or not self._theme_alerts_enabled:
                return None
            
            theme_event = ThemeEvent(
                theme=category,
                vault_name=trade_event.vault_name,
                vault_address=trade_event.vault_address,
                symbol=trade_event.symbol,
                trade_type=trade_event.trade_type,
                size_change=trade_event.size_change,
                timestamp=trade_event.timestamp
            )
            
            cutoff = trade_event.timestamp - timedelta(minutes=self._theme_window)
            existing_theme_events = [
                e for e in self._theme_events 
                if e.theme == category and e.timestamp > cutoff
            ]
            
            unique_vaults = len(set(e.vault_name for e in existing_theme_events))
            current_vault_counted = any(e.vault_name == trade_event.vault_name for e in existing_theme_events)
            total_vaults = unique_vaults + (0 if current_vault_counted else 1)
            
            # Add theme event
            self._theme_events.append(theme_event)
            cutoff_cleanup = datetime.now() - timedelta(minutes=self._theme_window)
            self._theme_events = [e for e in self._theme_events if e.timestamp > cutoff_cleanup]
            
            if total_vaults >= self._theme_threshold:
                all_theme_events = [
                    e for e in self._theme_events 
                    if e.theme == category and e.timestamp > cutoff
                ]
                return category, all_theme_events
            
            return None
    
    @property
    def categorizer(self) -> TokenCategorizer:
        return self._categorizer
    
    # Properties for settings
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
    def theme_alerts_enabled(self) -> bool:
        with self._lock:
            return self._theme_alerts_enabled
    
    @theme_alerts_enabled.setter
    def theme_alerts_enabled(self, value: bool):
        with self._lock:
            self._theme_alerts_enabled = value
            self._safe_save()
    
    def _safe_save(self):
        """Rate-limited save to prevent excessive I/O"""
        current_time = time.time()
        if current_time - self._last_save_time < BotConfig.MIN_SAVE_INTERVAL:
            return
        
        self._last_save_time = current_time
        self._save_data()
    
    def _save_data(self):
        """Save vault data atomically"""
        try:
            data = {
                'vaults': {name: vault.to_dict() for name, vault in self._vaults.items()},
                'settings': {
                    'theme_threshold': self._theme_threshold,
                    'theme_window': self._theme_window,
                    'confluence_threshold': self._confluence_threshold,
                    'confluence_window': self._confluence_window,
                    'theme_alerts_enabled': self._theme_alerts_enabled
                },
                'saved_at': datetime.now().isoformat(),
                'version': '3.0-coinglass'
            }
            
            # Atomic write
            temp_file = f"{BotConfig.VAULT_DATA_FILE}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Backup existing file
            if os.path.exists(BotConfig.VAULT_DATA_FILE):
                try:
                    os.rename(BotConfig.VAULT_DATA_FILE, BotConfig.BACKUP_FILE)
                except:
                    pass
            
            os.rename(temp_file, BotConfig.VAULT_DATA_FILE)
            logger.info(f"Saved {len(self._vaults)} vaults to storage")
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def _load_data(self):
        """Load vault data with fallback"""
        try:
            data = None
            
            # Try primary file
            if os.path.exists(BotConfig.VAULT_DATA_FILE):
                try:
                    with open(BotConfig.VAULT_DATA_FILE, 'r') as f:
                        data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load primary file: {e}")
            
            # Try backup
            if not data and os.path.exists(BotConfig.BACKUP_FILE):
                try:
                    with open(BotConfig.BACKUP_FILE, 'r') as f:
                        data = json.load(f)
                    logger.info("Loaded from backup file")
                except Exception as e:
                    logger.warning(f"Failed to load backup: {e}")
            
            if data:
                # Load vaults
                for name, vault_dict in data.get('vaults', {}).items():
                    self._vaults[name] = VaultInfo.from_dict(vault_dict)
                    self._previous_positions[vault_dict['address']] = {}
                
                # Load settings
                settings = data.get('settings', {})
                self._theme_threshold = settings.get('theme_threshold', BotConfig.DEFAULT_THEME_THRESHOLD)
                self._theme_window = settings.get('theme_window', BotConfig.DEFAULT_THEME_WINDOW)
                self._confluence_threshold = settings.get('confluence_threshold', BotConfig.DEFAULT_CONFLUENCE_THRESHOLD)
                self._confluence_window = settings.get('confluence_window', BotConfig.DEFAULT_CONFLUENCE_WINDOW)
                self._theme_alerts_enabled = settings.get('theme_alerts_enabled', True)
                
                logger.info(f"Loaded {len(self._vaults)} vaults from storage")
            else:
                logger.info("No existing data found - starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading data: {e}")

# ===========================
# MAIN BOT CLASS
# ===========================

class CoinGlassWhaleBot:
    """Clean CoinGlass-powered whale tracking bot"""
    
    def __init__(self, telegram_token: str, chat_id: str, coinglass_api_key: str):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.coinglass_client = CoinGlassClient(coinglass_api_key)
        self.vault_data = VaultDataManager()
        
        # Monitoring state
        self._is_monitoring = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._monitoring_lock = asyncio.Lock()
        
        logger.info("🎯 CoinGlass Whale Bot initialized")
    
    async def start_monitoring(self):
        """Start monitoring all vaults"""
        async with self._monitoring_lock:
            if self._is_monitoring:
                logger.warning("Monitoring already active")
                return
            
            self._is_monitoring = True
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            
            await self.send_alert("🚀 Clean CoinGlass Whale Bot v3.0 started!")
            logger.info("📊 Monitoring started")
    
    async def stop_monitoring(self):
        """Stop monitoring with cleanup"""
        async with self._monitoring_lock:
            self._is_monitoring = False
            
            if self._monitoring_task:
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
                self._monitoring_task = None
            
            logger.info("🛑 Monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("🔄 Starting monitoring loop")
        
        while self._is_monitoring:
            try:
                active_vaults = self.vault_data.get_active_vaults()
                if not active_vaults:
                    logger.warning("No active vaults to monitor")
                    await asyncio.sleep(BotConfig.CHECK_INTERVAL)
                    continue
                
                logger.info(f"📊 Checking {len(active_vaults)} vaults...")
                
                # Process vaults in batches
                for i in range(0, len(active_vaults), BotConfig.BATCH_SIZE):
                    batch = active_vaults[i:i + BotConfig.BATCH_SIZE]
                    batch_tasks = []
                    
                    for vault in batch:
                        task = asyncio.create_task(self._check_vault(vault))
                        batch_tasks.append(task)
                    
                    # Process batch
                    if batch_tasks:
                        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                        for j, result in enumerate(results):
                            if isinstance(result, Exception):
                                vault_name = batch[j].name if j < len(batch) else "unknown"
                                logger.error(f"Vault {vault_name} failed: {result}")
                    
                    # Small delay between batches
                    if i + BotConfig.BATCH_SIZE < len(active_vaults):
                        await asyncio.sleep(2)
                
                logger.info(f"✅ Vault check cycle completed")
                await asyncio.sleep(BotConfig.CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)  # Shorter retry on errors
    
    async def _check_vault(self, vault: VaultInfo):
        """Check individual vault for position changes"""
        try:
            logger.debug(f"🔍 Checking vault: {vault.name}")
            
            # Get current positions from CoinGlass
            positions_data = await self.coinglass_client.get_hyperliquid_whale_positions(vault.address)
            
            if positions_data is None:
                vault.consecutive_failures += 1
                logger.warning(f"Failed to get positions for {vault.name} (failures: {vault.consecutive_failures})")
                return
            
            # Reset failure count on success
            vault.consecutive_failures = 0
            vault.last_check = datetime.now()
            
            # Convert to Position objects
            current_positions = {}
            for pos_data in positions_data:
                symbol = pos_data.get('symbol', '').replace('USDT', '').replace('-USD', '')
                if symbol:
                    position = Position(
                        vault_address=vault.address,
                        vault_name=vault.name,
                        symbol=symbol,
                        size=Decimal(str(pos_data.get('position_size', 0))),
                        entry_price=Decimal(str(pos_data.get('entry_price', 0))) if pos_data.get('entry_price') else None,
                        unrealized_pnl=Decimal(str(pos_data.get('unrealized_pnl', 0))) if pos_data.get('unrealized_pnl') else None
                    )
                    current_positions[symbol] = position
            
            # Compare with previous positions
            previous_positions = self.vault_data._previous_positions.get(vault.address, {})
            changes_detected = 0
            
            # Check for changes
            all_symbols = set(current_positions.keys()) | set(previous_positions.keys())
            
            for symbol in all_symbols:
                old_position = previous_positions.get(symbol)
                new_position = current_positions.get(symbol)
                
                old_size = old_position.size if old_position else Decimal('0')
                new_size = new_position.size if new_position else Decimal('0')
                
                # Detect significant changes (avoid noise)
                if abs(new_size - old_size) > Decimal('0.1'):  # Minimum change threshold
                    changes_detected += 1
                    
                    # Create trade event
                    trade_event = TradeEvent(
                        vault_name=vault.name,
                        vault_address=vault.address,
                        symbol=symbol,
                        old_size=old_size,
                        new_size=new_size,
                        timestamp=datetime.now(),
                        entry_price=new_position.entry_price if new_position else None
                    )
                    
                    logger.info(f"📈 {vault.name}: {symbol} {trade_event.trade_type} - {old_size} → {new_size}")
                    
                    # Check for confluence
                    confluence_events = self.vault_data.check_confluence(trade_event)
                    if confluence_events:
                        await self._send_confluence_alert(trade_event, confluence_events)
                    
                    # Check for theme confluence
                    theme_result = self.vault_data.check_theme_confluence(trade_event)
                    if theme_result:
                        theme, theme_events = theme_result
                        await self._send_theme_alert(theme, trade_event, theme_events)
            
            # Update previous positions
            self.vault_data._previous_positions[vault.address] = current_positions
            
            if changes_detected > 0:
                logger.info(f"📊 {vault.name}: Detected {changes_detected} position changes")
            
        except Exception as e:
            logger.error(f"Error checking vault {vault.name}: {e}")
            vault.consecutive_failures += 1
    
    async def _send_confluence_alert(self, trigger_event: TradeEvent, all_events: List[TradeEvent]):
        """Send token confluence alert"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_events))
            confluence_count = len(unique_vaults)
            
            # Determine emoji based on action
            emoji = "🟢" if trigger_event.trade_type == "OPEN" else "🔴" if trigger_event.trade_type == "CLOSE" else "📈"
            
            message = (
                f"{emoji} **CONFLUENCE DETECTED** 🎯\n\n"
                f"**Token:** {trigger_event.symbol}\n"
                f"**Vaults Trading:** {confluence_count} within {self.vault_data._confluence_window}min\n\n"
                f"**Trigger Event:**\n"
                f"• Vault: {trigger_event.vault_name}\n"
                f"• Action: {trigger_event.trade_type}\n"
                f"• Size: {trigger_event.old_size} → {trigger_event.new_size}\n\n"
                f"**All Participating Vaults:**\n"
            )
            
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                vault_event = next((e for e in all_events if e.vault_name == vault_name), None)
                if vault_event:
                    time_diff = (trigger_event.timestamp - vault_event.timestamp).total_seconds() / 60
                    timing = "just now" if time_diff < 1 else f"{time_diff:.0f}m ago"
                    message += f"{i}. {vault_name} ({vault_event.trade_type}, {timing})\n"
            
            message += f"\n**Time:** {datetime.now().strftime('%H:%M:%S')}"
            
            await self.send_alert(message)
            logger.info(f"🚨 Confluence alert sent: {trigger_event.symbol} - {confluence_count} vaults")
            
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")
    
    async def _send_theme_alert(self, theme: str, trigger_event: TradeEvent, all_theme_events: List[ThemeEvent]):
        """Send theme confluence alert"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_theme_events))
            theme_count = len(unique_vaults)
            
            emoji = self.vault_data.categorizer.get_category_emoji(theme)
            tokens_traded = list(set(e.symbol for e in all_theme_events))
            
            message = (
                f"{emoji} **THEME CONFLUENCE DETECTED** {emoji}\n\n"
                f"**Theme:** {theme} ({emoji})\n"
                f"**Vaults Trading:** {theme_count} within {self.vault_data._theme_window}min\n"
                f"**Tokens:** {', '.join(sorted(tokens_traded))}\n\n"
                f"**Trigger Event:**\n"
                f"• Vault: {trigger_event.vault_name}\n"
                f"• Token: {trigger_event.symbol}\n"
                f"• Action: {trigger_event.trade_type}\n"
                f"• Size: {trigger_event.old_size} → {trigger_event.new_size}\n\n"
                f"**All {theme} Activity:**\n"
            )
            
            for i, vault_name in enumerate(sorted(unique_vaults), 1):
                vault_events = [e for e in all_theme_events if e.vault_name == vault_name]
                if vault_events:
                    latest_event = max(vault_events, key=lambda x: x.timestamp)
                    time_diff = (trigger_event.timestamp - latest_event.timestamp).total_seconds() / 60
                    timing = "just now" if time_diff < 1 else f"{time_diff:.0f}m ago"
                    message += f"{i}. {vault_name}: {latest_event.symbol} ({latest_event.trade_type}, {timing})\n"
            
            message += f"\n**Time:** {datetime.now().strftime('%H:%M:%S')}"
            message += f"\n🎯 **Theme Strength:** {theme_count}/{len(self.vault_data.get_active_vaults())} vaults"
            
            await self.send_alert(message)
            logger.info(f"🎯 Theme alert sent: {theme} - {theme_count} vaults trading {len(tokens_traded)} tokens")
            
        except Exception as e:
            logger.error(f"Error sending theme alert: {e}")
    
    async def send_alert(self, message: str):
        """Send alert to Telegram"""
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            logger.error(f"Error sending alert: {e}")
    
    # Telegram command handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            vault_count = len(self.vault_data.get_active_vaults())
            
            message = (
                "🎯 **Clean CoinGlass Whale Bot v3.0**\n\n"
                "🚀 **Features:**\n"
                "• CoinGlass API integration\n"
                "• Real-time whale tracking\n"
                "• Theme confluence detection\n"
                "• Professional-grade reliability\n\n"
                "**Commands:**\n"
                "/status - Bot status\n"
                "/vaults - List tracked vaults\n"
                "/themes - Theme detection settings\n"
                "/start_monitoring - Start tracking\n"
                "/stop_monitoring - Stop tracking\n\n"
                f"**Current Status:**\n"
                f"• Vaults: {vault_count} tracked\n"
                f"• Monitoring: {'🟢 Active' if self._is_monitoring else '🔴 Stopped'}\n"
                f"• Data Source: CoinGlass API\n\n"
                "🎯 Ready for professional whale tracking!"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("🎯 Clean CoinGlass Whale Bot v3.0 - Ready!")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        try:
            vault_count = len(self.vault_data.get_active_vaults())
            
            message = (
                f"📊 **Bot Status**\n\n"
                f"**Monitoring:** {'🟢 Active' if self._is_monitoring else '🔴 Stopped'}\n"
                f"**Vaults:** {vault_count} tracked\n"
                f"**Theme Alerts:** {'🟢 Enabled' if self.vault_data.theme_alerts_enabled else '🔴 Disabled'}\n"
                f"**Theme Threshold:** {self.vault_data.theme_threshold} vaults\n"
                f"**Check Interval:** {BotConfig.CHECK_INTERVAL}s\n"
                f"**Data Source:** CoinGlass API\n"
                f"**Version:** 3.0-coinglass\n\n"
                f"**Performance:**\n"
                f"• Batch processing: {BotConfig.BATCH_SIZE} vaults\n"
                f"• Real-time updates ≤ 1 minute\n"
                f"• Professional-grade reliability"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await update.message.reply_text("Error getting status")
    
    async def start_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_monitoring command"""
        try:
            if self._is_monitoring:
                await update.message.reply_text("📊 Monitoring is already active!")
                return
            
            await self.start_monitoring()
            await update.message.reply_text("🚀 Monitoring started!")
            
        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")
            await update.message.reply_text("Error starting monitoring")
    
    async def stop_monitoring_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_monitoring command"""
        try:
            if not self._is_monitoring:
                await update.message.reply_text("📊 Monitoring is already stopped!")
                return
            
            await self.stop_monitoring()
            await update.message.reply_text("🛑 Monitoring stopped!")
            
        except Exception as e:
            logger.error(f"Error stopping monitoring: {e}")
            await update.message.reply_text("Error stopping monitoring")
    
    async def vaults_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /vaults command"""
        try:
            vaults = self.vault_data.get_active_vaults()
            
            if not vaults:
                await update.message.reply_text("No vaults configured yet")
                return
            
            message = f"📊 **Tracked Vaults ({len(vaults)})**\n\n"
            
            for i, vault in enumerate(vaults, 1):
                status = "🟢" if vault.is_active else "🔴"
                last_check = vault.last_check.strftime('%H:%M:%S') if vault.last_check else "Never"
                message += f"{i}. {status} **{vault.name}**\n"
                message += f"   └ {vault.address[:10]}...{vault.address[-6:]}\n"
                message += f"   └ Last check: {last_check}\n\n"
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error in vaults command: {e}")
            await update.message.reply_text("Error listing vaults")

# Initialize default vaults from your list
DEFAULT_VAULTS = [
    ("0x56498e5f90c14060499b62b6f459b3e3fb9280c5", "TOPDOG"),
    ("0x5f42236dfb81cba77bf34698b2242826659d1275", "taptrade"),
    ("0x0a9e080547d3169b5ce8df28c2267b753205722b", "spitfire"),
    ("0x2b804617c6f63c040377e95bb276811747006f4b", "systemic"),
    ("0x4430bd573cb9a4eb33e61ece030ad6e5edaa0476", "amber"),
    ("0x27d33e77c8e6335089f56e399bf706ae9ad402b9", "marty"),
    ("0xa0ac2efa25448badf168afa445a5fe15eb966f16", "market"),
    ("0x8d599f4a77eaa7d4569735a0be656aab8efbf101", "stabilizer"),
    ("0x3005fade4c0df5e1cd187d7062da359416f0eb8e", "delta"),
    ("0x8af700ba841f30e0a3fcb0ee4c4a9d223e1efa05", "top2"),
    ("0x15b325660a1c4a9582a7d834c31119c0cb9e3a42", "top3"),
    ("0x2ba553d9f990a3b66b03b2dc0d030dfc1c061036", "top4"),
    ("0x020ca66c30bec2c4fe3861a94e4db4a498a35872", "top5ethhype"),
]

# ===========================
# MAIN FUNCTION
# ===========================

async def main():
    """Main function to run the CoinGlass whale bot"""
    # Get environment variables
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    coinglass_api_key = os.getenv('COINGLASS_API_KEY')
    
    if not all([telegram_token, chat_id, coinglass_api_key]):
        logger.error("Missing required environment variables:")
        logger.error("- TELEGRAM_BOT_TOKEN")
        logger.error("- TELEGRAM_CHAT_ID") 
        logger.error("- COINGLASS_API_KEY")
        return
    
    logger.info("🚀 Initializing Clean CoinGlass Whale Bot v3.0...")
    
    # Create bot instance
    whale_bot = CoinGlassWhaleBot(telegram_token, chat_id, coinglass_api_key)
    
    # Initialize default vaults if none exist
    if len(whale_bot.vault_data.get_active_vaults()) == 0:
        logger.info("🔧 Initializing default vaults...")
        for address, name in DEFAULT_VAULTS:
            success, message = whale_bot.vault_data.add_vault(address, name)
            if success:
                logger.info(f"✅ Added: {name}")
            else:
                logger.warning(f"❌ Failed to add {name}: {message}")
    
    # Create Telegram application
    application = Application.builder().token(telegram_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", whale_bot.start_command))
    application.add_handler(CommandHandler("status", whale_bot.status_command))
    application.add_handler(CommandHandler("vaults", whale_bot.vaults_command))
    application.add_handler(CommandHandler("start_monitoring", whale_bot.start_monitoring_command))
    application.add_handler(CommandHandler("stop_monitoring", whale_bot.stop_monitoring_command))
    
    logger.info("✅ Starting Clean CoinGlass Whale Bot v3.0!")
    
    try:
        # Auto-start monitoring
        if whale_bot.vault_data.get_active_vaults():
            logger.info("🔄 Auto-starting monitoring...")
            await whale_bot.start_monitoring()
        
        # Start the bot
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        # Cleanup
        await whale_bot.stop_monitoring()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())