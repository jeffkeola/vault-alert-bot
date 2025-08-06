# CryptoStalker - Hyperliquid Position Tracker

A real-time cryptocurrency position tracking and alerting system for Hyperliquid DEX. Monitors position changes and sends Telegram notifications when trades are detected.

## 🚀 Features

- **Real-time Position Monitoring** - Tracks Hyperliquid wallet positions via API
- **Smart Change Detection** - Only alerts on actual position changes (new/removed/modified positions)
- **Telegram Notifications** - Sends formatted alerts with position details and links
- **Azure SQL Database** - Stores historical snapshots and position data
- **Automated Refreshes** - Azure Functions timer trigger (every 5 minutes)
- **Multi-user Support** - Track multiple wallets simultaneously

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Console App   │    │  Azure Function │    │  Telegram Bot   │
│  (Testing/Dev)  │    │ (Every 5 mins)  │    │ (Notifications) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Core Library  │
                    │  - Models       │
                    │  - Services     │
                    │  - Extensions   │
                    └─────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Hyperliquid API │    │  Azure SQL DB   │    │   Change Logic  │
│  (Position Data)│    │  (Snapshots)    │    │  (Comparison)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📊 Database Schema

### Tables
- **HLUser** - Tracked users/wallets (`Id`, `Name`)
- **HLSnapshot** - Position snapshots over time (`Id`, `UserId`, `Json`, `Timestamp`, `CreatedUtc`)
- **HLPosition** - Individual position details (`Id`, `UserId`, `SnapshotId`, `Coin`, `Size`, `PositionValue`, `EntryPx`, `CreatedUtc`)

## 🛠️ Setup & Installation

### Prerequisites
- .NET 8.0 SDK
- Azure SQL Database
- Telegram Bot Token
- Hyperliquid wallet addresses to monitor

### 1. Clone and Build
```bash
git clone <repository-url>
cd crypto-stalker
dotnet restore
dotnet build
```

### 2. Configure Database
Update `appsettings.json` with your Azure SQL connection string:
```json
{
  "ConnectionStrings": {
    "CryptoStalker": "Server=tcp:your-server.database.windows.net,1433;Initial Catalog=CryptoStalker;User ID=your-user;Password=your-password;...",
    "TelegramBot": "https://api.telegram.org/bot{YOUR_BOT_TOKEN}"
  }
}
```

### 3. Database Setup
Create the required tables in your Azure SQL Database:
```sql
CREATE TABLE HLUser (
    Id NVARCHAR(100) PRIMARY KEY,
    Name NVARCHAR(100) NOT NULL
);

CREATE TABLE HLSnapshot (
    Id BIGINT IDENTITY(1,1) PRIMARY KEY,
    UserId NVARCHAR(100) NOT NULL,
    Json NVARCHAR(MAX) NOT NULL,
    Timestamp DATETIME2 NOT NULL,
    CreatedUtc DATETIME2 NOT NULL,
    FOREIGN KEY (UserId) REFERENCES HLUser(Id)
);

CREATE TABLE HLPosition (
    Id BIGINT IDENTITY(1,1) PRIMARY KEY,
    UserId NVARCHAR(100) NOT NULL,
    SnapshotId BIGINT NOT NULL,
    Coin NVARCHAR(50) NOT NULL,
    Size DECIMAL(18,8) NOT NULL,
    PositionValue DECIMAL(18,2) NOT NULL,
    EntryPx DECIMAL(18,8) NOT NULL,
    CreatedUtc DATETIME2 NOT NULL,
    FOREIGN KEY (UserId) REFERENCES HLUser(Id),
    FOREIGN KEY (SnapshotId) REFERENCES HLSnapshot(Id)
);
```

### 4. Add Users to Track
Insert wallet addresses you want to monitor:
```sql
INSERT INTO HLUser (Id, Name) VALUES 
('0xc0ee908e7bf8c8f11b039154f9f7a6230f9883f9', 'test09876'),
('0x8fc7c0442e582bca195978c5a4fdec2e7c5bb0f7', 'Elsewhere');
```

### 5. Configure Telegram
1. Create a Telegram bot via [@BotFather](https://t.me/botfather)
2. Get your bot token
3. Update the `TelegramBot` connection string in `appsettings.json`
4. Update `MainChatId` in `TelegramService.cs` with your chat ID

## 🚀 Usage

### Local Development
```bash
cd crypto-stalker
dotnet run
```

### Azure Functions Deployment
1. Deploy the Azure Function project (`CryptoStalkerFunction.csproj`)
2. Configure the function to call your main API endpoint
3. Function runs automatically every 5 minutes

### Manual Testing
The console app includes a test method that:
- Fetches current position data from Hyperliquid
- Compares with previous snapshot
- Shows detected changes
- Sends notifications (if configured)

## 📱 Telegram Notifications

Example notification format:
```
test09876: [BTC] | Change (+2.5) | $45,230.50 to $47,730.50
test09876: Add | [ETH] | $12,450.75
test09876: Removed | [LINK] | $892.30
```

Each message includes:
- User name
- Action (Change/Add/Removed)
- Coin symbol
- Position values
- Link to Hyperliquid vault

## 🔧 Configuration

### Key Files
- `appsettings.json` - Database and API configuration
- `Program.cs` - Console app entry point and testing
- `Core/Extensions/AppExtensions.cs` - Dependency injection setup
- `Core/Services/` - Business logic (API, Database, Telegram)

### Environment Variables (Production)
For production deployment, use environment variables instead of hardcoded connection strings:
```bash
ConnectionStrings__CryptoStalker="your-db-connection"
ConnectionStrings__TelegramBot="https://api.telegram.org/bot{token}"
```

## 🧪 Testing

### Test User Configuration
The project includes a test configuration in `Program.cs`:
```csharp
var user = new HyperliquidUser
{
    Id = "0xc0ee908e7bf8c8f11b039154f9f7a6230f9883f9",
    Name = "test09876"
};
```

### Manual Testing Steps
1. Run the console app: `dotnet run`
2. Check console output for API responses
3. Verify database entries in `HLSnapshot` and `HLPosition` tables
4. Test Telegram notifications

## 📈 Monitoring

### Azure Application Insights
The project includes Application Insights integration for:
- Function execution monitoring
- Error tracking
- Performance metrics
- API call logging

### Logs and Debugging
- Console app: Real-time console output
- Azure Functions: Application Insights logs
- Database: Query `HLSnapshot` table for historical data

## ⚠️ Important Notes

### Security
- **Never commit sensitive data** (connection strings, tokens)
- Use Azure Key Vault or environment variables in production
- Secure your database with proper firewall rules

### Rate Limits
- Hyperliquid API: No specific limits mentioned, but use responsibly
- Telegram Bot API: 30 messages/second limit
- Azure Functions: Pay attention to execution limits

### Cost Considerations
- Azure SQL Database: Based on DTU/vCore usage
- Azure Functions: Consumption plan recommended for this use case
- Storage: Minimal for this application

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is for educational purposes. Use responsibly and in accordance with all applicable terms of service.

## 🆘 Support

For issues:
1. Check the logs (console or Application Insights)
2. Verify database connectivity
3. Test API endpoints manually
4. Check Telegram bot configuration

Common issues:
- **Database connection errors**: Verify connection string and firewall rules
- **No notifications**: Check Telegram bot token and chat ID
- **Missing position data**: Verify Hyperliquid API responses
- **Build errors**: Ensure .NET 8.0 SDK is installed