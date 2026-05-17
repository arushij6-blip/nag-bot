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

**`couples` table:**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `nagger_chat_id` | INTEGER UNIQUE NOT NULL | The user who ran `/start` |
| `naggee_chat_id` | INTEGER UNIQUE | Set when partner `/join`s; nullable until paired |
| `nagger_name` | TEXT | Telegram first_name captured at `/start` |
| `naggee_name` | TEXT | Captured at `/join` |
| `tone` | TEXT DEFAULT 'default' | Reserved for future per-couple sass tone selection |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**`pairing_codes` table:**

| Column | Type | Notes |
|---|---|---|
| `code` | TEXT PK | 6-char alphanumeric, uppercased |
| `couple_id` | INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE | |
| `expires_at` | TIMESTAMP NOT NULL | 15-minute TTL |

**`tasks` table:**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `description` | TEXT NOT NULL | |
| `deadline` | TIMESTAMP NOT NULL | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |
| `reminders_sent` | INTEGER DEFAULT 0 | Max 3 |
| `completed` | INTEGER DEFAULT 0 | 0/1 boolean |
| `completed_at` | TIMESTAMP | |
| `assigned_to` | INTEGER | Telegram chat_id of nag target |
| `created_by` | INTEGER | Telegram chat_id of task author |
| `couple_id` | INTEGER NOT NULL REFERENCES couples(id) | Tenant scope |

Index: `idx_tasks_couple_completed` on `(couple_id, completed)`.

**Migration:** `_migrate_db()` in `database.py` adds any missing columns on upgraded databases. The historical legacy-couple backfill (which seeded the original Arushi/Ankush pair from env vars) was retired once production had migrated; fresh installs go straight to the multi-tenant schema.

---

## 5. Commands (Telegram)

Anyone can DM the bot. Users self-onboard into couples via `/start` + `/join`. Once paired, both participants can add tasks for each other.

| Command | Behavior |
|---|---|
| `/start` | New chat → creates a couple, returns a 6-char pairing code. Unpaired chat → regenerates the code. Paired chat → personalized help text. |
| `/join <code>` | Consumes the partner's pairing code and links the two chats. Notifies both sides. |
| `/leave` | Deletes the couple, all its tasks, and any pending reminders. Notifies the partner. |
| `/add <task> by <deadline>` | Creates a task assigned to the sender's partner. Schedules 3 reminders. |
| `/done <task>` | Fuzzy substring match against tasks **assigned to** the sender within the caller's couple. Marks complete, cancels jobs, notifies creator. |
| `/tasks` | Shows two sections: "Your tasks" (assigned to sender) and "Tasks you gave <partner>" (created by sender). Scoped to the caller's couple. |
| `/nag` | Manually fires a reminder for every open task **created by** the sender, to its assignee. |

Unknown chats get a "send /start to begin" nudge. Pairing codes expire after 15 minutes (`PAIRING_CODE_TTL` in `database.py`).

**Deadline parser** (`parse_deadline` in `bot.py`) supports ~20 formats: relative (`today`, `tomorrow`, `tonight`, with optional time like `today 9PM`), weekday names (`monday`, `wednesday 8AM`), offsets (`3 days`, `5 hours`), and explicit dates (`13 April`, `13 April 9AM`, `2026-05-13 09:00`, `13/05/2026 09:00`). Default time when only a date is given: 21:00.

---

## 6. Business Logic

- **Multi-tenant:** Each pair of users is a `couple` row. All task queries are scoped by `couple_id`; cross-couple writes (e.g. completing another couple's task by id) are no-ops at the SQL layer.
- **Bidirectional assignment:** Either participant in a couple adds tasks for the other; assignment is implicit (sender → partner).
- **Sass escalation:** 3 reminder levels in `sass_engine.py` — friendly (L1), firm (L2), exasperated (L3). 50 templates each, picked randomly. 50 completion templates.
- **Reminder spacing:** `(deadline - created_at) / 3` per interval. Overdue tasks fire a single L3 reminder ~10 seconds after scheduler picks them up.
- **Creator notification:** On the 3rd (final) reminder and on `/done`, the task creator is messaged.
- **Authorization model:** Self-service via pairing codes. `resolve_caller(update)` looks up the chat in the `couples` table; commands gate on `paired` status. Strangers are nudged to `/start`.
- **Delivery resilience:** All Telegram sends go through `safe_send`, which swallows `telegram.error.Forbidden` (user blocked the bot). When a reminder can't reach the assignee, the creator is notified instead.

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
| `DATA_DIR` | no | Override DB location (defaults to project root) |

Bootstrapping: any user who DMs the bot can `/start` to create a couple and get a pairing code, then send the code to their partner who runs `/join <code>`. No env-based allowlist anymore.

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

**Onboarding a new couple:** Either partner DMs the bot and sends `/start`. The bot replies with a 6-character pairing code (15-minute TTL). The other partner DMs the bot and sends `/join <code>`. Both sides get a confirmation and can begin `/add`-ing tasks. To rotate the code, re-send `/start`.

**Adding more than 2 users per couple (would require code changes):** Currently each `couple` row has exactly two seats (`nagger_chat_id`, `naggee_chat_id`). For groups, the schema would need a `couple_members` table and the `assigned_to`/`created_by` routing in `/add` would need a target selector. Roadmap is sketched in `nag bot.md`.

**Tuning sass:** Edit template lists in `sass_engine.py`. Three lists for reminders (`LEVEL_1`, `LEVEL_2`, `LEVEL_3`) plus completion. `{task}` and `{deadline}` are the only template placeholders.

**Changing reminder count/spacing:** `compute_reminder_times()` in `scheduler.py` is the single source of truth (currently 3 evenly spaced). `mark_reminder_sent` increments and the `reminders_sent < 3` filter in `get_tasks_needing_reminder` would also need adjusting.

---

## 12. Tradeoffs & Technical Decisions

- **In-memory scheduler** chosen over a persistent jobstore: simpler, and `reschedule_all_pending()` gives us the durability we need by deriving jobs from DB state on each boot. Cost: a restart during the ~seconds an overdue reminder is queued could double-fire it (unlikely in practice).
- **SQLite over Postgres:** Tens-to-hundreds of couples on a single host. Beyond that, swap the data layer for Postgres — `database.py` is small enough that this is a half-day move.
- **Self-service pairing over admin allowlist:** Couples onboard themselves via `/start` + `/join`. No env-based allowlist to maintain as users come and go.
- **Long-polling over webhooks:** No public HTTPS endpoint required. Trade: slightly higher latency, single-instance only.
- **Substring task matching in `/done`** instead of forcing the user to remember IDs. Trade: ambiguity if descriptions overlap; we accept "first match wins" by deadline order.
- **Reminders only delivered to assignee, not creator** (except final reminder): keeps the creator's chat quiet.

---

## 13. Known Issues

- If two open tasks share a substring, `/done <substring>` completes the earliest-deadline one without disambiguation.
- Overdue tasks always trigger a single L3 reminder regardless of how overdue, and don't replay missed L1/L2.
- Time zones are inferred from the host system (`datetime.now()` is naive local time). Deploying to a server in a different TZ shifts deadline semantics.
- No retry on Telegram send failures. `safe_send` swallows `Forbidden` but other transient errors propagate.
- A handful of sass templates still use relationship language ("babe", "divorce lawyer"). Most of the expanded pool is neutral, but the legacy lines weren't rewritten.
- No per-couple tone control — every couple gets the same template mix.

---

## 14. Future Improvements

- Per-couple tone control (`/tone` command — schema already has the `tone` column).
- Direction-aware or neutral sass templates (or pick from a pool based on `created_by`).
- Multi-user / group support beyond two-seat couples (see `nag bot.md` roadmap: `users`, `groups`, `group_members` tables).
- Recurring tasks (`/add ... every monday`).
- Snooze / reschedule command.
- Time-zone-aware deadlines per user.
- Persistent APScheduler jobstore (e.g., SQLAlchemyJobStore against the same SQLite file) to avoid the rebuild-on-boot dance.
- Webhook deployment for lower latency.
- Task priorities and inline keyboard buttons for `/done` instead of typed substrings.

---

## 15. Change Log

- **Multi-tenant rework** — Any pair of Telegram users can now self-onboard. New `couples` and `pairing_codes` tables; `tasks` gained `couple_id` with all queries scoped accordingly. Added `/start`/`/join`/`/leave` flow. Removed `ARUSHI_CHAT_ID` / `ANKUSH_CHAT_ID` env-var allowlist; auth now via `resolve_caller` over the `couples` table. Scheduler `_fire_reminder` re-reads the task at fire time and gracefully no-ops on deleted/completed rows. All Telegram sends wrapped in `safe_send` to swallow `Forbidden` and notify the partner. Sass pools expanded from 8/10/12/10 to 50/50/50/50.
- **Bidirectional task assignment** — Both participants can `/add`, `/done`, `/tasks`, and `/nag`. Added `assigned_to`/`created_by` columns and a migration + backfill path. Reminder routing is dynamic (resolved from task state) instead of hardcoded to Ankush. `send_reminder_to_ankush` renamed to `send_reminder`.
