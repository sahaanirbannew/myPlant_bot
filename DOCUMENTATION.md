# Deployment and Operations Guide

This document now covers two systems in this repository:

- the deployed Telegram webhook bot
- the local deterministic `My Plants` backend under `my_plants/`

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
3. The user does not receive a `Processing your question in the background.` status message.
4. The bot checks completion every 5 seconds.
5. Gemini retries up to 5 times with a 2-second delay between attempts.
6. The final answer is sanitized for plain-text Telegram delivery by removing `**` markers before it is sent back.

### Use case 3.0: local memory

- On each interaction, the latest stored Gemini API key is loaded into local memory if needed.
- In-memory session data expires after 3 minutes of inactivity.
- The persistent source of truth remains the CSV file.

## HTTPS and Telegram webhook setup

- The current deployment target uses `https://3.109.122.172:8443` as `APP_BASE_URL`.
- A self-signed certificate is acceptable for Telegram webhook delivery when the public certificate is uploaded during `setWebhook`.
- The service reads `SSL_CERTFILE` and `SSL_KEYFILE` from `.env` and starts uvicorn with TLS automatically when both are present.

## EC2 bootstrap

Run the bootstrap script on the Ubuntu EC2 host:

```bash
bash scripts/ec2_setup.sh
```

What it does:

- installs `git`, `curl`, and Python 3 using either `dnf` or `apt-get`
- creates `/home/ec2-user/myPlant_bot` by default
- writes and enables the `systemd` unit
- reloads `systemd`
- optionally opens port `8000` if `ufw` or `firewalld` is active

Verified infrastructure detail:

- The current EC2 instance at `3.109.122.172` was confirmed to be Amazon Linux 2023, not Ubuntu.

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

Required GitHub Actions variables:

- `EC2_HOST`
- `EC2_USER`
- `EC2_APP_DIR`
- `EC2_GITHUB_REPOSITORY_URL`
- `EC2_KNOWN_HOSTS`

Required GitHub Secrets:

- `EC2_SSH_PRIVATE_KEY`
- `EC2_ENV_FILE_BASE64`

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

## Testing

- Run `pytest` locally to validate the Telegram response formatting and background-processing behavior.
- Run `pytest` locally to validate the deterministic `My Plants` watering scheduler, reminder flow, and profile conversation flow.
- Run `pytest` locally to validate dashboard trace logging and `/dashboard` rendering.

## Telegram request dashboard

Route:

- `GET /dashboard`

Current behavior:

- No authorization is required right now.
- The page renders recent Telegram request traces from the moment a user message arrives until the bot sends the final reply.
- Each trace includes:
  - incoming Telegram text
  - which agent or processing step ran
  - the input that step received
  - the output that step produced
  - which data was saved
  - which file received that data
  - which agent handled the save
  - info events
  - error events

Storage:

- Trace events are stored in `data/telegram_agent_traces.jsonl`.
- Sensitive Gemini API keys are masked before they are written to trace logs.

Logged agents and stages currently include:

- `telegram_input_agent`
- `session_agent`
- `setup_agent`
- `gemini_validation_agent`
- `safety_agent`
- `queue_agent`
- `gemini_agent`
- `telegram_output_agent`
- `delivery_agent`
- `bot_service`
- `storage_agent`
- `setup_memory_agent`
- `outreach_registry_agent`
- `outreach_agent`

Current saved-file visibility:

- Gemini API key submissions and removals are shown with the target CSV path and masked saved payload.
- Static setup facts inferred from user messages are shown with the exact CSV path and saved row payload.
- Keys are masked before dashboard logging so the page does not expose the raw secret.

Telegram response behavior:

- The My Plants persona block is placed at the start of every Gemini prompt.
- Prompts explicitly ask for concise and objective responses.
- When useful, responses should end with one short question to gather missing static setup information.
- If a user writes in a non-English language, prompts instruct Gemini to reply in that same language.
- Prompts explicitly tell the bot not to guess species, cultivars, varieties, room placement, or light setup from vague descriptions.
- If a message is ambiguous, the extraction layer returns one short clarification question and leaves uncertain stored fields empty.

Static setup persistence and Data Storage Rules:

- **Per-User File Isolation:** All data generated by or relevant to a user is strictly stored within their isolated folder. This protects cross-chat data bleeding.
- **Where data is saved:**
  - `my_plants/data/users/<user_id>/rooms.csv`: Room layouts, lighting, and window setup.
  - `my_plants/data/users/<user_id>/plants.csv`: Plant definitions, soil, and links to rooms.
  - `my_plants/data/users/<user_id>/events.csv`: Transactional events like watering and fertilizing.
  - `my_plants/data/users/<user_id>/memory.json`: User preferences, last active plant, and dynamic overrides.
  - `my_plants/data/users/<user_id>/conversation_state.json`: Active multi-turn context (which plant and what question is currently being asked).
  - `my_plants/data/users/<user_id>/conversation_history.json`: Rolling window of the last 20 conversational messages (user/bot).
  - `my_plants/data/users/<user_id>/plant_<plant_id>_history.jsonl`: Independent time-series ledgers for every plant tracking all profile updates and care events.
- **What data is saved:**
  - **Room profiles:** Name, type, a list of windows (up to 3), size, and grow light flags. City data acts as a home-level property mostly placed onto the room.
  - **Plant profiles:** Name, species, soil type, and fertilizer type. They are linked to `room_id`s to establish a clean Home -> Room -> Plant hierarchy.
  - **Conversation states:** Active `plant_id` and the `pending_question` metadata to enable continuous conversational context over multiple replies.
- **How data is extracted / judged:**
  - **Conversational Memory Extraction:** If a conversation state is active, the bot uses `extract_with_llm` to dynamically format a JSON-extraction prompt (e.g., asking Gemini to cleanly extract "days" from natural text like "once every week or so").
  - **Implicit LLM Extraction (`BotService`):** For general queries, the Telegram bot pipes the user message directly to Gemini to extract structured `plants` and `rooms` JSON data. The prompt rigorously prevents Gemini from assuming plant placement or variety details unless explicitly described.
- **How data is retrieved and used (conditions for retrieval):** 
  - **Conversational History Injection:** To ensure semantic continuity (i.e. remembering "what the user just said"), `Orchestrator` buffers the latest message into the `conversation_history.json` and then retrieves the entire rolling window to inject dynamically at the top of the LLM prompt immediately before the new message and properties array. This ensures high-accuracy follow-ups when users just reply using pronouns or fragments like "mostly sand".
  - **Prompt Injection:** When the bot fields a question (e.g. "describe my room"), `PlantSetupStore.build_user_setup_summary(user_id)` retrieves all room and plant CSVs and formats them into a rich, readable summary block. This block is injected at the top of the LLM prompt.
  - **Dynamic Rule Resolution:** For CLI usage and backend analysis, `ContextBuilder.build` parses the files to pass full dictionary payloads into decision engines. The bot dynamically recalculates parameters based on the *retrieved room setup, window layouts, and city climate*, which strictly overrides standard textbook guidance forming the basis of all care recommendations.
- **Logic behind Conversation Topics:**
  - The system drives conversation using *Pending Profiles*. If a user's plant is missing details (e.g., soil type or location), the bot marks that as a `pending_question`. 
  - The backend pauses normal processing to emit a friendly, targeted follow-up question. 
  - If the user switches topics by sending unrelated keywords (e.g., "bought another plant"), the bot automatically clears the active conversation state to respect the user's organic conversation flow instead of trapping them in a questionnaire loop.

## Account Deletion
- Sending `/clear_data` to the bot fully purges the user's isolated `my_plants/data/users/<uuid>` filesystem folder.
- Additionally, it synchronously removes the user's API Key from `user_gemini_keys.csv` and flushes any active cached session states, providing a total clean-slate wipe.

Evening outreach:

- Known Telegram chats are stored in `data/telegram_user_registry.json`.
- Daily outreach state is stored in `data/evening_outreach_state.json`.
- If setup information is missing, the bot can proactively send one short setup question during the 8:30 PM to 9:00 PM India time window.
- The send minute is deterministic but pseudo-random per user per day, so outreach times vary without requiring a database or cron state.

## My Plants file-backed backend

Location:

- `my_plants/`

Storage model:

- `my_plants/data/users/<user_id>/plants.csv`
- `my_plants/data/users/<user_id>/rooms.csv`
- `my_plants/data/users/<user_id>/events.csv`
- `my_plants/data/users/<user_id>/memory.json`
- `my_plants/data/users/<user_id>/raw.log`
- `my_plants/data/users/<user_id>/plant_<plant_id>_history.jsonl`
- `my_plants/data/city_profiles.json` (global config)
- `my_plants/data/plant_requirements.json` (global config)

Core deterministic components:

- `FileManager`: creates directories and manages CSV, JSON, and text files
- `PlantResolver`: matches plant names, creates new plants for `bought` or `got a`, or falls back to last used plant
- `MemoryExtractor`: uses strict keyword matching for watering, fertilizing, issues, and room facts
- `ConversationAgent`: collects watering frequency, soil type, and plant location in a deterministic multi-turn flow
- `ContextBuilder`: loads plants, rooms, recent events, full plant event history, memory, plant requirements, and city profiles
- `TimeSeriesAnalyzer`: computes watering intervals, last watering timestamp, days since watering, and frequent-watering patterns
- `WateringScheduler`: calculates the effective watering interval using base requirements, room type, city profile, soil type, user history, and user-defined overrides
- `DecisionEngine`: applies indoor, north-window, and overwatering rules
- `ReminderAgent`: scans all plants for a user and groups due plants into warm, nudge-style reminder messages
- `GeminiInferenceClient`: calls Gemini to turn structured plant context into natural replies and reminders when configured
- `ResponseGenerator`: uses Gemini for plant-care phrasing and contextual inference, with a local fallback if Gemini is unavailable
- `Orchestrator`: coordinates the full end-to-end deterministic workflow

Watering scheduler rules:

- Base watering interval comes from `plant_requirements.json`
- Room type adjusts the interval for `indoor`, `balcony`, and `outdoor` placements
- City profile adjusts the interval using deterministic humidity and temperature bands
- Soil type adjusts the interval using deterministic soil retention rules
- If at least one recent watering history exists, the system computes average watering interval from the last five watering events and blends it with the adjusted base interval
- If a user-defined watering frequency exists, it overrides all other interval logic
- `days_since_last_watered` is computed from `events.csv`
- A reminder becomes due when `days_since_last_watered >= watering_interval`

Reminder and conversation behavior:

- Users can ask reminder-style questions such as which plants are due for watering
- Due plants are grouped into a single natural reminder response
- New plants trigger a follow-up profile flow that asks for watering frequency, soil type, and plant location
- The collected watering frequency is stored in user memory as a plant-specific override
- Final replies can use Gemini for contextual inference and the "My Plants" companion voice

My Plants Gemini environment:

- `MY_PLANTS_GEMINI_API_KEY`: Gemini API key for the My Plants response and reminder layers
- `MY_PLANTS_GEMINI_MODEL`: optional model override, defaults to `gemini-2.5-flash`
- `MY_PLANTS_GEMINI_API_BASE_URL`: optional API base URL override

Prompt behavior:

- The My Plants persona block is placed at the start of every Gemini prompt used by the Telegram bot question flow.
- The same persona block is also placed at the start of Gemini prompts used by the My Plants response and reminder layers.
- The persona instructions now explicitly require concise and objective responses.

CLI:

```bash
python3 my_plants/main.py
```

ADK wrapper:

- `my_plants/adk_agent.py`

Important ADK constraint:

- The wrapper is written to be ADK-compatible, but the official `google-adk` package was not installable in this local Python 3.9 environment.
- The blocking issue was the current interpreter/runtime dependency stack, not the deterministic backend itself.
- The deterministic core and CLI were fully tested locally with `pytest`.
