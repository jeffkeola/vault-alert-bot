#!/usr/bin/env python3
"""
Azure Container Deployment Helper
Prepares JWOvaultbot for Azure Container Instance deployment
"""

import os
import zipfile
import shutil

def create_deployment_package():
    """Create a deployment package for Azure"""
    
    print("📦 Creating deployment package for Azure...")
    
    # Files to include in deployment
    files_to_deploy = [
        'jwovaultbot.py',
        'confluence_engine.py', 
        'start_bot.py',
        'requirements.txt'
    ]
    
    # Create deployment directory
    deploy_dir = 'azure_deployment'
    if os.path.exists(deploy_dir):
        shutil.rmtree(deploy_dir)
    os.makedirs(deploy_dir)
    
    # Copy files
    for file in files_to_deploy:
        if os.path.exists(file):
            shutil.copy2(file, deploy_dir)
            print(f"✅ Added {file}")
        else:
            print(f"⚠️ Warning: {file} not found")
    
    # Create a startup script for Azure
    startup_script = """#!/bin/bash
echo "🚀 Starting JWOvaultbot in Azure Container..."
cd /app
pip install -r requirements.txt
echo "✅ Dependencies installed"
python start_bot.py
"""
    
    with open(f'{deploy_dir}/startup.sh', 'w') as f:
        f.write(startup_script)
    
    # Make startup script executable
    os.chmod(f'{deploy_dir}/startup.sh', 0o755)
    
    # Create Dockerfile for container
    dockerfile_content = """FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x startup.sh

# Run the startup script
CMD ["./startup.sh"]
"""
    
    with open(f'{deploy_dir}/Dockerfile', 'w') as f:
        f.write(dockerfile_content)
    
    print(f"\n📁 Deployment package created in '{deploy_dir}' directory")
    print("🔧 Files included:")
    for file in os.listdir(deploy_dir):
        print(f"   • {file}")
    
    return deploy_dir

def create_zip_package():
    """Create a zip file for easy upload"""
    deploy_dir = create_deployment_package()
    
    zip_filename = 'jwovaultbot_deployment.zip'
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(deploy_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, deploy_dir)
                zipf.write(file_path, arcname)
    
    print(f"\n📦 Created deployment zip: {zip_filename}")
    print("📤 Ready for upload to Azure!")
    
    return zip_filename

if __name__ == "__main__":
    create_zip_package()