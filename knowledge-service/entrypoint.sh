#!/bin/bash
set -e

# Set sensible defaults (can be overridden by env vars)
KNOWLEDGE_REPO_PATH=${KNOWLEDGE_REPO_PATH:-/data/knowledge-repo}
WORKSPACE_PATH=${WORKSPACE_PATH:-/data/workspace}
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}
LOG_LEVEL=${LOG_LEVEL:-info}

echo "=== Vault Knowledge Service ==="
echo "Knowledge repo: $KNOWLEDGE_REPO_PATH"
echo "Workspace:      $WORKSPACE_PATH"
echo "Port:           $PORT"
echo "Host:           $HOST"
echo "Log level:      $LOG_LEVEL"
echo ""

# Clone knowledge repo if KNOWLEDGE_REPO_URL is set and repo not already present
if [ -n "$KNOWLEDGE_REPO_URL" ] && [ "$SKIP_GIT_CLONE" != "true" ]; then
    if [ ! -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
        echo "Cloning knowledge repo from ${KNOWLEDGE_REPO_URL}..."
        if [ -n "$GITHUB_TOKEN" ]; then
            # Insert token into URL for auth (supports github.com URLs)
            AUTH_URL=$(echo "$KNOWLEDGE_REPO_URL" | sed "s|https://|https://${GITHUB_TOKEN}@|")
            git clone "$AUTH_URL" "$KNOWLEDGE_REPO_PATH"
        else
            git clone "$KNOWLEDGE_REPO_URL" "$KNOWLEDGE_REPO_PATH"
        fi
    fi
elif [ "$SKIP_GIT_CLONE" = "true" ]; then
    echo "Skipping git clone (SKIP_GIT_CLONE=true)"
fi

# Validate knowledge repo exists (could be volume-mounted or cloned above)
if [ ! -d "$KNOWLEDGE_REPO_PATH" ]; then
    echo "ERROR: Knowledge repo not found at $KNOWLEDGE_REPO_PATH"
    echo ""
    echo "You can either:"
    echo "  1. Mount a volume:  -v /path/to/repo:$KNOWLEDGE_REPO_PATH"
    echo "  2. Set KNOWLEDGE_REPO_URL and mount /data volume (for cloning inside container)"
    echo ""
    exit 1
fi

# Create workspace if it doesn't exist
mkdir -p "$WORKSPACE_PATH"

# Start uvicorn with all configured parameters
cd /app
exec python -m uvicorn src.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level "$LOG_LEVEL"
