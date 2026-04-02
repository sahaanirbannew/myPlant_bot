#!/usr/bin/env bash

set -euo pipefail

# This script prepares an Ubuntu EC2 host for idempotent FastAPI deployments.

APP_NAME="myplant-bot"
APP_USER="ubuntu"
APP_DIR="/opt/${APP_NAME}"
PYTHON_VERSION="python3.11"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

echo "[1/8] Installing OS packages..."
sudo apt-get update -y
sudo apt-get install -y git curl software-properties-common

echo "[2/8] Installing Python runtime..."
sudo add-apt-repository -y ppa:deadsnakes/ppa || true
sudo apt-get update -y
sudo apt-get install -y "${PYTHON_VERSION}" "${PYTHON_VERSION}-venv" "${PYTHON_VERSION}-distutils"

echo "[3/8] Creating application directory..."
sudo mkdir -p "${APP_DIR}"
sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "[4/8] Ensuring git safe directory..."
git config --global --add safe.directory "${APP_DIR}" || true

echo "[5/8] Writing systemd service unit..."
sudo tee "${SERVICE_FILE}" > /dev/null <<'EOF'
[Unit]
Description=myPlant FastAPI Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/myplant-bot
EnvironmentFile=/opt/myplant-bot/.env
ExecStart=/opt/myplant-bot/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "[6/8] Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl enable "${APP_NAME}.service"

echo "[7/8] Opening the application port if UFW is enabled..."
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 8000/tcp || true
fi

echo "[8/8] EC2 bootstrap complete."
echo "Next steps:"
echo "- Clone the repository into ${APP_DIR}"
echo "- Copy a production .env into ${APP_DIR}/.env"
echo "- Run the GitHub Actions workflow by pushing to main"

