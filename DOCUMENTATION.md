# Deployment and Operations Guide

## Application behavior

### Use case 1.1: `/setup`

1. User sends `/setup`.
2. Bot asks for a Gemini API key.
3. Submitted key is written to `data/user_gemini_keys.csv` with:
   - `user_id`
   - `gemini_api_key`
   - `datetime`
4. The key is validated against Gemini `2.5-flash`.
5. If validation succeeds, setup completes.
6. If validation fails, the invalid row is removed so the latest usable key remains intact, and the bot asks for the key again.

### Use case 2.1: input validation

- Non-text Telegram messages receive: `We only process text inputs for now.`
- Text messages are checked against lightweight jailbreak phrases.
- Unsafe inputs receive: `This is an unsafe input. We will not process this.`

### Use case 2.2: background QA

1. Safe text questions are accepted.
2. Gemini processing starts in the background.
3. The bot checks completion every 5 seconds.
4. Gemini retries up to 5 times with a 2-second delay between attempts.
5. The final answer is sent back to Telegram when ready.

### Use case 3.0: local memory

- On each interaction, the latest stored Gemini API key is loaded into local memory if needed.
- In-memory session data expires after 3 minutes of inactivity.
- The persistent source of truth remains the CSV file.

## EC2 bootstrap

Run the bootstrap script on the Ubuntu EC2 host:

```bash
bash scripts/ec2_setup.sh
```

What it does:

- installs `git`, `curl`, and Python 3.11
- creates `/opt/myplant-bot`
- writes and enables the `systemd` unit
- reloads `systemd`
- optionally opens port `8000` if `ufw` is active

## systemd service

The service file is located at `systemd/myplant-bot.service`.

Important commands on EC2:

```bash
sudo systemctl daemon-reload
sudo systemctl enable myplant-bot.service
sudo systemctl restart myplant-bot.service
sudo systemctl status myplant-bot.service
journalctl -u myplant-bot.service -f
```

## GitHub Actions workflow behavior

The workflow is intentionally idempotent:

- first deploy clones the repo if `.git` does not exist
- later deploys fetch and hard-reset to `origin/main`
- recreating `.venv` is safe across repeated runs
- `pip install -r requirements.txt` converges the host to the declared dependency set
- `systemctl restart` cleanly refreshes the running process each deploy

Required GitHub Secrets:

- `EC2_HOST`
- `EC2_USER`
- `EC2_SSH_PRIVATE_KEY`
- `EC2_KNOWN_HOSTS`
- `EC2_APP_DIR`
- `EC2_ENV_FILE_BASE64`
- `EC2_GITHUB_REPOSITORY_URL`

Helpful secret preparation commands:

```bash
ssh-keyscan -H your-ec2-hostname
base64 < .env | tr -d '\n'
```

## Security best practices

- Rotate the Telegram bot token before production use because it has already been exposed outside a secret store.
- Use `EC2_KNOWN_HOSTS` instead of `ssh-keyscan` in CI so host identity is pinned rather than trust-on-first-use.
- Use a dedicated deploy SSH key with no passphrase and read-only repository access where possible.
- Restrict inbound EC2 security group rules to only required ports and trusted source IPs.
- Keep the production `.env` only in GitHub Secrets and on the server with `chmod 600`.
- Terminate TLS at an ALB or reverse proxy like Nginx and expose the app publicly over HTTPS only.
- Prefer a dedicated non-root deploy user and limit `sudo` to the commands needed for `systemctl`.
- Add CloudWatch or another log sink for process and deployment observability.

## Production checklist

- Set `APP_BASE_URL` to the public HTTPS URL used by Telegram webhook delivery.
- Add the required GitHub Secrets before pushing to `main`.
- Run `/telegram/register-webhook` once after DNS and TLS are ready.
- Verify `GET /health` returns `status=ok`.
- Confirm `journalctl -u myplant-bot.service` shows successful startup after each deploy.
