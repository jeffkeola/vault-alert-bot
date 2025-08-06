"""
Confluence Detection Engine
Monitors tracked addresses and detects when multiple addresses make similar trades within a time window
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

from hyperliquid.info import Info
from hyperliquid.utils import constants
import websocket
import threading

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Represents a detected trade"""
    address: str
    asset: str
    direction: str  # 'LONG' or 'SHORT'
    size: float
    price: float
    value_usd: float
    timestamp: datetime
    raw_data: dict = None

@dataclass
class ConfluenceAlert:
    """Represents a confluence alert to be sent"""
    asset: str
    direction: str
    trades: List[Trade]
    total_value: float
    time_window: int
    confluence_count: int

class ConfluenceEngine:
    def __init__(self, database_conn, rules: dict, alert_callback=None):
        self.db = database_conn
        self.rules = rules
        self.alert_callback = alert_callback
        self.hyperliquid_info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Trade monitoring
        self.recent_trades = []  # Store recent trades for confluence detection
        self.monitoring_active = False
        self.ws_thread = None
        
        # WebSocket connection
        self.ws = None
        self.last_heartbeat = datetime.now()

    def get_tracked_addresses(self) -> List[Tuple[str, str, str]]:
        """Get all active tracked addresses from database"""
        cursor = self.db.execute('''
            SELECT address, type, name FROM tracked_addresses 
            WHERE active = TRUE
        ''')
        return cursor.fetchall()

    def store_trade(self, trade: Trade):
        """Store trade in database"""
        try:
            self.db.execute('''
                INSERT INTO detected_trades 
                (address, asset, direction, size, price, value_usd, timestamp, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.address, trade.asset, trade.direction,
                trade.size, trade.price, trade.value_usd,
                trade.timestamp.isoformat(), 
                json.dumps(trade.raw_data) if trade.raw_data else None
            ))
            self.db.commit()
            logger.info(f"Stored trade: {trade.asset} {trade.direction} by {trade.address[:8]}...")
        except Exception as e:
            logger.error(f"Error storing trade: {e}")

    def analyze_position_change(self, address: str, old_positions: dict, new_positions: dict) -> List[Trade]:
        """Analyze position changes to detect new trades"""
        trades = []
        
        try:
            # Compare old vs new positions to detect trades
            if not old_positions or not new_positions:
                return trades
            
            old_asset_positions = {pos['position']['coin']: pos for pos in old_positions.get('assetPositions', [])}
            new_asset_positions = {pos['position']['coin']: pos for pos in new_positions.get('assetPositions', [])}
            
            # Check each asset for position changes
            all_assets = set(list(old_asset_positions.keys()) + list(new_asset_positions.keys()))
            
            for asset in all_assets:
                old_pos = old_asset_positions.get(asset, {}).get('position', {})
                new_pos = new_asset_positions.get(asset, {}).get('position', {})
                
                old_size = float(old_pos.get('szi', '0'))
                new_size = float(new_pos.get('szi', '0'))
                
                # Detect significant position change
                size_change = abs(new_size - old_size)
                if size_change > 0.001:  # Minimum size threshold
                    # Get current price
                    all_mids = self.hyperliquid_info.all_mids()
                    current_price = float(all_mids.get(asset, 0))
                    
                    if current_price > 0:
                        value_usd = size_change * current_price
                        
                        # Only track trades above minimum value
                        if value_usd >= self.rules.get('min_trade_value', 1000):
                            direction = 'LONG' if new_size > old_size else 'SHORT'
                            
                            trade = Trade(
                                address=address,
                                asset=asset,
                                direction=direction,
                                size=size_change,
                                price=current_price,
                                value_usd=value_usd,
                                timestamp=datetime.now(),
                                raw_data={
                                    'old_position': old_pos,
                                    'new_position': new_pos
                                }
                            )
                            
                            trades.append(trade)
                            logger.info(f"Detected trade: {asset} {direction} ${value_usd:,.0f} by {address[:8]}...")
            
        except Exception as e:
            logger.error(f"Error analyzing position change for {address}: {e}")
        
        return trades

    async def monitor_address_continuously(self, address: str, name: str):
        """Continuously monitor a single address for position changes"""
        last_positions = None
        
        while self.monitoring_active:
            try:
                # Get current positions
                current_positions = self.hyperliquid_info.user_state(address)
                
                if last_positions is not None and current_positions:
                    # Analyze for new trades
                    new_trades = self.analyze_position_change(address, last_positions, current_positions)
                    
                    for trade in new_trades:
                        # Store trade
                        self.store_trade(trade)
                        
                        # Add to recent trades for confluence analysis
                        self.recent_trades.append(trade)
                        
                        # Clean old trades (keep only within time window)
                        cutoff_time = datetime.now() - timedelta(seconds=self.rules['time_window'])
                        self.recent_trades = [t for t in self.recent_trades if t.timestamp > cutoff_time]
                        
                        # Check for confluence
                        await self.check_confluence(trade)
                
                last_positions = current_positions
                
                # Wait before next check (don't spam API)
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error monitoring {address}: {e}")
                await asyncio.sleep(30)  # Wait longer on error

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
            self.db.execute('''
                INSERT INTO confluence_alerts 
                (asset, direction, addresses_count, total_value, time_window, created_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                alert.asset, alert.direction, alert.confluence_count,
                alert.total_value, alert.time_window, datetime.now().isoformat()
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
        logger.info("Starting confluence monitoring...")
        
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
            logger.info(f"Started monitoring {name} ({address[:8]}...)")
        
        # Wait for all monitoring tasks
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in monitoring tasks: {e}")

    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring_active = False
        logger.info("Stopped confluence monitoring")

    def get_recent_alerts(self, hours: int = 24) -> List[dict]:
        """Get recent confluence alerts"""
        cursor = self.db.execute('''
            SELECT asset, direction, addresses_count, total_value, created_date
            FROM confluence_alerts 
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

# Helper function to format confluence alert for Telegram
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
    
    message = f"""🚨 **CONFLUENCE ALERT** 🚨

📊 **Asset:** {alert.asset}
📈 **Direction:** {alert.direction}
🎯 **Addresses:** {alert.confluence_count}/{alert.confluence_count} required

💰 **Trades:**
{chr(10).join(trade_lines)}

━━━━━━━━━━━━━━━━━━━━
💵 **Total Value:** ${alert.total_value:,.0f}
⏱️ **Time Window:** {time_minutes} minutes
🕒 **Detected:** {datetime.now().strftime('%I:%M %p')}

⚡ Smart money is moving! 🧠"""

    return message