#!/usr/bin/env bash
# =============================================================================
# BioMix-STR Studio: Linux / macOS 1-Click Launcher
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================================"
echo "  BioMix-STR - Stirred-Tank Bioreactor CFD Studio"
echo "  FastAPI + Three.js 3D Hydrodynamics & Scale-Up Workbench"
echo "============================================================================"

# 1. Virtual environment setup
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (.venv)..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "[INFO] Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

export PYTHONPATH="$SCRIPT_DIR/biomix_str/src:$PYTHONPATH"

# 2. Open browser in background
(sleep 2 && (xdg-open http://127.0.0.1:8000 2>/dev/null || open http://127.0.0.1:8000 2>/dev/null || true)) &

echo "[INFO] Starting server on http://127.0.0.1:8000..."
python3 -m uvicorn biomix.server:app --host 127.0.0.1 --port 8000
