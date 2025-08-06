# Azure SQL Database Integration Guide

This guide will help you migrate JWOvaultbot from local SQLite to Azure SQL Database.

## Prerequisites
- Azure account
- Azure SQL Database created
- Connection string from Azure

## Setup Steps

### 1. Install Azure Dependencies
```bash
pip install pyodbc
# On Ubuntu/Debian, you might also need:
sudo apt-get install unixodbc-dev
```

### 2. Get Your Azure Connection String
In Azure Portal, go to your SQL Database > Connection strings > ODBC

Example format:
```
Driver={ODBC Driver 18 for SQL Server};Server=tcp:yourserver.database.windows.net,1433;Database=yourdatabase;Uid=yourusername;Pwd=yourpassword;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;
```

### 3. Set Environment Variable
```bash
export AZURE_SQL_CONNECTION="your_connection_string_here"
```

### 4. Database Migration Script

Create and run this migration script:

```python
import sqlite3
import pyodbc
import os

def migrate_to_azure():
    # Connect to SQLite
    sqlite_conn = sqlite3.connect('jwovaultbot.db')
    
    # Connect to Azure SQL
    azure_conn_str = os.getenv('AZURE_SQL_CONNECTION')
    azure_conn = pyodbc.connect(azure_conn_str)
    
    # Create tables in Azure SQL
    azure_cursor = azure_conn.cursor()
    
    # Create tables (modify data types for SQL Server)
    azure_cursor.execute('''
        CREATE TABLE tracked_addresses (
            id INT IDENTITY(1,1) PRIMARY KEY,
            address NVARCHAR(255) UNIQUE NOT NULL,
            type NVARCHAR(50) NOT NULL CHECK (type IN ('vault', 'wallet')),
            name NVARCHAR(255),
            weight REAL DEFAULT 1.0,
            added_date DATETIME2 DEFAULT GETDATE(),
            active BIT DEFAULT 1
        )
    ''')
    
    # Add other tables...
    
    # Migrate data
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute('SELECT * FROM tracked_addresses')
    
    for row in sqlite_cursor.fetchall():
        azure_cursor.execute('''
            INSERT INTO tracked_addresses (address, type, name, weight, added_date, active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', row[1:])  # Skip ID column
    
    azure_conn.commit()
    print("✅ Migration completed!")
```

### 5. Update JWOvaultbot

Modify the `init_database()` method in `jwovaultbot.py`:

```python
def init_database(self):
    """Initialize database (SQLite or Azure SQL)"""
    azure_conn_str = os.getenv('AZURE_SQL_CONNECTION')
    
    if azure_conn_str:
        # Use Azure SQL Database
        import pyodbc
        self.conn = pyodbc.connect(azure_conn_str)
        print("🟢 Connected to Azure SQL Database")
        # Create tables with SQL Server syntax
        self.create_azure_tables()
    else:
        # Use SQLite
        self.conn = sqlite3.connect('jwovaultbot.db', check_same_thread=False)
        print("🟡 Using local SQLite database")
        # Create tables with SQLite syntax
        self.create_sqlite_tables()
```

## Security Notes

1. **Never commit connection strings to code**
2. **Use Azure Key Vault for production**
3. **Enable firewall rules for your IP**
4. **Use service principals for automated deployments**

## Testing Connection

Test your Azure connection:

```python
import pyodbc
import os

try:
    conn_str = os.getenv('AZURE_SQL_CONNECTION')
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    print("✅ Azure SQL connection successful!")
    conn.close()
except Exception as e:
    print(f"❌ Connection failed: {e}")
```

## Production Deployment

1. **Use Azure Container Instances** or **Azure App Service**
2. **Store secrets in Azure Key Vault**
3. **Use managed identity for authentication**
4. **Set up monitoring and alerts**

## Backup Strategy

- Azure SQL has automatic backups
- Consider point-in-time restore
- Export important data regularly

---

**Need help?** Contact your friend who's helping with Azure setup! 🚀