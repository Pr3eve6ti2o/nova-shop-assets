#!/bin/bash
# Test bot startup script - starts rental mock backend + bot with all required env vars
# Created 2026-10-11: prevents "payment provider unreachable" and "rental not working"
# issues after VM restarts by ensuring all dependencies start together.

set -e

# 1. Start rental mock backend (if not already running)
if ! curl -s -m 3 -H "x-api-key: test-key-123" http://localhost:3002/api/internal/plans > /dev/null 2>&1; then
    echo "Starting rental mock backend on :3002..."
    NOVA_API_KEY=test-key-123 nohup python3 ~/workspace/goals/nova-shop-bot/files/mock-rental-backend.py > /tmp/rental-mock.log 2>&1 &
    sleep 2
fi

# 2. Start the test bot (loads .env from bot/ directory)
cd ~/workspace/nova-shop-repo/bot
if [ ! -f .env ]; then
    echo "ERROR: bot/.env not found" >&2
    exit 1
fi
set -a
source .env
set +a
nohup /home/hatch/workspace/shop-bot/.venv/bin/python app.py > /tmp/testbot.log 2>&1 &

echo "Test bot startup complete"
