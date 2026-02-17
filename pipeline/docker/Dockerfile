FROM node:20-slim

# Install system dependencies for Claude Code tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    ripgrep \
    curl \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user for security
RUN groupadd -r coder && useradd -r -g coder -m -s /bin/bash coder

# Create workspace and data directories
RUN mkdir -p /workspace /data && chown -R coder:coder /workspace /data

# Set git defaults so Claude Code can commit
RUN git config --system user.email "cloding@local" \
    && git config --system user.name "Cloding"

# Switch to non-root user
USER coder
WORKDIR /workspace

# Accept Claude Code terms non-interactively
ENV CLAUDE_CODE_ACCEPT_TOS=true

# Default entrypoint is claude CLI
ENTRYPOINT ["claude"]
