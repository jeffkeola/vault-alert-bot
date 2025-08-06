#!/bin/bash
echo "🚀 Starting JWOvaultbot in Azure Container..."
cd /app
pip install -r requirements.txt
echo "✅ Dependencies installed"
python start_bot.py
