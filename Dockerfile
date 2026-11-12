# =============================================================================
# BioMix-STR: Production Docker Container Definition
# Multi-platform deployment (Render, Cloud Run, Hugging Face Spaces, VPS)
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="BioMix-STR Engineering Team"
LABEL description="BioMix-STR: 3D Bioreactor CFD & Bioprocess Engineering Suite"

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/biomix_str/src" \
    PORT=8000 \
    HOST=0.0.0.0

# Install system dependencies for headless rendering and mesh processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglu1-mesa \
    libglib2.0-0 \
    libgomp1 \
    libxrender1 \
    libxcursor1 \
    libxinerama1 \
    libxft2 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and pre-computed CFD bundles
COPY biomix_str/ /app/biomix_str/
RUN pip install --no-cache-dir -e biomix_str

# Create non-root user for secure container execution
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose default HTTP/WebSocket port
EXPOSE 8000

# Health check to ensure API and static studio respond
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/status || exit 1

# Start Uvicorn ASGI server with dynamic port binding
CMD ["sh", "-c", "python -m uvicorn biomix.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
