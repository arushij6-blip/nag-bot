# Nag Bot

A sassy Telegram bot: two paired partners assign each other household/personal
tasks, and the bot nags the assignee with three escalating reminders before the
deadline. It can also fire one-shot meal reminders pushed from an external menu tool.

It doubles as the **Telegram edge for [Pensieve](https://github.com/arushij6-blip/HomeOS)**,
the household OS — free-text messages are forwarded to Pensieve for organizing, and
Pensieve can push reminders back to the user. Both directions are optional and
token-gated; with the `PENSIEVE_*` vars unset, Nag Bot runs standalone.

Full architecture, schema, and command reference live in
[`nag_bot_main.md`](nag_bot_main.md).

## Quick start

```bash
pip install -r requirements.txt
cp .env .env            # set TELEGRAM_BOT_TOKEN (from BotFather) at minimum
python bot.py
```

## Commands

`/start` · `/join <code>` · `/add <task> by <deadline>` · `/done <task>` ·
`/tasks` · `/nag` · `/leave`. Free text (no command) from a paired user is
forwarded to Pensieve when configured (see below); otherwise it gets a help nudge.

## Wiring Pensieve ⇄ Nag Bot

The two services talk over HTTP in both directions, each authenticated with a
bearer token. **Two token pairs must match**, and each service's `*_URL` points at
the other:

```
capture:   Nag Bot ──POST /inbox────▶ Pensieve
           Bearer PENSIEVE_INBOX_TOKEN   ==   INBOX_API_TOKEN

delivery:  Pensieve ──POST /deliver──▶ Nag Bot
           Bearer NAGBOT_TOKEN           ==   MENU_API_TOKEN
```

**Nag Bot `.env`**

```ini
TELEGRAM_BOT_TOKEN=...                    # from BotFather

# HTTP layer — gates both /menu and /deliver
MENU_API_TOKEN=shared-delivery-secret     # == Pensieve NAGBOT_TOKEN
MENU_API_HOST=0.0.0.0
MENU_API_PORT=8080

# Forward captured free text to Pensieve
PENSIEVE_INBOX_URL=http://localhost:8090  # Pensieve's inbox server
PENSIEVE_INBOX_TOKEN=shared-inbox-secret  # == Pensieve INBOX_API_TOKEN
# PENSIEVE_INBOX_TIMEOUT=8
PENSIEVE_DELIVERY_CHAT_ID=123456789       # your Telegram chat id (until Pensieve sends chat_id)
```

**Pensieve `.env`** (the `HomeOS` repo)

```ini
INBOX_API_TOKEN=shared-inbox-secret       # == Nag Bot PENSIEVE_INBOX_TOKEN
INBOX_API_HOST=0.0.0.0
INBOX_API_PORT=8090

NAGBOT_URL=http://localhost:8080          # Nag Bot's HTTP server
NAGBOT_TOKEN=shared-delivery-secret       # == Nag Bot MENU_API_TOKEN
```

The two secrets above are placeholders — use your own, but keep **each pair
identical** across the two files. Get one pair wrong and the loop connects in only
one direction (capture works but delivery 401s, or vice-versa).

## Tests

```bash
python tests/test_pensieve_integration.py
```

Plain-python smoke + regression tests for the Pensieve integration (no pytest
dependency).
