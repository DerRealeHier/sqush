#!/bin/bash
set -e

REPO_DIR="/root/sqush"
cd "$REPO_DIR"

# Fetch latest changes from GitHub
git fetch origin main --quiet

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    echo "[$(date)] Update detected: $LOCAL_HASH -> $REMOTE_HASH"
    
    # Pull new code
    git pull origin main
    
    # Install dependencies if requirements.txt changed
    if git diff --name-only "$LOCAL_HASH" "$REMOTE_HASH" | grep -q "requirements.txt"; then
        echo "requirements.txt changed. Installing dependencies..."
        /root/sqush/.venv/bin/pip install -r requirements.txt --quiet
    fi
    
    # Restart the application service
    echo "Restarting sqush.service..."
    systemctl restart sqush
    echo "[$(date)] Deployment successful!"
fi
