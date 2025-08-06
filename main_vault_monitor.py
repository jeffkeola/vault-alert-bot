import asyncio
import os
from datetime import datetime
from telegram import Bot
from hyperliquid.info import Info
from hyperliquid.utils import constants

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuration: Add your vault names and addresses here
VAULT_CONFIG = {
    'martybit_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Martybit Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'strategic_defi_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Strategic DeFi Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'opportunity_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address  
        'name': 'Opportunity Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'alpha_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Alpha Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'beta_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Beta Vault', 
        'enabled': False  # Set to True when you have real addresses
    },
    'gamma_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Gamma Vault',
        'enabled': False  # Set to True when you have real addresses
    },
    'delta_vault': {
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': 'Delta Vault',
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
            # Generate realistic data for all configured vaults
            simulation_params = [
                 {'multiplier': 0.995, 'value': 68000, 'size': 18.5},    # Martybit
                 {'multiplier': 0.999, 'value': 82000, 'size': 22.3},    # Strategic DeFi
                 {'multiplier': 1.002, 'value': 48000, 'size': 13.1},    # Opportunity  
                 {'multiplier': 0.998, 'value': 95000, 'size': 25.8},    # Alpha
                 {'multiplier': 1.001, 'value': 32000, 'size': 8.7},     # Beta
                 {'multiplier': 0.993, 'value': 156000, 'size': 42.3},   # Gamma
                 {'multiplier': 1.005, 'value': 74000, 'size': 20.1}     # Delta
             ]
            
            vault_keys = list(VAULT_CONFIG.keys())
            
            for i, (vault_key, vault_config) in enumerate(VAULT_CONFIG.items()):
                if i < len(simulation_params):
                    params = simulation_params[i]
                    entry_price = round(eth_price * params['multiplier'], 2)
                    eth_size = params['size']
                    unrealized_pnl = eth_size * (eth_price - entry_price)
                    
                    vault_data[vault_key] = {
                        'name': vault_config['name'],
                        'entry_price': entry_price,
                        'total_value': params['value'],
                        'eth_size': eth_size,
                        'unrealized_pnl': unrealized_pnl
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
    vaults = vault_data['vaults']
    
    # Calculate totals across all vaults
    total_value = sum(vault['total_value'] for vault in vaults.values())
    total_pnl = sum(vault['unrealized_pnl'] for vault in vaults.values())
    total_eth_size = sum(vault['eth_size'] for vault in vaults.values())
    
    now = datetime.now().strftime('%I:%M %p')
    
    # Build dynamic vault breakdown
    vault_breakdown = []
    vault_icons = ['🔸', '🔹', '🔺', '🔻', '🔷', '🔶']  # Different icons for each vault
    
    for i, (vault_key, vault) in enumerate(vaults.items()):
        icon = vault_icons[i % len(vault_icons)]
        pnl_pct = ((current_price - vault['entry_price']) / vault['entry_price']) * 100 if vault['entry_price'] > 0 else 0
        
        vault_section = f"""{icon} {vault['name']}
   Entry: ${vault['entry_price']:,.2f}
   Value: ${vault['total_value']:,}
   Size: {vault['eth_size']:.2f} ETH
   PnL: {pnl_pct:+.2f}% (${vault['unrealized_pnl']:+,.2f})"""
        
        vault_breakdown.append(vault_section)
    
    vault_breakdown_text = '\n\n'.join(vault_breakdown)
    
    message = f"""🚨 Vault Monitor Alert 🚨
📊 Token: ETH
💰 Current Price: ${current_price:,.2f}
{data_source}

🏦 VAULT BREAKDOWN ({len(vaults)} vaults):
━━━━━━━━━━━━━━━━━━━━
{vault_breakdown_text}

━━━━━━━━━━━━━━━━━━━━
💰 Combined Total: ${total_value:,}
📊 Total PnL: ${total_pnl:+,.2f}
🪙 Total ETH: {total_eth_size:.2f} ETH
📈 Market: ${vault_data['market_data']['bid']:.2f} / ${vault_data['market_data']['ask']:.2f}
🕒 {now} | ⚡ Hyperliquid API"""
    
    await bot.send_message(chat_id=CHAT_ID, text=message)
    print(f"✅ Vault monitor alert sent | ETH: ${current_price:,.2f}")

if __name__ == "__main__":
    asyncio.run(send_vault_monitor_alert())