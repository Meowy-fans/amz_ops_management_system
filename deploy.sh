#!/bin/bash
# Deployment Script for Amz Listing Management System
# Usage: ./deploy.sh [environment]

set -e

# Default environment
ENV=${1:-production}

echo "========================================"
echo "Starting deployment for $ENV..."
echo "========================================"

# 1. Update Codebase
echo "Step 1: Pulling latest code..."
git pull origin main

# 2. Update Dependencies (Optional if Docker handles it, but good for local checking)
# echo "Step 2: Updating dependencies..."
# pip install -r requirements.txt

# 3. Build and Restart Containers
echo "Step 3: Rebuilding and restarting containers..."
if [ -f "docker-compose.yml" ]; then
    docker-compose down
    docker-compose up -d --build
else
    echo "Error: docker-compose.yml not found!"
    exit 1
fi

# 4. Check Status
echo "Step 4: Checking service status..."
sleep 5
docker-compose ps

echo "========================================"
echo "Deployment Completed Successfully!"
echo "========================================"
