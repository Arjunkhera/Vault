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

# Install QMD from source, pinned to a known-good commit.
#
# WHY PINNED: We apply a source-level patch (below) to force `gpu: false` in
# llm.js. That patch targets a specific code pattern. Floating on `main` means
# any upstream refactor of ensureLlama() silently breaks the sed command —
# the build succeeds, the patch is a no-op, and the CUDA probe re-appears at
# runtime (~8s startup penalty on every container boot).
#
# TO UPGRADE: bump the SHA below, rebuild, and verify the GPU patch still
# applies by checking `docker run --rm horus-vault qmd --version` completes
# in <2s. If it hangs for ~8s, the patch needs updating.
#
# Pinned SHA: 40610c3 (2026-03-02 — known-good, GPU patch verified)
ARG QMD_SHA=40610c3aa65d9d399ebb188a7e4930f6628ae51c
RUN git clone https://github.com/tobi/qmd.git /opt/qmd \
    && cd /opt/qmd \
    && git checkout ${QMD_SHA} \
    && npm install \
    && npm run build \
    && printf '#!/bin/sh\nexec node /opt/qmd/dist/qmd.js "$@"\n' > /usr/local/bin/qmd \
    && chmod +x /usr/local/bin/qmd

# Patch QMD: force gpu:false to skip CUDA auto-detection.
#
# Podman/QEMU falsely reports CUDA available, triggering an ~8s cmake build
# probe that always fails before falling back to the CPU prebuilt (~160ms).
# This patch surgically replaces the getLlama() call inside ensureLlama() to
# hard-code `gpu: false`, bypassing the detection entirely.
#
# The sed command targets the specific block structure in llm.js at the pinned
# SHA above. If you bump QMD_SHA and this patch stops applying (build succeeds
# but startup takes 8s), update the sed pattern to match the new structure.
RUN <<'EOF'
sed -i '/async ensureLlama() {/,/return this\.llama;/{
  /if (!this\.llama) {/,/return this\.llama;/c\
        if (!this.llama) {\
            this.llama = await getLlama({ gpu: false, logLevel: LlamaLogLevel.error });\
        }\
        return this.llama;
}' /opt/qmd/dist/llm.js
EOF

# Create non-root user for security (with home dir so QMD can write ~/.config/qmd and ~/.local/share/qmd)
RUN useradd -m -r -s /bin/bash appuser \
    && mkdir -p /home/appuser/.config/qmd /home/appuser/.local/share/qmd \
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

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
