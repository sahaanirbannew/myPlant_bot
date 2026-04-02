# myPlant_bot

`myPlant_bot` is a FastAPI-based Telegram bot that stores a per-user Gemini API key, validates it during setup, and answers safe text questions in the background with Gemini `2.5-flash`.

This repository also contains `my_plants`, a separate deterministic backend for a file-based plant care assistant called `My Plants`.

## Features

- FastAPI webhook service for Telegram Bot API updates
- `/setup` flow that asks for a Gemini API key, stores it in CSV, validates it, and retries on failure
- In-memory per-user session cache that expires after 3 minutes of inactivity
- Text-only request handling with simple jailbreak detection
- Background Gemini question answering with 5 retries and 2-second backoff, without an interim status message
- Telegram replies are normalized to plain text by removing `**` bold markers from model output
- GitHub Actions deployment to EC2 over SSH
- `systemd` service for automatic restart and idempotent production deployment
- Separate `my_plants/` deterministic backend using CSV, JSON, and text files only
- Personalized watering scheduler that adapts to room type, city profile, soil type, user history, and user-defined frequency
- Friendly reminder scanning that groups due plants into natural-sounding watering messages
- Rule-based profile conversation flow that collects watering frequency, soil type, and plant location

## Project structure

```text
.
├── .github/workflows/deploy.yml
├── app/
│   ├── config.py
│   ├── main.py
│   ├── models.py
│   └── services/
├── my_plants/
│   ├── data/
│   ├── events/
│   ├── memory/
│   ├── raw_logs/
│   ├── adk_agent.py
│   ├── conversation_agent.py
│   ├── file_manager.py
│   ├── main.py
│   ├── orchestrator.py
│   ├── reminder_agent.py
│   └── watering_scheduler.py
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

## My Plants CLI

Run the deterministic file-based plant assistant from the repository root:

```bash
python3 my_plants/main.py
```

What it does:

- stores plant, room, and event data in local CSV files
- seeds plant requirements and city profiles in local JSON files
- stores user memory in JSON
- stores raw message history in text logs
- uses deterministic rule-based extraction only
- performs no external API calls and no LLM inference
- computes personalized watering intervals from plant requirements, room type, city profile, soil type, and recent watering history
- honors user-defined watering frequency as the highest-priority interval override
- asks follow-up profile questions for watering frequency, soil type, and plant location
- scans all plants for due watering reminders and groups them into friendly responses

## Google ADK note

`my_plants/adk_agent.py` provides an ADK-compatible wrapper around the deterministic orchestrator. The official `google-adk` package could not be installed in this local environment because the current interpreter is Python 3.9 while ADK officially targets Python 3.10+, so the tested path here is the deterministic CLI and orchestration core.

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
