# Vault Alert Bot (Clean Render Version)

This bot sends a test Telegram alert using environment variables.

## How to Deploy

1. Upload these files to GitHub
2. Create a new Render Background Worker
3. Select Python 3 as the Environment
4. Set Start Command: `python main.py`
5. Add environment variables:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
6. Deploy and check logs