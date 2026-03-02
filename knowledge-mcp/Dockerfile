# ─── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM node:22-bookworm-slim AS builder

WORKDIR /build

# Copy manifests first (layer cache)
COPY package.json package-lock.json tsconfig.json ./

# Install all deps (including devDependencies for TypeScript compilation)
RUN npm ci

# Copy source
COPY src/ ./src/

# Compile TypeScript → dist/
RUN npm run build


# ─── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM node:22-bookworm-slim

# curl for health checks only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -ms /bin/bash vault-mcp

WORKDIR /app

# Install production dependencies only
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Copy compiled output from builder
COPY --from=builder /build/dist/ ./dist/

RUN chown -R vault-mcp:vault-mcp /app

USER vault-mcp

EXPOSE 8300

# Environment configuration with defaults
ENV VAULT_MCP_HTTP=true
ENV VAULT_MCP_PORT=8300
ENV VAULT_MCP_HOST=0.0.0.0
# KNOWLEDGE_SERVICE_URL is set by docker-compose to the internal vault service URL
ENV KNOWLEDGE_SERVICE_URL=http://vault:8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8300/health || exit 1

CMD ["node", "/app/dist/index.js", "--http", "--port", "8300"]
