#!/usr/bin/env bash

set -euo pipefail

# This script prepares an EC2 host for idempotent FastAPI deployments.
# It supports both Amazon Linux 2023 and Ubuntu-style package managers.

APP_NAME="myplant-bot"
APP_USER="${APP_USER:-ec2-user}"
APP_DIR="${APP_DIR:-/home/${APP_USER}/myPlant_bot}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

install_packages() {
  # Task: Install required operating system packages using the host package manager.
  # Input: Package names passed as positional shell arguments.
  # Output: Requested packages installed on the EC2 host.
  # Failures: Exits non-zero if neither dnf nor apt-get is available, or installation fails.
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "$@"
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y "$@"
    return
  fi

  echo "Unsupported package manager. Install git and Python 3 manually." >&2
  exit 1
}

echo "[1/6] Installing OS packages..."
if ! command -v git >/dev/null 2>&1; then
  install_packages git
fi
if ! command -v curl >/dev/null 2>&1; then
  install_packages curl
fi
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  install_packages python3
fi

echo "[2/6] Creating application directory..."
sudo mkdir -p "${APP_DIR}"
sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "[3/6] Ensuring git safe directory..."
git config --global --add safe.directory "${APP_DIR}" || true

echo "[4/6] Writing systemd service unit..."
sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=myPlant FastAPI Telegram Bot
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "[5/6] Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl enable "${APP_NAME}.service"

echo "[6/6] Opening the application port if a firewall manager is active..."
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 8000/tcp || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  sudo firewall-cmd --add-port=8000/tcp --permanent || true
  sudo firewall-cmd --reload || true
fi

echo "EC2 bootstrap complete."
echo "Next steps:"
echo "- Clone the repository into ${APP_DIR}"
echo "- Copy a production .env into ${APP_DIR}/.env"
echo "- Run the GitHub Actions workflow by pushing to main"
