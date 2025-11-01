#!/usr/bin/env bash
set -euo pipefail
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
streamlit run teletriagem/frontend/Home.py --server.port "${UI_PORT:-8501}"
