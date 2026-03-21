# syntax=docker/dockerfile:1
# Multi-stage build: builder stage installs dependencies, final stage copies only what's needed
FROM python:3.12-slim AS builder

WORKDIR /build

# Upgrade pip for better caching
RUN pip install --upgrade pip --no-cache-dir

# Copy requirements and install to a target directory
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target /build/deps


# Final stage: lightweight runtime image
FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks, git for repo operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -r -s /bin/bash appuser \
    && chown -R appuser:appuser /home/appuser

# Copy Python dependencies from builder
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages/

# Copy application code
COPY src/ ./src/
COPY defaults/ ./defaults/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directories (will be mounted or populated at runtime)
RUN mkdir -p /data/knowledge-repo /data/workspace && chown -R appuser:appuser /data /app

# Health check: verify the service is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
