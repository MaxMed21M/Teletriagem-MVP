#!/usr/bin/env bash
set -euo pipefail
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
uvicorn teletriagem.api.main:app --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8000}" --reload
