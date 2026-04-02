#!/usr/bin/env bash

set -euo pipefail

# Task: Start the FastAPI application with optional TLS based on environment variables.
# Input: Environment variables such as APP_HOST, APP_PORT, SSL_CERTFILE, and SSL_KEYFILE.
# Output: A running uvicorn process for the Telegram bot application.
# Failures: Exits non-zero if the virtualenv or SSL files are missing, or uvicorn cannot start.

APP_DIR="${APP_DIR:-/home/ec2-user/myPlant_bot}"
HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
CERTFILE="${SSL_CERTFILE:-}"
KEYFILE="${SSL_KEYFILE:-}"
UVICORN_BIN="${APP_DIR}/.venv/bin/uvicorn"

if [ ! -x "${UVICORN_BIN}" ]; then
  echo "uvicorn executable not found at ${UVICORN_BIN}" >&2
  exit 1
fi

args=(
  "app.main:app"
  "--host" "${HOST}"
  "--port" "${PORT}"
)

if [ -n "${CERTFILE}" ] || [ -n "${KEYFILE}" ]; then
  if [ ! -f "${CERTFILE}" ] || [ ! -f "${KEYFILE}" ]; then
    echo "SSL_CERTFILE and SSL_KEYFILE must both exist when TLS is enabled." >&2
    exit 1
  fi
  args+=("--ssl-certfile" "${CERTFILE}" "--ssl-keyfile" "${KEYFILE}")
fi

cd "${APP_DIR}"
exec "${UVICORN_BIN}" "${args[@]}"

