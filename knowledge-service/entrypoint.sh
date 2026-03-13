#!/bin/bash
set -e

# ── Privilege handling ────────────────────────────────────────────────────────
# Under Docker: chown bind-mounted dirs to appuser, then drop to appuser via gosu.
# Under Podman rootless: root inside the container is already the unprivileged
# host user (user-namespace remapping), and chown on virtiofs bind mounts fails
# with EPERM. Skip chown+gosu entirely and keep running as root.
if [ "$(id -u)" -eq 0 ] && [ "${HORUS_RUNTIME:-docker}" != "podman" ]; then
  chown -R appuser:appuser /data/knowledge-repo /data/workspace /home/appuser
  exec gosu appuser "$0" "$@"
fi

# Variables at top
KNOWLEDGE_REPO_PATH=${KNOWLEDGE_REPO_PATH:-/data/knowledge-repo}
WORKSPACE_PATH=${WORKSPACE_PATH:-/data/workspace}
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}
LOG_LEVEL=${LOG_LEVEL:-info}
VAULT_KNOWLEDGE_REPO_URL=${VAULT_KNOWLEDGE_REPO_URL:-}
VAULT_SYNC_INTERVAL=${VAULT_SYNC_INTERVAL:-300}
GITHUB_TOKEN=${GITHUB_TOKEN:-}
GITHUB_REPO=${GITHUB_REPO:-}
GITHUB_BASE_BRANCH=${GITHUB_BASE_BRANCH:-master}
HORUS_RUNTIME=${HORUS_RUNTIME:-docker}
PULL_PID=""
PYTHON_PID=""

# Clear stale safe.directory entries left over from a previous container restart.
# Without this, --add accumulates duplicates and a subsequent plain SET fails
# with "cannot overwrite multiple values" (git exit code 5), crash-looping the
# container under restart: unless-stopped.
git config --global --unset-all safe.directory 2>/dev/null || true

# Mark bind-mounted path as safe for git (CVE-2022-24765: ownership differs in container)
git config --global --add safe.directory "$KNOWLEDGE_REPO_PATH"

# JSON logging functions (matching Anvil style)
log() {
  echo "{\"level\":\"info\",\"message\":\"$1\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" >&2
}

log_err() {
  echo "{\"level\":\"error\",\"message\":\"$1\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" >&2
}

# SIGTERM handler (defined BEFORE use)
shutdown() {
  log "Shutdown signal received — cleaning up..."
  if [ -n "$PULL_PID" ] && kill -0 "$PULL_PID" 2>/dev/null; then
    kill "$PULL_PID"
    wait "$PULL_PID" 2>/dev/null || true
    log "Pull daemon stopped"
  fi
  if [ -n "$PYTHON_PID" ] && kill -0 "$PYTHON_PID" 2>/dev/null; then
    kill "$PYTHON_PID"
    wait "$PYTHON_PID" 2>/dev/null || true
  fi
  exit 0
}
trap shutdown SIGTERM SIGINT

log "=== Vault Knowledge Service ==="
log "Knowledge repo: $KNOWLEDGE_REPO_PATH"
log "Workspace: $WORKSPACE_PATH"
log "Port: $PORT"
log "Host: $HOST"
log "Log level: $LOG_LEVEL"

# ── Podman runtime fixups ────────────────────────────────────────────────────
# Under Podman with user-namespace remapping, bind-mounted directories may be
# owned by a remapped UID. Fix ownership so appuser can write.
# Under Docker Desktop (macOS gRPC-FUSE), chown on bind mounts fails on
# read-only git objects (mode 0444) — skip it entirely.
if [ "$HORUS_RUNTIME" = "podman" ]; then
  chown -R appuser:appuser /data/knowledge-repo 2>/dev/null || true
  chown -R appuser:appuser /data/workspace 2>/dev/null || true
  chown -R appuser:appuser /home/appuser/.cache/qmd 2>/dev/null || true
  git config --global --replace-all safe.directory '*'
fi

# Fail fast if no repo configured and no data present
if [ -z "$VAULT_KNOWLEDGE_REPO_URL" ] && [ ! -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
  log_err "VAULT_KNOWLEDGE_REPO_URL is not set and $KNOWLEDGE_REPO_PATH has no .git directory. Cannot start."
  exit 1
fi

# Reject SSH URLs — container has no SSH binary or keys; HTTPS + GITHUB_TOKEN required
if echo "$VAULT_KNOWLEDGE_REPO_URL" | grep -qE '^(git@|ssh://)'; then
  log_err "SSH repo URLs are not supported in the container (no SSH binary or keys). Set VAULT_KNOWLEDGE_REPO_URL to an HTTPS URL (https://github.com/owner/repo) and provide GITHUB_TOKEN."
  exit 1
fi

# Clone if not already present
if [ -n "$VAULT_KNOWLEDGE_REPO_URL" ] && [ ! -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
  log "Cloning knowledge repo from $VAULT_KNOWLEDGE_REPO_URL..."
  if [ -n "$GITHUB_TOKEN" ]; then
    CLONE_URL=$(echo "$VAULT_KNOWLEDGE_REPO_URL" | sed "s|https://|https://${GITHUB_TOKEN}@|")
  else
    CLONE_URL="$VAULT_KNOWLEDGE_REPO_URL"
  fi
  git clone "$CLONE_URL" "$KNOWLEDGE_REPO_PATH" || {
    log_err "Failed to clone knowledge repo"
    exit 1
  }
  log "Knowledge repo cloned successfully"
fi

# Derive GITHUB_REPO from VAULT_KNOWLEDGE_REPO_URL if not already set
# Converts https://github.com/owner/repo.git → owner/repo
if [ -z "$GITHUB_REPO" ] && [ -n "$VAULT_KNOWLEDGE_REPO_URL" ]; then
  GITHUB_REPO=$(echo "$VAULT_KNOWLEDGE_REPO_URL" | sed -E 's|^[a-z]+://[^/]+/||' | sed 's|\.git$||')
  log "Derived GITHUB_REPO from URL: $GITHUB_REPO"
fi

# Configure git credentials and identity for any push operations
if [ -n "$GITHUB_TOKEN" ] && [ -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
  git -C "$KNOWLEDGE_REPO_PATH" config credential.helper "store"
  echo "https://oauth2:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
fi
git -C "$KNOWLEDGE_REPO_PATH" config user.email "horus@local" 2>/dev/null || true
git -C "$KNOWLEDGE_REPO_PATH" config user.name "Horus Vault Sync" 2>/dev/null || true

# Reconcile remote URL — if existing clone has SSH remote but VAULT_KNOWLEDGE_REPO_URL is HTTPS, update it
if [ -n "$VAULT_KNOWLEDGE_REPO_URL" ] && [ -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
  CURRENT_REMOTE=$(git -C "$KNOWLEDGE_REPO_PATH" remote get-url origin 2>/dev/null || echo "")
  if echo "$CURRENT_REMOTE" | grep -qE '^(git@|ssh://)'; then
    log "Existing clone has SSH remote ($CURRENT_REMOTE) — updating to HTTPS..."
    if [ -n "$GITHUB_TOKEN" ]; then
      NEW_REMOTE=$(echo "$VAULT_KNOWLEDGE_REPO_URL" | sed "s|https://|https://${GITHUB_TOKEN}@|")
    else
      NEW_REMOTE="$VAULT_KNOWLEDGE_REPO_URL"
      log_err "Warning: GITHUB_TOKEN not set — remote updated to plain HTTPS, push operations may fail"
    fi
    git -C "$KNOWLEDGE_REPO_PATH" remote set-url origin "$NEW_REMOTE"
    log "Remote URL updated to HTTPS"
  fi
fi

# Bootstrap _schema/ from defaults if schema.yaml is missing
if [ ! -f "$KNOWLEDGE_REPO_PATH/_schema/schema.yaml" ]; then
  log "Bootstrapping _schema/ from defaults..."
  mkdir -p "$KNOWLEDGE_REPO_PATH/_schema/registries"
  cp /app/defaults/_schema/schema.yaml "$KNOWLEDGE_REPO_PATH/_schema/"
  cp /app/defaults/_schema/registries/*.yaml "$KNOWLEDGE_REPO_PATH/_schema/registries/"
  log "_schema/ bootstrapped"
  if [ -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
    git -C "$KNOWLEDGE_REPO_PATH" add "_schema/" 2>/dev/null || true
    git -C "$KNOWLEDGE_REPO_PATH" commit -m "bootstrap: add default _schema" 2>/dev/null || true
    git -C "$KNOWLEDGE_REPO_PATH" push 2>/dev/null || log_err "Bootstrap push failed (non-fatal)"
    log "Bootstrap committed and pushed"
  fi
fi

# Workspace dir
mkdir -p "$WORKSPACE_PATH"

# Background pull daemon
if [ -d "$KNOWLEDGE_REPO_PATH/.git" ]; then
  log "Starting pull daemon (interval: ${VAULT_SYNC_INTERVAL}s)..."
  (
    while true; do
      sleep "$VAULT_SYNC_INTERVAL"
      log "Running git pull..."
      git -C "$KNOWLEDGE_REPO_PATH" pull --ff-only 2>/dev/null || {
        log_err "Git pull failed (will retry next cycle)"
      }
    done
  ) &
  PULL_PID=$!
  log "Pull daemon started (PID: $PULL_PID)"
fi

# Start uvicorn as background + wait
log "Starting Vault knowledge service on ${HOST}:${PORT}..."
cd /app
GITHUB_REPO="$GITHUB_REPO" \
GITHUB_BASE_BRANCH="$GITHUB_BASE_BRANCH" \
GITHUB_TOKEN="$GITHUB_TOKEN" \
python -m uvicorn src.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --log-level "$LOG_LEVEL" &

PYTHON_PID=$!
log "Vault service started (PID: $PYTHON_PID)"

wait "$PYTHON_PID"
