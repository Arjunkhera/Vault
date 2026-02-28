#!/bin/bash
set -e

# Clone knowledge repo if not already present (skip if SKIP_GIT_CLONE is set)
if [ "$SKIP_GIT_CLONE" != "true" ]; then
    if [ ! -d "/data/knowledge-repo/.git" ]; then
        echo "Cloning knowledge repo..."
        git clone "https://${GITHUB_TOKEN}@github.intuit.com/${KNOWLEDGE_REPO:-fdp-docmgmt/knowledge-base}.git" /data/knowledge-repo
    fi
else
    echo "Skipping git clone (SKIP_GIT_CLONE=true)"
fi

# Verify knowledge repo exists
if [ ! -d "/data/knowledge-repo" ]; then
    echo "ERROR: Knowledge repo not found at /data/knowledge-repo"
    exit 1
fi

# Start the Python service (sync daemon runs as background tasks inside the app)
cd /app
exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
