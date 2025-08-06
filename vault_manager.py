#!/usr/bin/env python3
"""
Vault Manager - Easy way to manage your crypto vault names and addresses
"""

import json
import os

def display_current_vaults():
    """Display current vault configuration"""
    print("📋 Current Vault Configuration:")
    print("=" * 50)
    
    # Read current config from main_vault_monitor.py
    with open('/workspace/main_vault_monitor.py', 'r') as f:
        content = f.read()
    
    # Extract vault names from the config
    lines = content.split('\n')
    in_config = False
    vault_count = 0
    
    for line in lines:
        if 'VAULT_CONFIG = {' in line:
            in_config = True
            continue
        elif in_config and line.strip() == '}':
            break
        elif in_config and "'name':" in line:
            vault_count += 1
            # Extract vault name
            name = line.split("'name': '")[1].split("'")[0]
            enabled = "🔴 DISABLED" if "'enabled': False" in content else "🟢 ENABLED"
            print(f"  {vault_count}. {name} - {enabled}")
    
    print(f"\n📊 Total Vaults: {vault_count}")
    print("=" * 50)

def add_new_vault():
    """Add a new vault to the configuration"""
    print("\n➕ Add New Vault")
    print("-" * 20)
    
    vault_name = input("Enter vault name: ").strip()
    if not vault_name:
        print("❌ Vault name cannot be empty!")
        return
    
    # Generate a key from the name
    vault_key = vault_name.lower().replace(' ', '_').replace('-', '_') + '_vault'
    
    print(f"✅ Vault Key: {vault_key}")
    print(f"✅ Vault Name: {vault_name}")
    
    # Read current file
    with open('/workspace/main_vault_monitor.py', 'r') as f:
        content = f.read()
    
    # Find the end of VAULT_CONFIG and add new vault
    new_vault_config = f"""    '{vault_key}': {{
        'address': '0x0000000000000000000000000000000000000000',  # Replace with actual vault address
        'name': '{vault_name}',
        'enabled': False  # Set to True when you have real addresses
    }},"""
    
    # Find the closing brace of VAULT_CONFIG
    config_end_pos = content.find('}', content.find('VAULT_CONFIG = {'))
    
    # Insert new vault before the closing brace
    new_content = content[:config_end_pos] + new_vault_config + '\n' + content[config_end_pos:]
    
    # Write back to file
    with open('/workspace/main_vault_monitor.py', 'w') as f:
        f.write(new_content)
    
    print(f"✅ Added {vault_name} to vault configuration!")
    print("💡 Run 'python3 main_vault_monitor.py' to test the updated configuration")

def customize_vault_names():
    """Customize existing vault names"""
    print("\n✏️  Customize Vault Names")
    print("-" * 25)
    
    vault_suggestions = [
        "Martybit Vault", "Opportunity Vault", "Alpha Vault", "Beta Vault", 
        "Gamma Vault", "Delta Vault", "Strategic Vault", "Conservative Vault",
        "Aggressive Vault", "Balanced Vault", "Growth Vault", "Income Vault",
        "DeFi Vault", "Arbitrage Vault", "Momentum Vault", "Value Vault"
    ]
    
    print("🎯 Suggested vault names:")
    for i, suggestion in enumerate(vault_suggestions, 1):
        print(f"  {i:2d}. {suggestion}")
    
    print("\n💡 You can use any of these suggestions or create your own!")
    print("💡 Edit the 'name' field in VAULT_CONFIG in main_vault_monitor.py")

def main():
    """Main menu for vault management"""
    print("🏦 Crypto Vault Manager")
    print("=" * 30)
    
    while True:
        print("\nChoose an option:")
        print("1. 📋 Display current vaults")
        print("2. ➕ Add new vault")
        print("3. ✏️  Vault name suggestions")
        print("4. 🚀 Test vault monitor")
        print("5. ❌ Exit")
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == '1':
            display_current_vaults()
        elif choice == '2':
            add_new_vault()
        elif choice == '3':
            customize_vault_names()
        elif choice == '4':
            print("\n🚀 Running vault monitor...")
            os.system('python3 main_vault_monitor.py')
        elif choice == '5':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice. Please try again.")

if __name__ == "__main__":
    main()