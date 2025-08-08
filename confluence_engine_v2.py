import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    address: str
    asset: str
    direction: str  # 'LONG' or 'SHORT'
    size: float
    price: float
    value_usd: float
    timestamp: datetime
    trade_id: str  # Unique trade identifier from API
    raw_data: dict

@dataclass
class ConfluenceAlert:
    asset: str
    direction: str
    trades: List[Trade]
    total_value: float
    time_window: int
    confluence_count: int

class ConfluenceEngineV2:
    """Version 2: Uses userFills API instead of position monitoring"""
    
    def __init__(self, db_path: str = "jwovaultbot.db", alert_callback: Optional[Callable] = None):
        self.db_path = db_path
        self.alert_callback = alert_callback
        self.monitoring_active = False
        self.recent_trades: List[Trade] = []
        self.last_seen_fills: Dict[str, str] = {}  # address -> last_fill_hash
        
        # Default rules
        self.rules = {
            'confluence_count': 2,
            'time_window': 300,  # 5 minutes
            'min_trade_value': 1000,
            'polling_interval': 30  # seconds between API calls
        }
        
        # Initialize Hyperliquid API
        self.hyperliquid_info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Initialize database
        self.init_database()

    def init_database(self):
        """Initialize database tables"""
        try:
            self.db = sqlite3.connect(self.db_path)
            
            # Create tables for V2
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS trades_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    size REAL NOT NULL,
                    price REAL NOT NULL,
                    value_usd REAL NOT NULL,
                    trade_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    raw_data TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS confluence_alerts_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    addresses_count INTEGER NOT NULL,
                    total_value REAL NOT NULL,
                    trades_data TEXT NOT NULL,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Index for performance
            self.db.execute('CREATE INDEX IF NOT EXISTS idx_trades_v2_timestamp ON trades_v2(timestamp)')
            self.db.execute('CREATE INDEX IF NOT EXISTS idx_trades_v2_address ON trades_v2(address)')
            
            self.db.commit()
            logger.info("Database V2 initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database V2: {e}")
            raise

    def get_tracked_addresses(self) -> List[tuple]:
        """Get tracked addresses from the main database table"""
        try:
            cursor = self.db.execute('''
                SELECT address, type, name FROM tracked_addresses WHERE active = 1
            ''')
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting tracked addresses: {e}")
            return []

    def update_rules(self, rule_type: str, value: Any):
        """Update detection rules"""
        if rule_type in self.rules:
            self.rules[rule_type] = value
            logger.info(f"Updated rule {rule_type} to {value}")
        else:
            logger.warning(f"Unknown rule type: {rule_type}")

    async def fetch_user_fills(self, address: str) -> List[Dict]:
        """Fetch user fills from Hyperliquid API"""
        try:
            # Get user fills (most recent fills)
            fills = self.hyperliquid_info.user_fills(address)
            
            if not fills:
                return []
                
            # Filter to only new fills we haven't seen
            last_seen = self.last_seen_fills.get(address, "")
            new_fills = []
            
            for fill in fills:
                fill_hash = fill.get('hash', '')
                if fill_hash and fill_hash != last_seen:
                    new_fills.append(fill)
                else:
                    # We've reached fills we've already processed
                    break
            
            # Update last seen fill for this address
            if fills:
                self.last_seen_fills[address] = fills[0].get('hash', '')
            
            return new_fills
            
        except Exception as e:
            logger.error(f"Error fetching fills for {address}: {e}")
            return []

    def parse_fill_to_trade(self, address: str, fill: Dict) -> Optional[Trade]:
        """Convert API fill data to Trade object"""
        try:
            # Extract basic trade data
            asset = fill.get('coin', '')
            side = fill.get('side', '')  # 'B' for buy, 'A' for sell  
            price = float(fill.get('px', 0))
            size = float(fill.get('sz', 0))
            timestamp_ms = fill.get('time', 0)
            trade_id = fill.get('hash', '') or f"{address}_{timestamp_ms}"
            
            # Calculate value
            value_usd = size * price
            
            # Skip trades below minimum value
            if value_usd < self.rules.get('min_trade_value', 1000):
                return None
            
            # Determine direction (LONG = buying, SHORT = selling)
            direction = 'LONG' if side == 'B' else 'SHORT'
            
            # Convert timestamp
            trade_time = datetime.fromtimestamp(timestamp_ms / 1000)
            
            return Trade(
                address=address,
                asset=asset,
                direction=direction,
                size=size,
                price=price,
                value_usd=value_usd,
                timestamp=trade_time,
                trade_id=trade_id,
                raw_data=fill
            )
            
        except Exception as e:
            logger.error(f"Error parsing fill: {e}")
            return None

    def store_trade(self, trade: Trade):
        """Store trade in database"""
        try:
            import json
            self.db.execute('''
                INSERT OR IGNORE INTO trades_v2 
                (address, asset, direction, size, price, value_usd, trade_id, timestamp, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.address,
                trade.asset,
                trade.direction,
                trade.size,
                trade.price,
                trade.value_usd,
                trade.trade_id,
                trade.timestamp.isoformat(),
                json.dumps(trade.raw_data)
            ))
            self.db.commit()
        except Exception as e:
            logger.error(f"Error storing trade: {e}")

    async def monitor_address_continuously(self, address: str, name: str):
        """Continuously monitor a single address for new fills"""
        logger.info(f"Starting userFills monitoring for {name} ({address[:8]}...)")
        
        while self.monitoring_active:
            try:
                # Fetch new fills
                new_fills = await self.fetch_user_fills(address)
                
                for fill in new_fills:
                    trade = self.parse_fill_to_trade(address, fill)
                    
                    if trade:
                        # Store trade
                        self.store_trade(trade)
                        
                        # Add to recent trades for confluence analysis
                        self.recent_trades.append(trade)
                        
                        # Clean old trades (keep only within time window)
                        cutoff_time = datetime.now() - timedelta(seconds=self.rules['time_window'])
                        self.recent_trades = [t for t in self.recent_trades if t.timestamp > cutoff_time]
                        
                        logger.info(f"New trade detected: {trade.asset} {trade.direction} ${trade.value_usd:,.0f} by {name}")
                        
                        # Check for confluence
                        await self.check_confluence(trade)
                
                # Wait before next check
                await asyncio.sleep(self.rules['polling_interval'])
                
            except Exception as e:
                logger.error(f"Error monitoring {address}: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def check_confluence(self, new_trade: Trade):
        """Check if this trade creates a confluence alert"""
        try:
            # Find similar trades within time window
            similar_trades = []
            cutoff_time = datetime.now() - timedelta(seconds=self.rules['time_window'])
            
            for trade in self.recent_trades:
                if (trade.asset == new_trade.asset and 
                    trade.direction == new_trade.direction and
                    trade.timestamp > cutoff_time and
                    trade.address != new_trade.address):  # Different address
                    similar_trades.append(trade)
            
            # Include the new trade
            similar_trades.append(new_trade)
            
            # Check if we have enough for confluence
            unique_addresses = set(trade.address for trade in similar_trades)
            
            if len(unique_addresses) >= self.rules['confluence_count']:
                # Calculate total value
                total_value = sum(trade.value_usd for trade in similar_trades)
                
                # Create confluence alert
                alert = ConfluenceAlert(
                    asset=new_trade.asset,
                    direction=new_trade.direction,
                    trades=similar_trades,
                    total_value=total_value,
                    time_window=self.rules['time_window'],
                    confluence_count=len(unique_addresses)
                )
                
                # Send alert
                await self.send_confluence_alert(alert)
                
                # Store alert in database
                self.store_confluence_alert(alert)
                
        except Exception as e:
            logger.error(f"Error checking confluence: {e}")

    async def send_confluence_alert(self, alert: ConfluenceAlert):
        """Send confluence alert via callback"""
        if self.alert_callback:
            try:
                await self.alert_callback(alert)
                logger.info(f"Sent confluence alert: {alert.asset} {alert.direction} ({alert.confluence_count} addresses)")
            except Exception as e:
                logger.error(f"Error sending alert: {e}")

    def store_confluence_alert(self, alert: ConfluenceAlert):
        """Store confluence alert in database"""
        try:
            import json
            trades_data = json.dumps([{
                'address': t.address,
                'value_usd': t.value_usd,
                'price': t.price,
                'size': t.size,
                'timestamp': t.timestamp.isoformat()
            } for t in alert.trades])
            
            self.db.execute('''
                INSERT INTO confluence_alerts_v2 
                (asset, direction, addresses_count, total_value, trades_data)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                alert.asset,
                alert.direction,
                alert.confluence_count,
                alert.total_value,
                trades_data
            ))
            self.db.commit()
        except Exception as e:
            logger.error(f"Error storing confluence alert: {e}")

    async def start_monitoring(self):
        """Start monitoring all tracked addresses"""
        if self.monitoring_active:
            logger.warning("Monitoring already active")
            return
        
        self.monitoring_active = True
        logger.info("Starting confluence monitoring V2 (userFills)...")
        
        # Get tracked addresses
        tracked_addresses = self.get_tracked_addresses()
        
        if not tracked_addresses:
            logger.warning("No tracked addresses found")
            return
        
        # Start monitoring each address
        tasks = []
        for address, addr_type, name in tracked_addresses:
            task = asyncio.create_task(
                self.monitor_address_continuously(address, name)
            )
            tasks.append(task)
            logger.info(f"Started userFills monitoring {name} ({address[:8]}...)")
        
        # Wait for all monitoring tasks
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in monitoring tasks: {e}")

    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring_active = False
        logger.info("Stopped confluence monitoring V2")

    def get_recent_alerts(self, hours: int = 24) -> List[dict]:
        """Get recent confluence alerts"""
        cursor = self.db.execute('''
            SELECT asset, direction, addresses_count, total_value, created_date
            FROM confluence_alerts_v2 
            WHERE created_date > datetime('now', '-{} hours')
            ORDER BY created_date DESC
        '''.format(hours))
        
        return [
            {
                'asset': row[0],
                'direction': row[1],
                'addresses_count': row[2],
                'total_value': row[3],
                'created_date': row[4]
            }
            for row in cursor.fetchall()
        ]


# Helper function to format confluence alert for Telegram (same as V1)
def format_confluence_alert(alert: ConfluenceAlert) -> str:
    """Format confluence alert for Telegram"""
    
    # Sort trades by value (largest first)
    sorted_trades = sorted(alert.trades, key=lambda t: t.value_usd, reverse=True)
    
    # Build trade list
    trade_lines = []
    for trade in sorted_trades:
        address_short = trade.address[:8] + "..."
        trade_lines.append(f"- {address_short}: ${trade.value_usd:,.0f} at ${trade.price:,.2f}")
    
    time_minutes = alert.time_window // 60
    
    message = f"""🚨 **CONFLUENCE ALERT V2** 🚨

📊 **Asset:** {alert.asset}
📈 **Direction:** {alert.direction}
🎯 **Addresses:** {alert.confluence_count}/{alert.confluence_count} required

💰 **Trades:**
{chr(10).join(trade_lines)}

━━━━━━━━━━━━━━━━━━━━
💵 **Total Value:** ${alert.total_value:,.0f}
⏱️ **Time Window:** {time_minutes} minutes
🕒 **Detected:** {datetime.now().strftime('%I:%M %p')}

⚡ Smart money is moving! 🧠 (V2)"""

    return message