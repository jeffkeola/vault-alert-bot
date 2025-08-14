# 🎯 Theme Detection System

## Overview

The Theme Detection System is a powerful new feature added to your Hyperliquid vault tracking bot that detects when multiple vaults are trading tokens from the same category (theme) within a specified time window. This helps identify coordinated institutional trading strategies and market themes.

## 🚀 What's New in v2.3

### Core Features

- **📊 Token Categorization**: Automatically categorizes 80+ tokens into 10 market themes
- **🎯 Theme Confluence Detection**: Alerts when multiple vaults trade the same theme
- **⚙️ Configurable Settings**: Customizable thresholds and time windows
- **🔄 Real-time Monitoring**: Runs alongside existing position tracking
- **💾 Persistent Settings**: All configurations are saved automatically

### Token Categories

| Theme | Emoji | Example Tokens | Count |
|-------|-------|----------------|-------|
| **AI** | 🤖 | ARKM, FET, RNDR, TAO, OCEAN | 12 tokens |
| **Gaming** | 🎮 | GALA, SAND, MANA, AXS, IMX | 12 tokens |
| **DeFi** | 🏦 | UNI, AAVE, SNX, CRV, COMP | 12 tokens |
| **Meme** | 🐸 | PEPE, DOGE, SHIB, FLOKI, BONK | 10 tokens |
| **Layer 1** | ⛓️ | BTC, ETH, SOL, ADA, DOT | 12 tokens |
| **Layer 2** | 🔗 | ARB, OP, MATIC, LRC, ZK | 8 tokens |
| **Oracles** | 🔮 | LINK, BAND, TRB, API3, UMA | 6 tokens |
| **Infrastructure** | 🏗️ | GRT, FIL, AR, STORJ, THETA | 7 tokens |
| **Privacy** | 🕵️ | XMR, ZEC, SCRT, ROSE, NYM | 6 tokens |
| **RWA** | 🏠 | RIO, TRU, CFG, MKR, ONDO | 7 tokens |

## 📋 Telegram Commands

### Theme Management Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/themes` | Show theme detection settings and overview | `/themes` |
| `/theme_threshold <number>` | Set minimum vaults for theme alerts | `/theme_threshold 3` |
| `/categories` | List all token categories with details | `/categories` |

### Updated Commands

- `/start` - Now shows theme detection status
- `/status` - Includes theme settings in overview
- `/show_settings` - Displays theme configuration

## 🎯 How Theme Detection Works

### 1. Token Classification
When a vault trades a token, the system:
- Looks up the token in the categorization database
- Identifies which theme the token belongs to
- Creates a theme event record

### 2. Confluence Detection
The system tracks theme events and triggers alerts when:
- **Threshold Met**: 2+ vaults (configurable) trade tokens from the same theme
- **Time Window**: Within 15 minutes (configurable) of each other
- **Unique Vaults**: Each vault counts only once per theme per window

### 3. Alert Generation
When theme confluence is detected, you receive:
- 🎯 **Theme confluence alert** with theme emoji
- **Participating vaults** and their actions
- **All tokens** traded within the theme
- **Timing information** for each trade
- **Theme strength** (vaults participating / total vaults)

## 📊 Example Alert

```
🤖 THEME CONFLUENCE DETECTED 🤖

Theme: AI (🤖)
Vaults Trading: 3 within 15min
Tokens: ARKM, FET, RNDR

Trigger Event:
• Vault: Martybit
• Token: RNDR
• Action: OPEN
• Size: 0 → 5000

All AI Activity:
1. Amber: ARKM (OPEN, 2m ago)
2. Martybit: RNDR (OPEN, just now)
3. TapTrade: FET (INCREASE, 5m ago)

Time: 14:32:15
🎯 Theme Strength: 3/9 vaults
```

## ⚙️ Configuration

### Default Settings
- **Theme Alerts**: Enabled
- **Theme Threshold**: 2 vaults
- **Time Window**: 15 minutes

### Customization
```bash
# Set theme threshold (minimum vaults for alerts)
/theme_threshold 3

# View current settings
/themes

# See all categories
/categories
```

## 🔍 Use Cases

### 1. Institutional Coordination Detection
- **AI Sector Play**: Multiple vaults buying AI tokens simultaneously
- **Gaming Rotation**: Coordinated moves into gaming/metaverse tokens
- **DeFi Summer**: Synchronized DeFi protocol investments

### 2. Market Theme Identification
- **Narrative Shifts**: Early detection of new market themes
- **Sector Rotation**: Identify when smart money moves between sectors
- **Risk Management**: Spot when multiple vaults exit similar positions

### 3. Trading Strategy Insights
- **Follow the Smart Money**: See which themes institutional vaults favor
- **Timing Analysis**: Understand coordination patterns
- **Diversification**: Avoid over-concentration in crowded themes

## 🚨 Alert Types

### Regular Confluence (by token)
```
🟢 CONFLUENCE DETECTED v2.3

Token: ETH
Vaults Trading: 2 within 10min
```

### Theme Confluence (NEW)
```
🤖 THEME CONFLUENCE DETECTED 🤖

Theme: AI (🤖)
Vaults Trading: 3 within 15min
Tokens: ARKM, FET, RNDR
```

## 🔧 Technical Implementation

### Thread-Safe Design
- All theme detection runs in thread-safe environment
- Concurrent vault processing doesn't interfere with theme tracking
- Atomic data persistence ensures no lost events

### Performance Optimized
- Efficient token lookup using hash maps
- Automatic cleanup of old theme events
- Minimal overhead on existing position monitoring

### Extensible Architecture
- Easy to add new token categories
- Configurable time windows and thresholds
- Support for custom token classification

## 📈 Benefits

### For Active Traders
- **Early Signals**: Detect institutional coordination before public
- **Theme Awareness**: Stay ahead of market narratives
- **Risk Management**: Avoid following crowd too late

### For Position Tracking
- **Enhanced Context**: Understand why vaults are moving together
- **Pattern Recognition**: Identify recurring themes and cycles
- **Strategic Insights**: Learn from institutional behavior patterns

## 🔄 Integration with Existing Features

### Compatibility
- ✅ Works alongside existing confluence detection
- ✅ Maintains all current position tracking features
- ✅ Preserves cooldown and anti-spam mechanisms
- ✅ Compatible with all vault management commands

### Data Persistence
- Theme settings saved automatically
- Theme events cleaned up based on time windows
- No impact on existing vault data storage

## 🚀 Getting Started

1. **Update your bot** to v2.3 (already done)
2. **Check theme settings**: `/themes`
3. **Customize if needed**: `/theme_threshold 3`
4. **Monitor alerts**: Theme confluence alerts will appear automatically
5. **Explore categories**: `/categories` to see all available themes

## 🎯 Success Example

Based on your trading objective to detect "confluence - when multiple large vaults trade the same token within a time window", theme detection takes this to the next level by:

1. **Expanding beyond single tokens** to thematic coordination
2. **Providing market context** through categorization
3. **Identifying narrative-driven** institutional strategies
4. **Enhancing signal quality** with theme-based filtering

You'll now catch both:
- **Token-specific confluence**: "3 vaults buying ETH"
- **Theme-based confluence**: "4 vaults buying AI tokens (ARKM, FET, RNDR, TAO)"

This gives you deeper insights into institutional coordination patterns and helps identify emerging market themes before they become obvious.