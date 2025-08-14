#!/usr/bin/env python3
"""
🎯 Budget-Optimized CoinGlass Whale Bot v3.0
Designed for cost-effective whale tracking with longer check intervals
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
# BUDGET-OPTIMIZED CONFIGURATION
# ===========================

class BudgetBotConfig:
    """Budget-optimized configuration for different CoinGlass plans"""
    
    # CoinGlass API settings
    COINGLASS_API_BASE = "https://fapi.coinglass.com"
    API_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    # Budget-friendly plan configurations
    PLANS = {
        'hobbyist': {
            'cost_per_month': 29,
            'requests_per_minute': 30,
            'recommended_check_interval': 900,  # 15 minutes
            'max_check_interval': 3600,        # 1 hour max
            'min_check_interval': 600,         # 10 minutes min
            'description': 'Perfect for learning patterns ($29/mo)'
        },
        'startup': {
            'cost_per_month': 79,
            'requests_per_minute': 80,
            'recommended_check_interval': 300,  # 5 minutes
            'max_check_interval': 1800,        # 30 minutes max
            'min_check_interval': 180,         # 3 minutes min
            'description': 'Great balance of cost vs performance ($79/mo)'
        },
        'standard': {
            'cost_per_month': 299,
            'requests_per_minute': 300,
            'recommended_check_interval': 120,  # 2 minutes
            'max_check_interval': 600,         # 10 minutes max
            'min_check_interval': 60,          # 1 minute min
            'description': 'For active trading ($299/mo)'
        }
    }
    
    # Default to startup plan (best value)
    DEFAULT_PLAN = 'startup'
    
    # Data persistence
    VAULT_DATA_FILE = "budget_vault_data.json"
    BACKUP_FILE = "budget_vault_backup.json"
    
    # Rate limiting and batch processing
    MIN_SAVE_INTERVAL = 10  # Reduced save frequency
    BATCH_SIZE = 3  # Smaller batches for budget plans
    
    # Theme detection (optimized for longer intervals)
    DEFAULT_THEME_THRESHOLD = 2
    DEFAULT_THEME_WINDOW = 30  # Longer window for budget mode
    DEFAULT_CONFLUENCE_THRESHOLD = 2
    DEFAULT_CONFLUENCE_WINDOW = 20  # Longer window for budget mode

    @classmethod
    def get_plan_config(cls, plan_name: str = None) -> Dict:
        """Get configuration for a specific plan"""
        plan_name = plan_name or cls.DEFAULT_PLAN
        return cls.PLANS.get(plan_name, cls.PLANS[cls.DEFAULT_PLAN])

# ===========================
# DATA MODELS (Same as before)
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
# TOKEN CATEGORIZATION (Same as before)
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
# BUDGET-OPTIMIZED API CLIENT
# ===========================

class BudgetCoinGlassClient:
    """Budget-optimized CoinGlass API client with request tracking"""
    
    def __init__(self, api_key: str, plan: str = 'startup'):
        self.api_key = api_key
        self.plan = plan
        self.plan_config = BudgetBotConfig.get_plan_config(plan)
        self.base_url = BudgetBotConfig.COINGLASS_API_BASE
        
        # Request tracking for budget monitoring
        self.requests_this_minute = 0
        self.last_minute_reset = datetime.now()
        
        self.session = requests.Session()
        self.session.headers.update({
            'CG-API-KEY': api_key,
            'Content-Type': 'application/json'
        })
        
        logger.info(f"🎯 CoinGlass client initialized for {plan} plan (${self.plan_config['cost_per_month']}/mo)")
    
    def _reset_minute_counter(self):
        """Reset request counter every minute"""
        now = datetime.now()
        if (now - self.last_minute_reset).total_seconds() >= 60:
            self.requests_this_minute = 0
            self.last_minute_reset = now
    
    def _check_rate_limit(self):
        """Check if we're approaching rate limits"""
        self._reset_minute_counter()
        
        limit = self.plan_config['requests_per_minute']
        utilization = (self.requests_this_minute / limit) * 100
        
        if utilization > 80:
            logger.warning(f"⚠️ High API usage: {utilization:.1f}% of {limit} req/min limit")
        
        return self.requests_this_minute < limit
    
    async def get_hyperliquid_whale_positions(self, address: str) -> Optional[List[Dict]]:
        """Get whale positions with budget-friendly rate limiting"""
        try:
            if not self._check_rate_limit():
                logger.warning(f"Rate limit reached, skipping request for {address}")
                return None
            
            url = f"{self.base_url}/api/hyperliquid/whale-position"
            params = {'address': address}
            
            response = await self._make_request(url, params)
            if response and response.get('success'):
                self.requests_this_minute += 1
                return response.get('data', [])
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching whale positions for {address}: {e}")
            return None
    
    async def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make async HTTP request with budget-friendly retries"""
        for attempt in range(BudgetBotConfig.MAX_RETRIES):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: self.session.get(url, params=params, timeout=BudgetBotConfig.API_TIMEOUT)
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limited
                    wait_time = 60  # Wait a full minute for budget plans
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(f"API request failed: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt < BudgetBotConfig.MAX_RETRIES - 1:
                    await asyncio.sleep(BudgetBotConfig.RETRY_DELAY * (attempt + 1))
        
        return None
    
    def get_usage_stats(self) -> Dict:
        """Get current API usage statistics"""
        self._reset_minute_counter()
        limit = self.plan_config['requests_per_minute']
        return {
            'plan': self.plan,
            'cost_per_month': self.plan_config['cost_per_month'],
            'requests_this_minute': self.requests_this_minute,
            'requests_per_minute_limit': limit,
            'utilization_percent': (self.requests_this_minute / limit) * 100
        }

# ===========================
# BUDGET-OPTIMIZED DATA MANAGER
# ===========================

class BudgetVaultDataManager:
    """Budget-optimized vault data management with configurable intervals"""
    
    def __init__(self, plan: str = 'startup'):
        self._lock = threading.RLock()
        self._plan = plan
        self._plan_config = BudgetBotConfig.get_plan_config(plan)
        
        # Vault management
        self._vaults: Dict[str, VaultInfo] = {}
        self._previous_positions: Dict[str, Dict[str, Position]] = {}
        self._trade_events: List[TradeEvent] = []
        self._theme_events: List[ThemeEvent] = []
        self._last_save_time = 0
        
        # Budget-optimized settings
        self._check_interval = self._plan_config['recommended_check_interval']
        self._theme_threshold = BudgetBotConfig.DEFAULT_THEME_THRESHOLD
        self._theme_window = BudgetBotConfig.DEFAULT_THEME_WINDOW
        self._confluence_threshold = BudgetBotConfig.DEFAULT_CONFLUENCE_THRESHOLD
        self._confluence_window = BudgetBotConfig.DEFAULT_CONFLUENCE_WINDOW
        self._theme_alerts_enabled = True
        
        # Initialize categorizer
        self._categorizer = TokenCategorizer()
        
        # Load persisted data
        self._load_data()
        
        logger.info(f"🎯 Budget manager initialized for {plan} plan - {self._check_interval/60:.0f}min intervals")
    
    @property
    def check_interval(self) -> int:
        """Get current check interval in seconds"""
        with self._lock:
            return self._check_interval
    
    def set_check_interval(self, seconds: int):
        """Set check interval with plan limits"""
        with self._lock:
            min_interval = self._plan_config['min_check_interval']
            max_interval = self._plan_config['max_check_interval']
            
            # Enforce plan limits
            if seconds < min_interval:
                logger.warning(f"Interval {seconds}s too low for {self._plan} plan, using {min_interval}s")
                seconds = min_interval
            elif seconds > max_interval:
                logger.warning(f"Interval {seconds}s too high for {self._plan} plan, using {max_interval}s")
                seconds = max_interval
            
            self._check_interval = seconds
            self._safe_save()
            logger.info(f"Check interval set to {seconds}s ({seconds/60:.1f} minutes)")
    
    def get_plan_info(self) -> Dict:
        """Get current plan information"""
        return {
            'plan': self._plan,
            'cost_per_month': self._plan_config['cost_per_month'],
            'check_interval_seconds': self._check_interval,
            'check_interval_minutes': self._check_interval / 60,
            'description': self._plan_config['description']
        }
    
    # [Rest of the methods are similar to the original VaultDataManager but with budget optimizations]
    
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
        """Add trade event with budget-optimized cleanup"""
        with self._lock:
            self._trade_events.append(event)
            # Longer cleanup window for budget mode
            cutoff = datetime.now() - timedelta(minutes=self._confluence_window)
            self._trade_events = [e for e in self._trade_events if e.timestamp > cutoff]
    
    def check_confluence(self, trade_event: TradeEvent) -> Optional[List[TradeEvent]]:
        """Check for token confluence with budget-optimized windows"""
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
        """Check for theme confluence with budget-optimized windows"""
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
    
    def _safe_save(self):
        """Rate-limited save for budget optimization"""
        current_time = time.time()
        if current_time - self._last_save_time < BudgetBotConfig.MIN_SAVE_INTERVAL:
            return
        
        self._last_save_time = current_time
        self._save_data()
    
    def _save_data(self):
        """Save vault data atomically"""
        try:
            data = {
                'vaults': {name: vault.to_dict() for name, vault in self._vaults.items()},
                'settings': {
                    'plan': self._plan,
                    'check_interval': self._check_interval,
                    'theme_threshold': self._theme_threshold,
                    'theme_window': self._theme_window,
                    'confluence_threshold': self._confluence_threshold,
                    'confluence_window': self._confluence_window,
                    'theme_alerts_enabled': self._theme_alerts_enabled
                },
                'saved_at': datetime.now().isoformat(),
                'version': '3.0-budget'
            }
            
            # Atomic write
            temp_file = f"{BudgetBotConfig.VAULT_DATA_FILE}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Backup existing file
            if os.path.exists(BudgetBotConfig.VAULT_DATA_FILE):
                try:
                    os.rename(BudgetBotConfig.VAULT_DATA_FILE, BudgetBotConfig.BACKUP_FILE)
                except:
                    pass
            
            os.rename(temp_file, BudgetBotConfig.VAULT_DATA_FILE)
            logger.debug(f"Saved {len(self._vaults)} vaults to storage")
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def _load_data(self):
        """Load vault data with fallback"""
        try:
            data = None
            
            # Try primary file
            if os.path.exists(BudgetBotConfig.VAULT_DATA_FILE):
                try:
                    with open(BudgetBotConfig.VAULT_DATA_FILE, 'r') as f:
                        data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load primary file: {e}")
            
            # Try backup
            if not data and os.path.exists(BudgetBotConfig.BACKUP_FILE):
                try:
                    with open(BudgetBotConfig.BACKUP_FILE, 'r') as f:
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
                self._plan = settings.get('plan', self._plan)
                self._plan_config = BudgetBotConfig.get_plan_config(self._plan)
                self._check_interval = settings.get('check_interval', self._plan_config['recommended_check_interval'])
                self._theme_threshold = settings.get('theme_threshold', BudgetBotConfig.DEFAULT_THEME_THRESHOLD)
                self._theme_window = settings.get('theme_window', BudgetBotConfig.DEFAULT_THEME_WINDOW)
                self._confluence_threshold = settings.get('confluence_threshold', BudgetBotConfig.DEFAULT_CONFLUENCE_THRESHOLD)
                self._confluence_window = settings.get('confluence_window', BudgetBotConfig.DEFAULT_CONFLUENCE_WINDOW)
                self._theme_alerts_enabled = settings.get('theme_alerts_enabled', True)
                
                logger.info(f"Loaded {len(self._vaults)} vaults from storage")
            else:
                logger.info("No existing data found - starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading data: {e}")

# Default vaults (same as before)
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
# BUDGET BOT CLASS (Simplified)
# ===========================

class BudgetCoinGlassWhaleBot:
    """Budget-optimized whale tracking bot"""
    
    def __init__(self, telegram_token: str, chat_id: str, coinglass_api_key: str, plan: str = 'startup'):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.plan = plan
        self.coinglass_client = BudgetCoinGlassClient(coinglass_api_key, plan)
        self.vault_data = BudgetVaultDataManager(plan)
        
        # Monitoring state
        self._is_monitoring = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._monitoring_lock = asyncio.Lock()
        
        logger.info(f"🎯 Budget CoinGlass Bot initialized for {plan} plan")
    
    async def start_monitoring(self):
        """Start budget-optimized monitoring"""
        async with self._monitoring_lock:
            if self._is_monitoring:
                logger.warning("Monitoring already active")
                return
            
            self._is_monitoring = True
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            
            plan_info = self.vault_data.get_plan_info()
            await self.send_alert(
                f"🚀 Budget CoinGlass Bot v3.0 started!\n"
                f"💰 Plan: {plan_info['plan']} (${plan_info['cost_per_month']}/mo)\n"
                f"⏱️ Check interval: {plan_info['check_interval_minutes']:.0f} minutes\n"
                f"📊 Tracking: {len(self.vault_data.get_active_vaults())} vaults"
            )
            logger.info("📊 Budget monitoring started")
    
    async def _monitoring_loop(self):
        """Budget-optimized monitoring loop"""
        logger.info("🔄 Starting budget monitoring loop")
        
        while self._is_monitoring:
            try:
                active_vaults = self.vault_data.get_active_vaults()
                if not active_vaults:
                    logger.warning("No active vaults to monitor")
                    await asyncio.sleep(self.vault_data.check_interval)
                    continue
                
                logger.info(f"📊 Checking {len(active_vaults)} vaults (budget mode)...")
                
                # Process vaults in smaller batches for budget plans
                for i in range(0, len(active_vaults), BudgetBotConfig.BATCH_SIZE):
                    batch = active_vaults[i:i + BudgetBotConfig.BATCH_SIZE]
                    
                    for vault in batch:
                        await self._check_vault(vault)
                        # Small delay between vaults to respect rate limits
                        await asyncio.sleep(2)
                    
                    # Longer delay between batches for budget mode
                    if i + BudgetBotConfig.BATCH_SIZE < len(active_vaults):
                        await asyncio.sleep(5)
                
                # Show API usage stats
                usage_stats = self.coinglass_client.get_usage_stats()
                logger.info(f"✅ Check completed - API usage: {usage_stats['utilization_percent']:.1f}%")
                
                await asyncio.sleep(self.vault_data.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Shorter retry on errors
    
    async def _check_vault(self, vault: VaultInfo):
        """Budget-optimized vault checking"""
        try:
            # Get current positions from CoinGlass
            positions_data = await self.coinglass_client.get_hyperliquid_whale_positions(vault.address)
            
            if positions_data is None:
                vault.consecutive_failures += 1
                logger.warning(f"Failed to get positions for {vault.name}")
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
                        entry_price=Decimal(str(pos_data.get('entry_price', 0))) if pos_data.get('entry_price') else None
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
                
                # Detect significant changes (higher threshold for budget mode)
                if abs(new_size - old_size) > Decimal('1.0'):  # Higher threshold
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
                    
                    # Check for confluence (with longer windows)
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
        """Send budget-optimized confluence alert"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_events))
            confluence_count = len(unique_vaults)
            
            emoji = "🟢" if trigger_event.trade_type == "OPEN" else "🔴" if trigger_event.trade_type == "CLOSE" else "📈"
            
            message = (
                f"{emoji} **CONFLUENCE DETECTED** 🎯\n\n"
                f"**Token:** {trigger_event.symbol}\n"
                f"**Vaults Trading:** {confluence_count} within {self.vault_data._confluence_window}min\n\n"
                f"**Trigger:** {trigger_event.vault_name} - {trigger_event.trade_type}\n"
                f"**Size:** {trigger_event.old_size} → {trigger_event.new_size}\n\n"
                f"**All Vaults:** {', '.join(sorted(unique_vaults))}\n"
                f"**Time:** {datetime.now().strftime('%H:%M:%S')}\n"
                f"💰 **Budget Mode** - {self.vault_data.check_interval/60:.0f}min intervals"
            )
            
            await self.send_alert(message)
            logger.info(f"🚨 Confluence alert sent: {trigger_event.symbol} - {confluence_count} vaults")
            
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")
    
    async def _send_theme_alert(self, theme: str, trigger_event: TradeEvent, all_theme_events: List[ThemeEvent]):
        """Send budget-optimized theme alert"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_theme_events))
            theme_count = len(unique_vaults)
            
            emoji = self.vault_data.categorizer.get_category_emoji(theme)
            tokens_traded = list(set(e.symbol for e in all_theme_events))
            
            message = (
                f"{emoji} **THEME CONFLUENCE** {emoji}\n\n"
                f"**Theme:** {theme}\n"
                f"**Vaults:** {theme_count} within {self.vault_data._theme_window}min\n"
                f"**Tokens:** {', '.join(sorted(tokens_traded))}\n\n"
                f"**Trigger:** {trigger_event.vault_name} - {trigger_event.symbol}\n"
                f"**Action:** {trigger_event.trade_type}\n\n"
                f"**All Vaults:** {', '.join(sorted(unique_vaults))}\n"
                f"**Time:** {datetime.now().strftime('%H:%M:%S')}\n"
                f"💰 **Budget Mode** - {self.vault_data.check_interval/60:.0f}min intervals"
            )
            
            await self.send_alert(message)
            logger.info(f"🎯 Theme alert sent: {theme} - {theme_count} vaults")
            
        except Exception as e:
            logger.error(f"Error sending theme alert: {e}")
    
    async def send_alert(self, message: str):
        """Send alert to Telegram"""
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            logger.error(f"Error sending alert: {e}")

# Simple main function for testing
async def main():
    """Main function for budget bot"""
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    coinglass_api_key = os.getenv('COINGLASS_API_KEY')
    plan = os.getenv('COINGLASS_PLAN', 'startup')  # Default to startup plan
    
    if not all([telegram_token, chat_id, coinglass_api_key]):
        print("❌ Missing required environment variables")
        return
    
    print(f"🚀 Starting Budget CoinGlass Bot v3.0 ({plan} plan)...")
    
    # Create bot instance
    whale_bot = BudgetCoinGlassWhaleBot(telegram_token, chat_id, coinglass_api_key, plan)
    
    # Initialize default vaults if none exist
    if len(whale_bot.vault_data.get_active_vaults()) == 0:
        print("🔧 Initializing default vaults...")
        for address, name in DEFAULT_VAULTS:
            success, message = whale_bot.vault_data.add_vault(address, name)
            if success:
                print(f"✅ Added: {name}")
    
    # Start monitoring
    await whale_bot.start_monitoring()
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        print("Bot stopped by user")

if __name__ == "__main__":
    asyncio.run(main())