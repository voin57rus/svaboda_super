#!/bin/bash

echo 🚀 Updating project...

cd /root/svaboda_super || {
    echo ❌ Project folder not found
    exit 1
}

git fetch origin
git reset --hard origin/main

echo "🧹 Clearing __pycache__..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

echo "🔄 Restarting bot via systemd..."

systemctl restart svaboda_super.service

sleep 2

systemctl is-active svaboda_super.service

echo ✅ Update complete
