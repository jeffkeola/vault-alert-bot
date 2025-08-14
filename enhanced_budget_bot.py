#!/usr/bin/env python3
"""
🎯 Enhanced Budget CoinGlass Whale Bot v3.1
Now includes Total Balance (TVL) in alerts for better context
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
# ENHANCED DATA MODELS
# ===========================

@dataclass
class VaultInfo:
    """Enhanced vault information with TVL tracking"""
    address: str
    name: str
    is_active: bool = True
    last_check: Optional[datetime] = None
    consecutive_failures: int = 0
    total_balance: Optional[Decimal] = None  # TVL from CoinGlass
    last_tvl_update: Optional[datetime] = None
    
    def __str__(self):
        tvl_str = f" TVL: ${self.total_balance:,.0f}" if self.total_balance else ""
        return f"{self.name} ({self.address[:8]}...{tvl_str})"
    
    def to_dict(self):
        return {
            'address': self.address,
            'name': self.name,
            'is_active': self.is_active,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'consecutive_failures': self.consecutive_failures,
            'total_balance': float(self.total_balance) if self.total_balance else None,
            'last_tvl_update': self.last_tvl_update.isoformat() if self.last_tvl_update else None
        }
    
    @classmethod
    def from_dict(cls, data):
        last_check = None
        if data.get('last_check'):
            try:
                last_check = datetime.fromisoformat(data['last_check'])
            except:
                pass
        
        last_tvl_update = None
        if data.get('last_tvl_update'):
            try:
                last_tvl_update = datetime.fromisoformat(data['last_tvl_update'])
            except:
                pass
        
        total_balance = None
        if data.get('total_balance'):
            try:
                total_balance = Decimal(str(data['total_balance']))
            except:
                pass
        
        return cls(
            address=data['address'],
            name=data['name'],
            is_active=data.get('is_active', True),
            last_check=last_check,
            consecutive_failures=data.get('consecutive_failures', 0),
            total_balance=total_balance,
            last_tvl_update=last_tvl_update
        )

@dataclass
class Position:
    """Enhanced position with USD values"""
    vault_address: str
    vault_name: str
    symbol: str
    size: Decimal
    entry_price: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    position_value_usd: Optional[Decimal] = None  # USD value from CoinGlass
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    @property
    def usd_value(self) -> Decimal:
        """Get USD value of position"""
        if self.position_value_usd:
            return self.position_value_usd
        elif self.mark_price and self.size:
            return abs(self.size * self.mark_price)
        elif self.entry_price and self.size:
            return abs(self.size * self.entry_price)
        return Decimal('0')

@dataclass
class TradeEvent:
    """Enhanced trade event with USD values and TVL context"""
    vault_name: str
    vault_address: str
    symbol: str
    old_size: Decimal
    new_size: Decimal
    old_usd_value: Decimal
    new_usd_value: Decimal
    total_balance: Optional[Decimal]  # TVL at time of trade
    timestamp: datetime
    entry_price: Optional[Decimal] = None
    
    @property
    def size_change(self) -> Decimal:
        return abs(self.new_size - self.old_size)
    
    @property
    def usd_change(self) -> Decimal:
        return abs(self.new_usd_value - self.old_usd_value)
    
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
    
    @property
    def position_percentage(self) -> Optional[float]:
        """Calculate position size as percentage of total balance"""
        if self.total_balance and self.total_balance > 0:
            return float((self.new_usd_value / self.total_balance) * 100)
        return None

# ===========================
# ENHANCED API CLIENT
# ===========================

class EnhancedCoinGlassClient:
    """Enhanced CoinGlass client that captures TVL"""
    
    def __init__(self, api_key: str, plan: str = 'startup'):
        self.api_key = api_key
        self.plan = plan
        self.base_url = "https://fapi.coinglass.com"
        
        # Request tracking
        self.requests_this_minute = 0
        self.last_minute_reset = datetime.now()
        
        self.session = requests.Session()
        self.session.headers.update({
            'CG-API-KEY': api_key,
            'Content-Type': 'application/json'
        })
        
        logger.info(f"🎯 Enhanced CoinGlass client initialized for {plan} plan")
    
    def _reset_minute_counter(self):
        """Reset request counter every minute"""
        now = datetime.now()
        if (now - self.last_minute_reset).total_seconds() >= 60:
            self.requests_this_minute = 0
            self.last_minute_reset = now
    
    def _check_rate_limit(self):
        """Check if we're approaching rate limits"""
        self._reset_minute_counter()
        return self.requests_this_minute < 80  # Startup plan limit
    
    async def get_hyperliquid_whale_positions(self, address: str) -> Optional[Tuple[List[Dict], Decimal]]:
        """Get whale positions AND total balance"""
        try:
            if not self._check_rate_limit():
                logger.warning(f"Rate limit reached, skipping request for {address}")
                return None
            
            url = f"{self.base_url}/api/hyperliquid/whale-position"
            params = {'address': address}
            
            response = await self._make_request(url, params)
            if response and response.get('success'):
                self.requests_this_minute += 1
                
                data = response.get('data', {})
                positions = data.get('positions', []) if isinstance(data, dict) else data
                
                # Extract total balance (TVL)
                total_balance = Decimal('0')
                if isinstance(data, dict):
                    # Look for various possible field names
                    tvl_fields = ['totalBalance', 'total_balance', 'balance', 'totalValue', 'portfolioValue']
                    for field in tvl_fields:
                        if field in data and data[field]:
                            try:
                                total_balance = Decimal(str(data[field]))
                                logger.debug(f"Found TVL {total_balance} in field '{field}' for {address[:8]}")
                                break
                            except:
                                continue
                
                # If no direct TVL field, calculate from positions
                if total_balance == 0 and positions:
                    for pos in positions:
                        pos_value = pos.get('position_value_usd', 0) or pos.get('positionValueUsd', 0)
                        if pos_value:
                            total_balance += Decimal(str(pos_value))
                
                return positions, total_balance
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching whale positions for {address}: {e}")
            return None
    
    async def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make async HTTP request"""
        for attempt in range(3):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: self.session.get(url, params=params, timeout=30)
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    await asyncio.sleep(60)
                else:
                    logger.warning(f"API request failed: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        
        return None

# ===========================
# ENHANCED BOT CLASS
# ===========================

class EnhancedCoinGlassWhaleBot:
    """Enhanced whale tracking bot with TVL context"""
    
    def __init__(self, telegram_token: str, chat_id: str, coinglass_api_key: str, plan: str = 'startup'):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.plan = plan
        self.coinglass_client = EnhancedCoinGlassClient(coinglass_api_key, plan)
        
        # Vault data
        self._vaults: Dict[str, VaultInfo] = {}
        self._previous_positions: Dict[str, Dict[str, Position]] = {}
        self._trade_events: List[TradeEvent] = []
        
        # Settings
        self._min_position_change = Decimal('1000')  # $1k minimum
        self._confluence_threshold = 2
        self._confluence_window = 5  # minutes
        
        # Monitoring state
        self._is_monitoring = False
        self._monitoring_task: Optional[asyncio.Task] = None
        
        # Initialize default vaults
        self._initialize_default_vaults()
        
        logger.info(f"🎯 Enhanced CoinGlass Bot initialized")
    
    def _initialize_default_vaults(self):
        """Initialize with your 13 vaults"""
        default_vaults = [
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
        
        for address, name in default_vaults:
            self._vaults[name] = VaultInfo(address=address.lower(), name=name)
            self._previous_positions[address.lower()] = {}
    
    async def start_monitoring(self):
        """Start enhanced monitoring with TVL tracking"""
        if self._is_monitoring:
            return
        
        self._is_monitoring = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        await self.send_alert(
            f"🚀 Enhanced CoinGlass Bot v3.1 started!\n"
            f"💰 Plan: {self.plan} - 5min intervals\n"
            f"📊 Tracking: {len(self._vaults)} vaults with TVL context\n"
            f"🎯 Min change: ${self._min_position_change:,}"
        )
        logger.info("📊 Enhanced monitoring started")
    
    async def _monitoring_loop(self):
        """Main monitoring loop with TVL updates"""
        logger.info("🔄 Starting enhanced monitoring loop")
        
        while self._is_monitoring:
            try:
                active_vaults = [v for v in self._vaults.values() if v.is_active]
                if not active_vaults:
                    await asyncio.sleep(300)  # 5 minutes
                    continue
                
                logger.info(f"📊 Checking {len(active_vaults)} vaults with TVL...")
                
                # Process in small batches
                for i in range(0, len(active_vaults), 3):
                    batch = active_vaults[i:i + 3]
                    
                    for vault in batch:
                        await self._check_vault_enhanced(vault)
                        await asyncio.sleep(2)  # Rate limiting
                    
                    if i + 3 < len(active_vaults):
                        await asyncio.sleep(5)
                
                logger.info("✅ Check completed with TVL data")
                await asyncio.sleep(300)  # 5 minutes
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)
    
    async def _check_vault_enhanced(self, vault: VaultInfo):
        """Enhanced vault checking with TVL capture"""
        try:
            # Get positions AND total balance
            result = await self.coinglass_client.get_hyperliquid_whale_positions(vault.address)
            
            if result is None:
                vault.consecutive_failures += 1
                logger.warning(f"Failed to get data for {vault.name}")
                return
            
            positions_data, total_balance = result
            
            # Update vault TVL
            vault.consecutive_failures = 0
            vault.last_check = datetime.now()
            if total_balance > 0:
                vault.total_balance = total_balance
                vault.last_tvl_update = datetime.now()
                logger.debug(f"{vault.name} TVL: ${total_balance:,.0f}")
            
            # Process positions
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
                        mark_price=Decimal(str(pos_data.get('mark_price', 0))) if pos_data.get('mark_price') else None,
                        position_value_usd=Decimal(str(pos_data.get('position_value_usd', 0))) if pos_data.get('position_value_usd') else None
                    )
                    current_positions[symbol] = position
            
            # Compare with previous positions
            previous_positions = self._previous_positions.get(vault.address, {})
            
            for symbol in set(current_positions.keys()) | set(previous_positions.keys()):
                old_position = previous_positions.get(symbol)
                new_position = current_positions.get(symbol)
                
                old_usd = old_position.usd_value if old_position else Decimal('0')
                new_usd = new_position.usd_value if new_position else Decimal('0')
                
                usd_change = abs(new_usd - old_usd)
                
                # Check if change meets minimum threshold
                if usd_change >= self._min_position_change:
                    # Create enhanced trade event
                    trade_event = TradeEvent(
                        vault_name=vault.name,
                        vault_address=vault.address,
                        symbol=symbol,
                        old_size=old_position.size if old_position else Decimal('0'),
                        new_size=new_position.size if new_position else Decimal('0'),
                        old_usd_value=old_usd,
                        new_usd_value=new_usd,
                        total_balance=vault.total_balance,
                        timestamp=datetime.now(),
                        entry_price=new_position.entry_price if new_position else None
                    )
                    
                    logger.info(f"📈 {vault.name}: {symbol} {trade_event.trade_type} - ${old_usd:,.0f} → ${new_usd:,.0f}")
                    
                    # Check for confluence
                    confluence_events = self._check_confluence(trade_event)
                    if confluence_events:
                        await self._send_enhanced_confluence_alert(trade_event, confluence_events)
            
            # Update previous positions
            self._previous_positions[vault.address] = current_positions
            
        except Exception as e:
            logger.error(f"Error checking vault {vault.name}: {e}")
            vault.consecutive_failures += 1
    
    def _check_confluence(self, trade_event: TradeEvent) -> Optional[List[TradeEvent]]:
        """Check for confluence with enhanced logic"""
        # Add to events list
        self._trade_events.append(trade_event)
        
        # Clean old events
        cutoff = datetime.now() - timedelta(minutes=self._confluence_window)
        self._trade_events = [e for e in self._trade_events if e.timestamp > cutoff]
        
        # Check for confluence
        symbol_events = [
            e for e in self._trade_events 
            if e.symbol == trade_event.symbol and e.timestamp > cutoff
        ]
        
        unique_vaults = len(set(e.vault_name for e in symbol_events))
        
        if unique_vaults >= self._confluence_threshold:
            return symbol_events
        
        return None
    
    async def _send_enhanced_confluence_alert(self, trigger_event: TradeEvent, all_events: List[TradeEvent]):
        """Send enhanced confluence alert with TVL context"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_events))
            confluence_count = len(unique_vaults)
            
            # Group events by vault
            vault_events = {}
            for event in all_events:
                if event.vault_name not in vault_events:
                    vault_events[event.vault_name] = []
                vault_events[event.vault_name].append(event)
            
            # Build enhanced alert
            emoji = "🟢" if trigger_event.trade_type == "OPEN" else "🔴" if trigger_event.trade_type == "CLOSE" else "📈"
            
            message_lines = [
                f"{emoji} **CONFLUENCE DETECTED** 🎯",
                "",
                f"**Token:** {trigger_event.symbol}",
                f"**Wallets Trading:** {confluence_count} within {self._confluence_window}min",
                "",
                "📊 **Position Details:**"
            ]
            
            total_flow = Decimal('0')
            
            # Add details for each vault
            for vault_name in sorted(unique_vaults):
                events = vault_events[vault_name]
                latest_event = max(events, key=lambda e: e.timestamp)
                
                # Format TVL
                tvl_str = ""
                if latest_event.total_balance:
                    tvl_str = f" (TVL: ${latest_event.total_balance:,.0f})"
                
                # Format position change
                change_str = f"${latest_event.old_usd_value:,.0f} → ${latest_event.new_usd_value:,.0f}"
                
                # Add percentage of portfolio if available
                pct_str = ""
                if latest_event.position_percentage:
                    pct_str = f" ({latest_event.position_percentage:.1f}% of portfolio)"
                
                message_lines.append(f"• **{vault_name}**{tvl_str}")
                message_lines.append(f"  {latest_event.symbol}: {change_str} ({latest_event.trade_type}){pct_str}")
                
                total_flow += latest_event.usd_change
            
            message_lines.extend([
                "",
                f"**Total Flow:** ${total_flow:,.0f}",
                f"**Time:** {datetime.now().strftime('%H:%M:%S')}",
                f"💰 **Min change:** ${self._min_position_change:,}"
            ])
            
            message = "\n".join(message_lines)
            await self.send_alert(message)
            
            logger.info(f"🚨 Enhanced confluence alert sent: {trigger_event.symbol} - {confluence_count} vaults - ${total_flow:,.0f}")
            
        except Exception as e:
            logger.error(f"Error sending enhanced confluence alert: {e}")
    
    async def send_alert(self, message: str):
        """Send alert to Telegram"""
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            logger.error(f"Error sending alert: {e}")

# Simple main function
async def main():
    """Main function for enhanced bot"""
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    coinglass_api_key = os.getenv('COINGLASS_API_KEY')
    plan = os.getenv('COINGLASS_PLAN', 'startup')
    
    if not all([telegram_token, chat_id, coinglass_api_key]):
        print("❌ Missing required environment variables")
        return
    
    print(f"🚀 Starting Enhanced CoinGlass Bot v3.1 ({plan} plan)...")
    
    # Create enhanced bot instance
    whale_bot = EnhancedCoinGlassWhaleBot(telegram_token, chat_id, coinglass_api_key, plan)
    
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