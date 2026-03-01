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

# Install curl for health checks, git for repo operations, and build dependencies for QMD
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (QMD v1.0.8 requires Node >= 22)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install QMD v1.0.8 from source
RUN git clone https://github.com/tobi/qmd.git /opt/qmd \
    && cd /opt/qmd \
    && npm install \
    && npm run build

# Patch QMD: force gpu:false to skip CUDA auto-detection
# Podman/QEMU falsely reports CUDA available, triggering an ~8s cmake build
# probe that always fails before falling back to the CPU prebuilt (~160ms)
RUN sed -i '/async ensureLlama() {/,/return this\.llama;/{
  /if (!this\.llama) {/,/return this\.llama;/c\
        if (!this.llama) {\
            this.llama = await getLlama({ gpu: false, logLevel: LlamaLogLevel.error });\
        }\
        return this.llama;
}' /opt/qmd/dist/llm.js

ENV PATH="/opt/qmd:${PATH}"

# Create non-root user for security
RUN useradd -r -s /bin/false appuser

# Copy Python dependencies from builder
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages/

# Copy application code
COPY src/ ./src/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directories (will be mounted or populated at runtime)
RUN mkdir -p /data/knowledge-repo /data/workspace && chown -R appuser:appuser /data /app

# Health check: verify the service is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
