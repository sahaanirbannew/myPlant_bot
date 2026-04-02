# myPlant_bot

`myPlant_bot` is a FastAPI-based Telegram bot that stores a per-user Gemini API key, validates it during setup, and answers safe text questions in the background with Gemini `2.5-flash`.

## Features

- FastAPI webhook service for Telegram Bot API updates
- `/setup` flow that asks for a Gemini API key, stores it in CSV, validates it, and retries on failure
- In-memory per-user session cache that expires after 3 minutes of inactivity
- Text-only request handling with simple jailbreak detection
- Background Gemini question answering with 5 retries and 2-second backoff, without an interim status message
- Telegram replies are normalized to plain text by removing `**` bold markers from model output
- GitHub Actions deployment to EC2 over SSH
- `systemd` service for automatic restart and idempotent production deployment

## Project structure

```text
.
├── .github/workflows/deploy.yml
├── app/
│   ├── config.py
│   ├── main.py
│   ├── models.py
│   └── services/
├── scripts/ec2_setup.sh
├── systemd/myplant-bot.service
├── requirements.txt
└── DOCUMENTATION.md
```

## Local setup

1. Create the virtual environment:

   ```bash
   python3 -m venv .venv
   ```

2. Activate it:

   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Review `.env` and update values that should differ from local defaults.

5. Run the app:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. Run the tests:

   ```bash
   pytest
   ```

## Telegram webhook flow

- `POST /telegram/webhook` receives Telegram updates.
- `POST /telegram/register-webhook` registers the webhook URL defined by `APP_BASE_URL`.
- `GET /health` returns a simple readiness payload.

## Production TLS note

Telegram webhooks require HTTPS. For the current EC2 setup, the deployment uses a self-signed certificate on port `8443`, which Telegram supports when the public certificate is uploaded during `setWebhook`.

## GitHub Actions deployment

Every push to `main` runs `.github/workflows/deploy.yml`, which:

- connects to EC2 over SSH using GitHub Secrets
- clones the repo on first deployment or resets it to `origin/main`
- writes the production `.env`
- recreates the virtual environment
- installs dependencies from `requirements.txt`
- restarts the `systemd` service

The workflow supports both Ubuntu-style hosts and Amazon Linux hosts. During validation against the current instance, the target host was confirmed to be Amazon Linux 2023 with `python3` and `systemd` already available.

## Required GitHub Actions variables

- `EC2_HOST`: Public EC2 hostname or IP address
- `EC2_USER`: SSH user, for your instance `ec2-user`
- `EC2_APP_DIR`: Remote deployment directory, for this host `/home/ec2-user/myPlant_bot`
- `EC2_GITHUB_REPOSITORY_URL`: Git clone URL reachable from EC2, for example `https://github.com/sahaanirbannew/myPlant_bot.git`
- `EC2_KNOWN_HOSTS`: Pinned `known_hosts` entry for the EC2 server

## Required GitHub Secrets

- `EC2_SSH_PRIVATE_KEY`: Private key matching the EC2 authorized key
- `EC2_ENV_FILE_BASE64`: Base64-encoded production `.env` content

## Security note

The Telegram bot token was provided in the request and has been placed in the local `.env`, which is git-ignored. Because it was shared in chat, rotate it in Telegram BotFather before production use.
