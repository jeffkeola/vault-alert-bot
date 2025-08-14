#!/usr/bin/env python3
"""
Test script to check if CoinGlass API returns totalBalance (TVL) field
"""

import requests
import json
import os
from dotenv import load_dotenv

def test_coinglass_tvl():
    """Test if we can get totalBalance from CoinGlass API"""
    
    print("🔍 Testing CoinGlass API for totalBalance (TVL) field...")
    print("=" * 60)
    
    # Load environment if available
    load_dotenv()
    
    # Get API key (you'll need to set this after signup)
    api_key = os.getenv('COINGLASS_API_KEY')
    
    if not api_key:
        print("❌ No CoinGlass API key found in environment")
        print("   Please set COINGLASS_API_KEY after you sign up")
        print("   For now, showing what we'll test...")
        print()
    
    # Your wallet addresses to test
    test_wallets = [
        ("0x27d33e77c8e6335089f56e399bf706ae9ad402b9", "marty"),  # The one you showed me
        ("0x56498e5f90c14060499b62b6f459b3e3fb9280c5", "TOPDOG"),
        ("0x4430bd573cb9a4eb33e61ece030ad6e5edaa0476", "amber"),
    ]
    
    if not api_key:
        print("📋 Will test these wallets once you have API key:")
        for address, name in test_wallets:
            print(f"   • {name}: {address}")
        print()
        print("🔗 Sign up at: https://coinglass.com/api")
        print("💰 Choose Startup Plan ($79/month)")
        return
    
    # Test with API key
    session = requests.Session()
    session.headers.update({
        'CG-API-KEY': api_key,
        'Content-Type': 'application/json'
    })
    
    base_url = "https://fapi.coinglass.com"
    
    print(f"🔌 Testing with API key: {api_key[:8]}...")
    print()
    
    for address, name in test_wallets:
        print(f"📊 Testing {name} ({address[:8]}...):")
        
        try:
            url = f"{base_url}/api/hyperliquid/whale-position"
            params = {'address': address}
            
            response = session.get(url, params=params, timeout=30)
            
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   Success: {data.get('success', False)}")
                
                if data.get('success'):
                    response_data = data.get('data', {})
                    
                    # Check what fields we get
                    if isinstance(response_data, dict):
                        print(f"   Available fields: {list(response_data.keys())}")
                        
                        # Check for totalBalance specifically
                        if 'totalBalance' in response_data:
                            tvl = response_data['totalBalance']
                            print(f"   ✅ Found totalBalance: ${tvl:,.2f}")
                        else:
                            print(f"   ❌ No totalBalance field found")
                            
                            # Check for other possible TVL field names
                            tvl_fields = ['total_balance', 'balance', 'totalValue', 'portfolioValue', 'accountValue']
                            found_tvl = False
                            for field in tvl_fields:
                                if field in response_data and response_data[field]:
                                    print(f"   💡 Found alternative TVL field '{field}': ${response_data[field]:,.2f}")
                                    found_tvl = True
                                    break
                            
                            if not found_tvl:
                                print(f"   ❌ No TVL fields found in response")
                        
                        # Show positions info
                        positions = response_data.get('positions', [])
                        if positions:
                            print(f"   📈 Found {len(positions)} positions")
                            total_pos_value = 0
                            for pos in positions[:3]:  # Show first 3
                                symbol = pos.get('symbol', 'Unknown')
                                pos_value = pos.get('position_value_usd', 0)
                                if pos_value:
                                    total_pos_value += pos_value
                                    print(f"      • {symbol}: ${pos_value:,.2f}")
                            if len(positions) > 3:
                                print(f"      • ... and {len(positions)-3} more")
                            print(f"   📊 Total position value: ${total_pos_value:,.2f}")
                        else:
                            print(f"   📈 No positions found")
                    
                    else:
                        print(f"   📊 Response data is list with {len(response_data)} items")
                        # If it's a list, positions might be the whole response
                        if response_data and isinstance(response_data[0], dict):
                            print(f"   Sample item fields: {list(response_data[0].keys())}")
                
                else:
                    print(f"   ❌ API returned success=false")
                    if 'message' in data:
                        print(f"   Error: {data['message']}")
            
            elif response.status_code == 401:
                print(f"   ❌ Authentication failed - check API key")
            elif response.status_code == 429:
                print(f"   ❌ Rate limited")
            else:
                print(f"   ❌ Request failed")
                try:
                    error_data = response.json()
                    print(f"   Error: {error_data}")
                except:
                    print(f"   Error: {response.text[:200]}")
        
        except Exception as e:
            print(f"   ❌ Exception: {e}")
        
        print()
    
    print("🎯 Summary:")
    print("   If totalBalance field is found → Perfect! We can show TVL")
    print("   If no TVL fields found → We'll show positions without TVL context")
    print("   Either way, confluence detection will work great!")

if __name__ == "__main__":
    test_coinglass_tvl()