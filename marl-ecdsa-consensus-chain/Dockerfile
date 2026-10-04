# =============================================================================
# MARL-ECDSA Consensus Chain — Docker Image
# CCF 5th Blockchain Competition | Version 4.1
# =============================================================================
# Build:
#   docker build -t marl-ecdsa-chain .
#
# Run (interactive menu):
#   docker run -it --rm -p 9090:9090 marl-ecdsa-chain
#
# Run (full experiment):
#   docker run -it --rm -p 9090:9090 marl-ecdsa-chain --experiment
#
# Run (dashboard only):
#   docker run -it --rm -p 9090:9090 marl-ecdsa-chain --dashboard
# =============================================================================

FROM python:3.12-slim

LABEL org.opencontainers.image.title="MARL-ECDSA Consensus Chain"
LABEL org.opencontainers.image.description="Blockchain-AI Synergistic Consensus for Multi-Agent Reinforcement Learning"
LABEL org.opencontainers.image.version="4.1"
LABEL org.opencontainers.image.authors="MARL-ECDSA Consensus Chain Team"
LABEL org.opencontainers.image.source="CCF 5th Blockchain Competition"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Create directories for outputs
RUN mkdir -p /app/results /app/keys /app/plots

# Expose dashboard port
EXPOSE 9090

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default entrypoint
ENTRYPOINT ["python", "main.py"]

# Default command: quick demo
CMD ["--demo"]
