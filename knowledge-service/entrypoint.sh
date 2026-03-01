#!/bin/bash
set -e

# Clone knowledge repo if KNOWLEDGE_REPO_URL is set and repo not already present
if [ -n "$KNOWLEDGE_REPO_URL" ] && [ "$SKIP_GIT_CLONE" != "true" ]; then
    if [ ! -d "/data/knowledge-repo/.git" ]; then
        echo "Cloning knowledge repo from ${KNOWLEDGE_REPO_URL}..."
        if [ -n "$GITHUB_TOKEN" ]; then
            # Insert token into URL for auth (supports github.com URLs)
            AUTH_URL=$(echo "$KNOWLEDGE_REPO_URL" | sed "s|https://|https://${GITHUB_TOKEN}@|")
            git clone "$AUTH_URL" /data/knowledge-repo
        else
            git clone "$KNOWLEDGE_REPO_URL" /data/knowledge-repo
        fi
    fi
elif [ "$SKIP_GIT_CLONE" = "true" ]; then
    echo "Skipping git clone (SKIP_GIT_CLONE=true)"
fi

# Verify knowledge repo exists (could be volume-mounted)
if [ ! -d "/data/knowledge-repo" ]; then
    echo "WARNING: Knowledge repo not found at /data/knowledge-repo"
    echo "Creating empty directory — mount a volume or set KNOWLEDGE_REPO_URL"
    mkdir -p /data/knowledge-repo
fi

# Start the Python service (sync daemon runs as background tasks inside the app)
cd /app
exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
