#!/usr/bin/env python3
"""
🎯 Simple Enhanced CoinGlass Whale Bot v3.1
Tries to get TVL when available, but focuses on core functionality
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import requests

# Telegram imports
from telegram import Bot

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===========================
# SIMPLE DATA MODELS
# ===========================

@dataclass
class VaultInfo:
    """Simple vault information"""
    address: str
    name: str
    is_active: bool = True
    total_balance: Optional[Decimal] = None  # TVL if available
    last_tvl_update: Optional[datetime] = None

@dataclass
class Position:
    """Position with USD values"""
    vault_address: str
    vault_name: str
    symbol: str
    size: Decimal
    usd_value: Decimal  # USD value from CoinGlass
    entry_price: Optional[Decimal] = None

@dataclass
class TradeEvent:
    """Trade event with USD values and optional TVL"""
    vault_name: str
    symbol: str
    old_usd_value: Decimal
    new_usd_value: Decimal
    total_balance: Optional[Decimal]  # TVL if available
    timestamp: datetime
    
    @property
    def usd_change(self) -> Decimal:
        return abs(self.new_usd_value - self.old_usd_value)
    
    @property
    def trade_type(self) -> str:
        if self.old_usd_value == 0:
            return "OPEN"
        elif self.new_usd_value == 0:
            return "CLOSE"
        elif self.new_usd_value > self.old_usd_value:
            return "INCREASE"
        else:
            return "DECREASE"
    
    @property
    def position_percentage(self) -> Optional[float]:
        """Position as % of portfolio (if TVL available)"""
        if self.total_balance and self.total_balance > 0:
            return float((self.new_usd_value / self.total_balance) * 100)
        return None

# ===========================
# SMART API CLIENT
# ===========================

class SmartCoinGlassClient:
    """Smart client that tries to get TVL but doesn't force it"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://fapi.coinglass.com"
        
        self.session = requests.Session()
        self.session.headers.update({
            'CG-API-KEY': api_key,
            'Content-Type': 'application/json'
        })
        
        logger.info("🎯 Smart CoinGlass client initialized")
    
    async def get_whale_data(self, address: str) -> Optional[Tuple[List[Dict], Optional[Decimal]]]:
        """Get positions and try to get TVL (but don't force it)"""
        try:
            url = f"{self.base_url}/api/hyperliquid/whale-position"
            params = {'address': address}
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.session.get(url, params=params, timeout=30)
            )
            
            if response.status_code != 200:
                logger.warning(f"API request failed: {response.status_code}")
                return None
            
            data = response.json()
            if not data.get('success'):
                return None
            
            # Get positions
            response_data = data.get('data', {})
            positions = response_data.get('positions', []) if isinstance(response_data, dict) else response_data
            
            # Try to get TVL (but don't calculate if not provided)
            total_balance = None
            if isinstance(response_data, dict):
                # Try common field names
                tvl_fields = ['totalBalance', 'total_balance', 'balance', 'totalValue', 'portfolioValue', 'accountValue']
                for field in tvl_fields:
                    if field in response_data and response_data[field]:
                        try:
                            total_balance = Decimal(str(response_data[field]))
                            logger.info(f"Found TVL ${total_balance:,.0f} for {address[:8]}...")
                            break
                        except:
                            continue
            
            # Don't calculate TVL from positions - that would be wrong
            if total_balance is None:
                logger.debug(f"No TVL field found for {address[:8]}... (will show positions without TVL context)")
            
            return positions, total_balance
            
        except Exception as e:
            logger.error(f"Error fetching data for {address}: {e}")
            return None

# ===========================
# SIMPLE BOT CLASS
# ===========================

class SimpleEnhancedWhaleBot:
    """Simple whale bot with optional TVL context"""
    
    def __init__(self, telegram_token: str, chat_id: str, coinglass_api_key: str):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.coinglass_client = SmartCoinGlassClient(coinglass_api_key)
        
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
        
        # Initialize your vaults
        self._initialize_vaults()
        
        logger.info("🎯 Simple Enhanced Bot initialized")
    
    def _initialize_vaults(self):
        """Initialize with your 13 vaults"""
        vaults = [
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
        
        for address, name in vaults:
            self._vaults[name] = VaultInfo(address=address.lower(), name=name)
            self._previous_positions[address.lower()] = {}
    
    async def start_monitoring(self):
        """Start monitoring with smart TVL detection"""
        if self._is_monitoring:
            return
        
        self._is_monitoring = True
        
        await self.send_alert(
            f"🚀 Simple Enhanced Bot v3.1 started!\n"
            f"📊 Tracking: {len(self._vaults)} vaults\n"
            f"🎯 Min change: ${self._min_position_change:,}\n"
            f"💡 TVL shown when available from CoinGlass"
        )
        
        # Start monitoring loop
        await self._monitoring_loop()
    
    async def _monitoring_loop(self):
        """Simple monitoring loop"""
        logger.info("🔄 Starting monitoring loop")
        
        while self._is_monitoring:
            try:
                active_vaults = [v for v in self._vaults.values() if v.is_active]
                
                logger.info(f"📊 Checking {len(active_vaults)} vaults...")
                
                # Check vaults (with rate limiting)
                for i, vault in enumerate(active_vaults):
                    await self._check_vault(vault)
                    
                    # Rate limiting between requests
                    if i < len(active_vaults) - 1:
                        await asyncio.sleep(3)
                
                logger.info("✅ Check completed")
                await asyncio.sleep(300)  # 5 minutes
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)
    
    async def _check_vault(self, vault: VaultInfo):
        """Check vault with smart TVL handling"""
        try:
            result = await self.coinglass_client.get_whale_data(vault.address)
            
            if result is None:
                logger.warning(f"Failed to get data for {vault.name}")
                return
            
            positions_data, total_balance = result
            
            # Update TVL if available
            if total_balance:
                vault.total_balance = total_balance
                vault.last_tvl_update = datetime.now()
            
            # Process positions
            current_positions = {}
            for pos_data in positions_data:
                symbol = pos_data.get('symbol', '').replace('USDT', '').replace('-USD', '')
                if symbol:
                    # Get USD value from API (preferred) or calculate
                    usd_value = Decimal('0')
                    if pos_data.get('position_value_usd'):
                        usd_value = Decimal(str(pos_data['position_value_usd']))
                    elif pos_data.get('mark_price') and pos_data.get('position_size'):
                        usd_value = abs(Decimal(str(pos_data['mark_price'])) * Decimal(str(pos_data['position_size'])))
                    
                    if usd_value > 0:
                        position = Position(
                            vault_address=vault.address,
                            vault_name=vault.name,
                            symbol=symbol,
                            size=Decimal(str(pos_data.get('position_size', 0))),
                            usd_value=usd_value,
                            entry_price=Decimal(str(pos_data.get('entry_price', 0))) if pos_data.get('entry_price') else None
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
                
                # Check if change meets threshold
                if usd_change >= self._min_position_change:
                    trade_event = TradeEvent(
                        vault_name=vault.name,
                        symbol=symbol,
                        old_usd_value=old_usd,
                        new_usd_value=new_usd,
                        total_balance=vault.total_balance,  # Could be None
                        timestamp=datetime.now()
                    )
                    
                    logger.info(f"📈 {vault.name}: {symbol} {trade_event.trade_type} - ${old_usd:,.0f} → ${new_usd:,.0f}")
                    
                    # Check for confluence
                    confluence_events = self._check_confluence(trade_event)
                    if confluence_events:
                        await self._send_confluence_alert(trade_event, confluence_events)
            
            # Update previous positions
            self._previous_positions[vault.address] = current_positions
            
        except Exception as e:
            logger.error(f"Error checking vault {vault.name}: {e}")
    
    def _check_confluence(self, trade_event: TradeEvent) -> Optional[List[TradeEvent]]:
        """Check for confluence"""
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
    
    async def _send_confluence_alert(self, trigger_event: TradeEvent, all_events: List[TradeEvent]):
        """Send confluence alert with optional TVL context"""
        try:
            unique_vaults = list(set(e.vault_name for e in all_events))
            confluence_count = len(unique_vaults)
            
            # Group events by vault
            vault_events = {}
            for event in all_events:
                if event.vault_name not in vault_events:
                    vault_events[event.vault_name] = []
                vault_events[event.vault_name].append(event)
            
            # Build alert
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
                
                # TVL context (only if available)
                tvl_str = ""
                if latest_event.total_balance:
                    tvl_str = f" (TVL: ${latest_event.total_balance:,.0f})"
                
                # Position change
                change_str = f"${latest_event.old_usd_value:,.0f} → ${latest_event.new_usd_value:,.0f}"
                
                # Portfolio percentage (only if TVL available)
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
                f"💰 **Min change:** ${self._min_position_change:,}",
                "",
                "💡 *TVL shown when available from CoinGlass*"
            ])
            
            message = "\n".join(message_lines)
            await self.send_alert(message)
            
            logger.info(f"🚨 Confluence alert sent: {trigger_event.symbol} - {confluence_count} vaults")
            
        except Exception as e:
            logger.error(f"Error sending confluence alert: {e}")
    
    async def send_alert(self, message: str):
        """Send alert to Telegram"""
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            logger.error(f"Error sending alert: {e}")

# Main function
async def main():
    """Main function"""
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    coinglass_api_key = os.getenv('COINGLASS_API_KEY')
    
    if not all([telegram_token, chat_id, coinglass_api_key]):
        print("❌ Missing required environment variables")
        return
    
    print("🚀 Starting Simple Enhanced Bot v3.1...")
    
    # Create bot instance
    whale_bot = SimpleEnhancedWhaleBot(telegram_token, chat_id, coinglass_api_key)
    
    # Start monitoring
    await whale_bot.start_monitoring()

if __name__ == "__main__":
    asyncio.run(main())