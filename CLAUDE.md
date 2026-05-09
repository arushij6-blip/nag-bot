# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Nag Bot** is a Telegram bot that manages household tasks with escalating, sassy reminders. It's designed for two users: one person creates tasks with deadlines, the other receives reminders and marks them complete.

### Core Features
- **Flexible deadline parsing**: Accepts "today", "tomorrow", day names (Monday-Sunday), relative times (3 days, 5 hours), and explicit dates (13 April 9AM, 2026-05-13 09:00)
- **3-tier reminder system**: Each task triggers 3 reminders at evenly-spaced intervals, with escalating attitude levels (friendly → firm → exasperated)
- **Role-based access**: Arushi (task creator) can add tasks and trigger nags; Ankush (task doer) can mark tasks complete
- **Persistent storage**: SQLite database with WAL mode for reliability

## Architecture

### Module Layout

**bot.py** — Main entry point and command handler
- Telegram bot initialization and command routing
- `parse_deadline()`: Converts user input (e.g., "tomorrow 3pm", "Friday") into datetime objects. This is the most complex function and supports multiple formats
- Command handlers: `/start`, `/add`, `/done`, `/tasks`, `/nag`
- Cross-user messaging: When Ankush completes a task, Arushi is notified automatically

**database.py** — SQLite persistence layer
- Single table: `tasks` (id, description, deadline, created_at, reminders_sent, completed, completed_at)
- WAL mode enabled for concurrent access safety
- Key functions: `add_task()`, `get_open_tasks()`, `get_tasks_needing_reminder()`, `mark_reminder_sent()`, `complete_task()`, `find_task_by_description()`
- Database path controlled by `DATA_DIR` env var; defaults to project root

**scheduler.py** — APScheduler integration for reminders
- `compute_reminder_times()`: Splits task duration into 3 equal intervals for reminder scheduling
- `schedule_task_reminders()`: Schedules up to 3 reminder jobs; handles late starts (if a job should have fired already, it fires ASAP instead)
- `_fire_reminder()`: Callback that generates the reminder message and sends it via Telegram
- `reschedule_all_pending()`: Called on bot startup to re-attach all incomplete tasks to the scheduler (handles restarts)

**sass_engine.py** — Message generation
- Three template lists (LEVEL_1, LEVEL_2, LEVEL_3) with sassy, humorous reminder messages
- `generate_reminder()`: Returns a random template at the given level, interpolating task description and deadline
- `generate_completion_message()`: Celebratory message when a task is marked done

### Data Flow

1. **Add Task** (Arushi): `/add <description> by <deadline>` → Parse deadline → Insert to DB → Schedule 3 reminders
2. **Reminder Trigger**: APScheduler fires at scheduled time → Generate message → Send to Ankush → Mark reminder as sent in DB
3. **Complete Task** (Ankush): `/done <partial description>` → Fuzzy-match task → Mark completed in DB → Cancel remaining reminders → Notify Arushi
4. **Bot Restart**: `reschedule_all_pending()` re-attaches all incomplete tasks that haven't sent 3 reminders

## Running the Bot

### Setup
```bash
# Create .env file with:
TELEGRAM_BOT_TOKEN=<your bot token from BotFather>
ARUSHI_CHAT_ID=<Arushi's Telegram chat ID>
ANKUSH_CHAT_ID=<Ankush's Telegram chat ID>
```

### Run Locally
```bash
pip install -r requirements.txt
python bot.py
```

The bot uses `application.run_polling()` to continuously listen for messages. Exit with Ctrl+C.

### Run in Docker
```bash
docker build -t nag-bot .
docker run --env-file .env nag-bot
```

The Dockerfile runs Python 3.12 and starts the bot with `python bot.py`.

### Deploy
The bot is designed for Heroku/Railway:
- `Procfile`: Specifies `worker: python bot.py`
- `runtime.txt`: Python 3.12.0
- Heroku/Railway will automatically run the worker dyno

## Testing & Development

### Testing Deadline Parsing
The `parse_deadline()` function in bot.py is the most complex and most likely to need fixes. Test cases:
```python
parse_deadline("today")                   # → today 9 PM
parse_deadline("tomorrow 3pm")            # → tomorrow 3 PM
parse_deadline("friday")                  # → next Friday 9 PM
parse_deadline("wednesday 8am")           # → next Wednesday 8 AM
parse_deadline("tonight")                 # → today 10 PM
parse_deadline("5 days")                  # → 5 days from now, 9 PM
parse_deadline("13 April 9AM")            # → April 13 of current year, 9 AM
parse_deadline("2026-05-13 09:00")        # → ISO format
```

To test locally without a real Telegram bot:
1. Create a test user in BotFather
2. Add `ARUSHI_CHAT_ID` and `ANKUSH_CHAT_ID` to .env (you can use the same ID for both to test both roles)
3. Start the bot and send commands

### Database Inspection
```bash
sqlite3 nag_bot.db ".schema"
sqlite3 nag_bot.db "SELECT * FROM tasks;"
```

Use `DATA_DIR` env var to point to a test database:
```bash
DATA_DIR=./test_data python bot.py
```

## Key Design Decisions

1. **Async-first with APScheduler**: The bot is fully async (python-telegram-bot uses asyncio). Reminders are scheduled via APScheduler's AsyncIOScheduler, which integrates cleanly with the telegram bot's event loop.

2. **3 equal-interval reminders**: Rather than fixed times, reminders are computed as 1/3, 2/3, and 3/3 of the time between task creation and deadline. This scales naturally to short-term (1 hour) and long-term (6 month) tasks.

3. **Late-start handling**: If the bot restarts or a reminder fires after its scheduled time, `schedule_task_reminders()` re-computes which reminders have already fired and schedules only the remaining ones. This prevents duplicate reminders.

4. **Fuzzy task matching**: `/done <text>` uses substring matching (case-insensitive) to find the task, not exact matching. This is user-friendly but could match the wrong task if descriptions are too similar; a dialog to disambiguate could be added if needed.

5. **Sqlite with WAL**: WAL (Write-Ahead Logging) mode prevents "database is locked" errors under concurrent read/write load. Single-user bots rarely need this, but it's good practice.

6. **User separation**: Arushi and Ankush are hardcoded via chat IDs. Adding a third user or swapping roles requires env var changes. Future: could store users in the database.

## Common Tweaks

- **Change reminder sass levels**: Edit `LEVEL_1_TEMPLATES`, `LEVEL_2_TEMPLATES`, `LEVEL_3_TEMPLATES` in sass_engine.py
- **Change default deadline time**: The default is 9 PM (21:00) for most date formats. Change the `(21, 0)` tuples in `parse_deadline()`
- **Change reminder count**: Modify the `3` hardcoded in `compute_reminder_times()` and the loop range in `schedule_task_reminders()`, and add/remove templates in sass_engine.py
- **Change reminder interval formula**: Replace the `total_duration / 3` logic in `compute_reminder_times()`
- **Add a new deadline format**: Add a new branch or format string in `parse_deadline()`
