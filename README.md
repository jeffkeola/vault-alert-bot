# 🤖 JWOvaultbot - Crypto Trading Intelligence System

A sophisticated Telegram bot that monitors Hyperliquid vaults and wallets to detect trading confluence and send intelligent alerts.

## 🎯 What This Bot Does

- **Tracks Multiple Addresses**: Monitor both vaults and individual wallet addresses on Hyperliquid
- **Detects Trading Confluence**: Alerts when multiple tracked addresses make similar trades
- **Real-Time Monitoring**: Checks for new trades every 30 seconds
- **Smart Filtering**: Only alerts on trades above your minimum value threshold
- **Configurable Rules**: Customize confluence requirements, time windows, and trade minimums

## 🚀 Current Status

- ✅ **Bot is Live**: Running 24/7 on Render.com
- ✅ **Telegram Integration**: Responds to commands instantly
- ✅ **Database Active**: SQLite database tracking addresses and trades
- ✅ **API Connected**: Successfully pulling data from Hyperliquid
- ⏳ **Waiting for First Real Alert**: Testing with actual vault addresses

## 📊 Current Configuration

### Default Rules:
- **Confluence Count**: 2 addresses needed for alert
- **Time Window**: 300 seconds (5 minutes)
- **Minimum Trade Value**: $1,000
- **Monitoring Frequency**: Every 30 seconds

### Tracked Addresses:
- Use `/list_tracked` to see current addresses
- Currently monitoring: [Will show when vaults are added]

## 🛠 Available Commands

### Core Commands:
- `/start` - Show welcome message and command list
- `/status` - Display bot status and statistics
- `/show_rules` - View current confluence rules

### Address Management:
- `/add_vault <address> <name>` - Track a Hyperliquid vault
- `/add_wallet <address> <name>` - Track a wallet address
- `/remove_vault <address>` - Stop tracking a vault
- `/remove_wallet <address>` - Stop tracking a wallet
- `/list_tracked` - Show all tracked addresses

### Rule Configuration:
- `/set_rule confluence <number>` - Set how many addresses needed for alert
- `/set_rule time_window <seconds>` - Set confluence time window
- `/set_rule min_value <amount>` - Set minimum trade value ($)

### Monitoring:
- `/start_monitoring` - Begin real-time tracking
- `/stop_monitoring` - Pause tracking
- `/recent_alerts` - Show recent confluence alerts

## 🔧 Technical Details

### Architecture:
- **Main Bot**: `jwovaultbot.py` - Telegram bot and command handlers
- **Confluence Engine**: `confluence_engine.py` - Trade detection and analysis
- **Launcher**: `start_bot.py` - Bot startup and error handling
- **Dependencies**: `requirements.txt` - Python packages
- **Deployment**: `render.yaml` - Render.com configuration

### Data Storage:
- **Database**: SQLite (local storage)
- **Tables**: tracked_addresses, trade_rules, detected_trades, confluence_alerts
- **Persistence**: Data resets on code deployments (considering PostgreSQL upgrade)

### API Integration:
- **Hyperliquid SDK**: Real-time market data and position tracking
- **Telegram Bot API**: Command handling and alert delivery
- **Rate Limiting**: 30-second intervals to respect API limits

## 🎪 How Confluence Detection Works

1. **Monitor Addresses**: Bot checks each tracked address every 30 seconds
2. **Detect Position Changes**: Compares old vs new positions to identify trades
3. **Store Trades**: Records significant trades (above minimum value)
4. **Analyze Confluence**: Looks for similar trades (same asset + direction) within time window
5. **Send Alerts**: When enough addresses trade similarly, sends formatted alert

### Example Alert:
```
🚨 **CONFLUENCE ALERT** 🚨

📊 **Asset:** ETH
📈 **Direction:** LONG
🎯 **Addresses:** 3/2 required

💰 **Trades:**
- 0x1234567...: $15,000 at $3,180.50
- 0xabcdef1...: $8,500 at $3,181.25
- 0x9876543...: $12,300 at $3,180.75

━━━━━━━━━━━━━━━━━━━━
💵 **Total Value:** $35,800
⏱️ **Time Window:** 5 minutes
🕒 **Detected:** 2:45 PM

⚡ Smart money is moving! 🧠
```

## 🔮 Future Enhancements (Phase 2)

- **Automated Trading**: Execute trades based on confluence signals
- **Rate Limiting**: Max 4 trades per 20 minutes with manual approval
- **Advanced Weighting**: Weight certain vaults more heavily than others
- **PostgreSQL Database**: Persistent storage that survives deployments
- **WebSocket Integration**: Even faster trade detection
- **Machine Learning**: Pattern recognition and signal strength scoring

## 📈 Success Metrics

- **Alert Accuracy**: How often confluence leads to profitable moves
- **Response Time**: Speed from trade detection to alert delivery
- **Coverage**: Percentage of significant moves caught by confluence
- **False Positives**: Reducing noise while maintaining sensitivity

## 🔒 Security & Privacy

- **Private Repository**: All code and strategies kept confidential
- **Environment Variables**: Sensitive tokens stored securely
- **Local Database**: Trading data not shared with external services
- **24/7 Monitoring**: Bot runs continuously without manual intervention

## 📞 Support & Maintenance

- **Bot Status**: Monitor via Render dashboard logs
- **Error Handling**: Automatic restarts on failures
- **Updates**: Deploy via GitHub commits
- **Backup Strategy**: GitHub releases for stable versions

---

*Built with Python, Telegram Bot API, Hyperliquid SDK, and deployed on Render.com*