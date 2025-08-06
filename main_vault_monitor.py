import asyncio
import os
from datetime import datetime
from telegram import Bot
from hyperliquid.info import Info
from hyperliquid.utils import constants

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuration: Add your actual vault addresses here
VAULT_CONFIG = {
    'martybit_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Martybit Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'opportunity_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address  
        'name': 'Opportunity Vault',
        'enabled': False  # Set to True when you have real addresses
    }
}

async def get_vault_positions(info, vault_address):
    """Get actual vault positions from Hyperliquid"""
    try:
        # Get user state for the vault address
        user_state = info.user_state(vault_address)
        
        positions = []
        total_value = 0
        
        if user_state and 'assetPositions' in user_state:
            for position in user_state['assetPositions']:
                if position['position']['szi'] != '0':  # Non-zero position
                    asset_name = position['position']['coin']
                    position_size = float(position['position']['szi'])
                    entry_px = float(position['position']['entryPx'])
                    
                    # Get current market price
                    all_mids = info.all_mids()
                    current_price = float(all_mids.get(asset_name, 0))
                    
                    # Calculate position value
                    notional_value = abs(position_size * current_price)
                    unrealized_pnl = position_size * (current_price - entry_px)
                    
                    positions.append({
                        'asset': asset_name,
                        'size': position_size,
                        'entry_price': entry_px,
                        'current_price': current_price,
                        'notional_value': notional_value,
                        'unrealized_pnl': unrealized_pnl
                    })
                    
                    total_value += notional_value
        
        return {
            'positions': positions,
            'total_value': total_value,
            'account_value': float(user_state.get('marginSummary', {}).get('accountValue', 0)) if user_state else 0
        }
        
    except Exception as e:
        print(f"Error fetching vault data for {vault_address}: {e}")
        return {'positions': [], 'total_value': 0, 'account_value': 0}

async def get_hyperliquid_vault_data():
    """Fetch real vault data from Hyperliquid or simulate based on market conditions"""
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    try:
        # Get current ETH price for reference
        all_mids = info.all_mids()
        eth_price = float(all_mids.get('ETH', 0))
        
        vault_data = {}
        
        # Check if we have real vault addresses configured
        has_real_vaults = any(config['enabled'] for config in VAULT_CONFIG.values())
        
        if has_real_vaults:
            print("📊 Fetching real vault position data...")
            
            for vault_key, vault_config in VAULT_CONFIG.items():
                if vault_config['enabled']:
                    vault_positions = await get_vault_positions(info, vault_config['address'])
                    
                    # Find ETH position if it exists
                    eth_position = next((pos for pos in vault_positions['positions'] if pos['asset'] == 'ETH'), None)
                    
                    if eth_position:
                        vault_data[vault_key] = {
                            'name': vault_config['name'],
                            'entry_price': eth_position['entry_price'],
                            'total_value': vault_positions['total_value'],
                            'eth_size': eth_position['size'],
                            'unrealized_pnl': eth_position['unrealized_pnl']
                        }
                    else:
                        vault_data[vault_key] = {
                            'name': vault_config['name'],
                            'entry_price': 0,
                            'total_value': vault_positions['account_value'],
                            'eth_size': 0,
                            'unrealized_pnl': 0
                        }
        else:
            print("📊 Using simulated vault data (configure real addresses in VAULT_CONFIG)...")
            
            # Use enhanced simulation based on real market data
            vault_data = {
                'martybit_vault': {
                    'name': 'Martybit Vault',
                    'entry_price': round(eth_price * 0.995, 2),
                    'total_value': 68000,
                    'eth_size': 18.5,  # Simulated ETH holdings
                    'unrealized_pnl': 180.50
                },
                'opportunity_vault': {
                    'name': 'Opportunity Vault',
                    'entry_price': round(eth_price * 1.002, 2),
                    'total_value': 48000,
                    'eth_size': 13.1,  # Simulated ETH holdings
                    'unrealized_pnl': -85.25
                }
            }
        
        # Get order book data
        l2_book = info.l2_snapshot("ETH")
        
        return {
            'current_eth_price': eth_price,
            'vaults': vault_data,
            'market_data': {
                'bid': float(l2_book['levels'][0][0]['px']) if l2_book and 'levels' in l2_book else eth_price,
                'ask': float(l2_book['levels'][1][0]['px']) if l2_book and 'levels' in l2_book else eth_price
            },
            'is_live_data': has_real_vaults
        }
        
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

async def send_vault_monitor_alert():
    """Send advanced vault monitoring alert"""
    
    bot = Bot(token=TELEGRAM_TOKEN)
    
    # Fetch vault data
    print("📡 Fetching vault data from Hyperliquid...")
    vault_data = await get_hyperliquid_vault_data()
    
    if not vault_data:
        await bot.send_message(chat_id=CHAT_ID, text="❌ Failed to fetch vault data from Hyperliquid")
        return
    
    # Send initial status message
    data_source = "🔴 LIVE DATA" if vault_data['is_live_data'] else "🟡 SIMULATED DATA"
    await bot.send_message(chat_id=CHAT_ID, text=f"✅ Vault Monitor Active | {data_source}")
    
    # Format the alert
    current_price = vault_data['current_eth_price']
    martybit = vault_data['vaults']['martybit_vault']
    opportunity = vault_data['vaults']['opportunity_vault']
    
    # Calculate totals
    total_value = martybit['total_value'] + opportunity['total_value']
    total_pnl = martybit['unrealized_pnl'] + opportunity['unrealized_pnl']
    
    # Calculate PnL percentages
    martybit_pnl_pct = ((current_price - martybit['entry_price']) / martybit['entry_price']) * 100 if martybit['entry_price'] > 0 else 0
    opportunity_pnl_pct = ((current_price - opportunity['entry_price']) / opportunity['entry_price']) * 100 if opportunity['entry_price'] > 0 else 0
    
    now = datetime.now().strftime('%I:%M %p')
    
    message = f"""🚨 Vault Monitor Alert 🚨
📊 Token: ETH
💰 Current Price: ${current_price:,.2f}
{data_source}

🏦 VAULT BREAKDOWN:
━━━━━━━━━━━━━━━━━━━━
🔸 {martybit['name']}
   Entry: ${martybit['entry_price']:,.2f}
   Value: ${martybit['total_value']:,}
   Size: {martybit['eth_size']:.2f} ETH
   PnL: {martybit_pnl_pct:+.2f}% (${martybit['unrealized_pnl']:+,.2f})

🔹 {opportunity['name']}
   Entry: ${opportunity['entry_price']:,.2f}
   Value: ${opportunity['total_value']:,}
   Size: {opportunity['eth_size']:.2f} ETH
   PnL: {opportunity_pnl_pct:+.2f}% (${opportunity['unrealized_pnl']:+,.2f})

━━━━━━━━━━━━━━━━━━━━
💰 Combined Total: ${total_value:,}
📊 Total PnL: ${total_pnl:+,.2f}
📈 Market: ${vault_data['market_data']['bid']:.2f} / ${vault_data['market_data']['ask']:.2f}
🕒 {now} | ⚡ Hyperliquid API"""
    
    await bot.send_message(chat_id=CHAT_ID, text=message)
    print(f"✅ Vault monitor alert sent | ETH: ${current_price:,.2f}")

if __name__ == "__main__":
    asyncio.run(send_vault_monitor_alert())