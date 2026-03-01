FROM python:3.12-bookworm

# python:3.12-bookworm includes gcc, g++, make, and dev headers
# We add cmake (needed if node-llama-cpp falls back to source build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (QMD v1.0.8 requires Node >= 22)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install QMD v1.0.8 from source
RUN git clone https://github.com/tobi/qmd.git /opt/qmd \
    && cd /opt/qmd \
    && npm install \
    && npm run build
ENV PATH="/opt/qmd:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN mkdir -p /data/knowledge-repo /workspace

EXPOSE 8000

ENV KNOWLEDGE_REPO=akhera/knowledge-base
ENV SYNC_INTERVAL=300
ENV QMD_INDEX_NAME=knowledge

CMD ["./entrypoint.sh"]
