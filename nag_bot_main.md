# nag_bot_main.md

Permanent knowledge file for the **Nag Bot** project. Update whenever architecture, schema, or major logic changes.

---

## 1. Project Overview

A sassy Telegram bot that lets two participants (currently Arushi and Ankush) assign household/personal tasks to each other with escalating reminder messages. Either user can add tasks; the bot nags the assignee with three reminders of increasing sass before the deadline. The creator is notified on the final reminder and on completion.

---

## 2. Architecture

**Type:** Single-process async Python service. No HTTP layer, no API. Telegram is both the UI and the messaging transport.

**Runtime components:**
- `python-telegram-bot` (long-polling) handles inbound commands
- `APScheduler` (AsyncIOScheduler, in-memory job store) fires reminders at computed times
- `SQLite` (WAL mode) for persistence
- Single event loop owned by `Application.run_polling`

**Reminder lifecycle:**
1. User runs `/add <task> by <deadline>` → row inserted in `tasks`
2. `schedule_task_reminders()` computes 3 evenly-spaced reminder times between `created_at` and `deadline`, registers 3 APScheduler `DateTrigger` jobs
3. Each job calls `_fire_reminder()` → generates a sassy message → calls the `send_reminder` callback → bot posts to assignee's chat
4. On the 3rd reminder, the creator is also notified
5. `/done` cancels remaining jobs and notifies the creator
6. On restart, `reschedule_all_pending()` re-creates jobs for all incomplete tasks (scheduler is in-memory only)

---

## 3. File Layout

| File | Purpose |
|---|---|
| `bot.py` | Telegram handlers, deadline parsing, command authorization, reminder callback |
| `database.py` | SQLite CRUD + schema migration |
| `scheduler.py` | APScheduler setup + reminder time computation |
| `sass_engine.py` | Sassy message template pools |
| `requirements.txt` | `python-telegram-bot==21.6`, `apscheduler==3.10.4`, `python-dotenv==1.0.1` |
| `Dockerfile`, `Procfile`, `nixpacks.toml` | Container/cloud deploy |
| `com.arushi.nagbot.plist` | macOS launchd autostart |
| `nag_bot.db` | SQLite data file (created at runtime) |
| `nag bot.md` | Original product spec / roadmap doc |

There is no frontend. All user interaction is via the Telegram client.

---

## 4. Database

**Engine:** SQLite, WAL journal mode. Path: `${DATA_DIR:-.}/nag_bot.db`.

**Schema (single `tasks` table):**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `description` | TEXT NOT NULL | |
| `deadline` | TIMESTAMP NOT NULL | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |
| `reminders_sent` | INTEGER DEFAULT 0 | Max 3 |
| `completed` | INTEGER DEFAULT 0 | 0/1 boolean |
| `completed_at` | TIMESTAMP | |
| `assigned_to` | INTEGER DEFAULT 0 | Telegram chat_id of nag target |
| `created_by` | INTEGER DEFAULT 0 | Telegram chat_id of task author |

**Migration:** `_migrate_db()` in `database.py` adds `assigned_to`/`created_by` columns if missing. `backfill_tasks(arushi_id, ankush_id)` populates legacy rows where both fields are 0 (assumes the old Arushi→Ankush direction). Both run at startup via `init_db()` and `main()`.

---

## 5. Commands (Telegram)

All commands accept input from either participant. Unknown chat IDs are rejected with a friendly message that echoes their chat_id.

| Command | Behavior |
|---|---|
| `/start` | Unified help text personalized with sender's name and partner's name |
| `/add <task> by <deadline>` | Creates a task assigned to the sender's partner. Schedules 3 reminders. |
| `/done <task>` | Fuzzy substring match against tasks **assigned to** the sender. Marks complete, cancels jobs, notifies creator. |
| `/tasks` | Shows two sections: "Your tasks" (assigned to sender) and "Tasks you gave <partner>" (created by sender). |
| `/nag` | Manually fires a reminder for every open task **created by** the sender, to its assignee. |

**Deadline parser** (`parse_deadline` in `bot.py`) supports ~20 formats: relative (`today`, `tomorrow`, `tonight`, with optional time like `today 9PM`), weekday names (`monday`, `wednesday 8AM`), offsets (`3 days`, `5 hours`), and explicit dates (`13 April`, `13 April 9AM`, `2026-05-13 09:00`, `13/05/2026 09:00`). Default time when only a date is given: 21:00.

---

## 6. Business Logic

- **Bidirectional assignment:** Either user adds tasks for the other; assignment is implicit (sender → partner).
- **Sass escalation:** 3 reminder levels in `sass_engine.py` — friendly (L1), firm (L2), exasperated (L3). 8/10/12 templates respectively, picked randomly. 10 completion templates.
- **Reminder spacing:** `(deadline - created_at) / 3` per interval. Overdue tasks fire a single L3 reminder ~10 seconds after scheduler picks them up.
- **Creator notification:** On the 3rd (final) reminder and on `/done`, the task creator is messaged.
- **Authorization model:** Two-user allowlist via env vars. Anyone else gets their chat_id echoed back so they can be added to `.env`.

---

## 7. State Management

- **Persistent:** Task rows in SQLite. Survives restarts.
- **Volatile:** APScheduler jobs are in-memory (no `jobstore` configured). On boot, `reschedule_all_pending()` rebuilds jobs from the DB. The `reminders_sent` counter is the source of truth for which reminders still need to fire.
- **Global singleton:** `app_instance` in `bot.py` holds the `Application` reference so the scheduler callback can send messages outside the request lifecycle.

---

## 8. Environment & Configuration

Loaded via `python-dotenv` from `.env`:

| Var | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | From BotFather |
| `ARUSHI_CHAT_ID` | yes | Numeric Telegram chat_id |
| `ANKUSH_CHAT_ID` | yes | Numeric Telegram chat_id |
| `DATA_DIR` | no | Override DB location (defaults to project root) |

Bootstrapping: `/start` from an unknown chat echoes that user's chat_id so it can be added to `.env`.

---

## 9. Deployment

Three supported paths:

1. **Docker / Railway / Heroku:** `Dockerfile` (Python 3.12-slim) + `Procfile` (`worker: python bot.py`). `nixpacks.toml` is the Nixpacks fallback.
2. **macOS launchd:** `com.arushi.nagbot.plist` keeps the process alive on a personal machine, logs to `bot.log`.
3. **Bare Python:** `pip install -r requirements.txt && python bot.py`.

Only one instance should run at a time — Telegram long-polling does not multiplex.

---

## 10. Third-Party Integrations

- **Telegram Bot API** — sole external dependency. All user I/O.
- No analytics, no logging service, no DB hosting. Everything is local-process.

---

## 11. Important Workflows

**Adding a new participant (would require code changes):** Currently hardcoded to 2 users. Would need: a `users` table, removal of `ARUSHI_CHAT_ID`/`ANKUSH_CHAT_ID` env vars in favor of registration, group concept, and `@user` mention parsing in `/add`. Roadmap is sketched in `nag bot.md`.

**Tuning sass:** Edit template lists in `sass_engine.py`. Three lists for reminders (`LEVEL_1`, `LEVEL_2`, `LEVEL_3`) plus completion. `{task}` and `{deadline}` are the only template placeholders.

**Changing reminder count/spacing:** `compute_reminder_times()` in `scheduler.py` is the single source of truth (currently 3 evenly spaced). `mark_reminder_sent` increments and the `reminders_sent < 3` filter in `get_tasks_needing_reminder` would also need adjusting.

---

## 12. Tradeoffs & Technical Decisions

- **In-memory scheduler** chosen over a persistent jobstore: simpler, and `reschedule_all_pending()` gives us the durability we need by deriving jobs from DB state on each boot. Cost: a restart during the ~seconds an overdue reminder is queued could double-fire it (unlikely in practice).
- **SQLite over Postgres:** Two-user scale, single host. No reason for a network DB.
- **Hardcoded participants:** Faster to ship than a registration system. Acceptable while user count = 2.
- **Long-polling over webhooks:** No public HTTPS endpoint required. Trade: slightly higher latency, single-instance only.
- **Substring task matching in `/done`** instead of forcing the user to remember IDs. Trade: ambiguity if descriptions overlap; we accept "first match wins" by deadline order.
- **Reminders only delivered to assignee, not creator** (except final reminder): keeps the creator's chat quiet.

---

## 13. Known Issues

- If two open tasks share a substring, `/done <substring>` completes the earliest-deadline one without disambiguation.
- Overdue tasks always trigger a single L3 reminder regardless of how overdue, and don't replay missed L1/L2.
- Time zones are inferred from the host system (`datetime.now()` is naive local time). Deploying to a server in a different TZ shifts deadline semantics.
- No retry on Telegram send failures.
- Sass templates contain gendered/relationship language ("babe", "husband") written from Arushi→Ankush; they read awkwardly in the reverse direction.

---

## 14. Future Improvements

- Direction-aware or neutral sass templates (or pick from a pool based on `created_by`).
- Multi-user / group support (see `nag bot.md` roadmap: `users`, `groups`, `group_members` tables).
- Recurring tasks (`/add ... every monday`).
- Snooze / reschedule command.
- Time-zone-aware deadlines per user.
- Persistent APScheduler jobstore (e.g., SQLAlchemyJobStore against the same SQLite file) to avoid the rebuild-on-boot dance.
- Webhook deployment for lower latency.
- Task priorities and inline keyboard buttons for `/done` instead of typed substrings.

---

## 15. Change Log

- **Bidirectional task assignment** — Both participants can now `/add`, `/done`, `/tasks`, and `/nag`. Added `assigned_to`/`created_by` columns and a migration + backfill path. Reminder routing is now dynamic (passed through the scheduler args) instead of hardcoded to Ankush. `send_reminder_to_ankush` renamed to `send_reminder`.
