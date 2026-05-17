import asyncio
import os
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import (
    init_db,
    add_task,
    get_open_tasks,
    find_task_by_description,
    complete_task,
    backfill_tasks,
)
from scheduler import (
    scheduler,
    set_reminder_callback,
    schedule_task_reminders,
    cancel_task_reminders,
    reschedule_all_pending,
)
from sass_engine import generate_completion_message

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ARUSHI_CHAT_ID = int(os.getenv("ARUSHI_CHAT_ID") or "0")
ANKUSH_CHAT_ID = int(os.getenv("ANKUSH_CHAT_ID") or "0")

app_instance = None


def is_arushi(update: Update) -> bool:
    return update.effective_chat.id == ARUSHI_CHAT_ID


def is_ankush(update: Update) -> bool:
    return update.effective_chat.id == ANKUSH_CHAT_ID


def is_participant(update: Update) -> bool:
    return update.effective_chat.id in (ARUSHI_CHAT_ID, ANKUSH_CHAT_ID)


def get_partner(chat_id: int) -> int:
    if chat_id == ARUSHI_CHAT_ID:
        return ANKUSH_CHAT_ID
    return ARUSHI_CHAT_ID


def get_name(chat_id: int) -> str:
    if chat_id == ARUSHI_CHAT_ID:
        return "Arushi"
    if chat_id == ANKUSH_CHAT_ID:
        return "Ankush"
    return "Unknown"


def parse_deadline(deadline_text: str) -> datetime | None:
    deadline_text = deadline_text.strip().lower()

    time_suffix = None
    for keyword in ["today", "tomorrow", "tonight"]:
        if deadline_text.startswith(keyword):
            time_part = deadline_text[len(keyword):].strip().strip(",").strip()
            if time_part:
                for fmt in ["%I:%M %p", "%I%p", "%I:%M%p", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_part, fmt)
                        time_suffix = (parsed_time.hour, parsed_time.minute)
                        break
                    except ValueError:
                        continue
            deadline_text = keyword

    if deadline_text == "today":
        h, m = time_suffix or (21, 0)
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    if deadline_text == "tomorrow":
        h, m = time_suffix or (21, 0)
        return (datetime.now() + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    if deadline_text == "tonight":
        h, m = time_suffix or (22, 0)
        return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    matched_day = None
    day_time_suffix = None
    for day in day_names:
        if deadline_text.startswith(day):
            matched_day = day
            time_part = deadline_text[len(day):].strip().strip(",").strip()
            if time_part:
                for fmt in ["%I:%M %p", "%I%p", "%I:%M%p", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_part, fmt)
                        day_time_suffix = (parsed_time.hour, parsed_time.minute)
                        break
                    except ValueError:
                        continue
            break
    if matched_day:
        target_day = day_names.index(matched_day)
        today = datetime.now()
        days_ahead = (target_day - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        h, m = day_time_suffix or (21, 0)
        return (today + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)

    if deadline_text.endswith("days"):
        try:
            num = int(deadline_text.replace("days", "").strip())
            return (datetime.now() + timedelta(days=num)).replace(hour=21, minute=0, second=0, microsecond=0)
        except ValueError:
            pass

    if deadline_text.endswith("hours"):
        try:
            num = int(deadline_text.replace("hours", "").strip())
            return datetime.now() + timedelta(hours=num)
        except ValueError:
            pass

    formats_with_time = [
        "%d %B, %I:%M %p",      # 13 April, 9:00 AM
        "%d %B, %I%p",           # 13 April, 9AM
        "%d %B %I:%M %p",        # 13 April 9:00 AM
        "%d %B %I%p",            # 13 April 9AM
        "%d %b, %I:%M %p",       # 13 Apr, 9:00 AM
        "%d %b, %I%p",           # 13 Apr, 9AM
        "%d %b %I:%M %p",        # 13 Apr 9:00 AM
        "%d %b %I%p",            # 13 Apr 9AM
        "%Y-%m-%d %H:%M",        # 2026-05-13 09:00
        "%d/%m/%Y %H:%M",        # 13/05/2026 09:00
        "%d-%m-%Y %H:%M",        # 13-05-2026 09:00
        "%Y-%m-%d %I:%M %p",     # 2026-05-13 9:00 AM
        "%d/%m/%Y %I:%M %p",     # 13/05/2026 9:00 AM
    ]
    for fmt in formats_with_time:
        try:
            return datetime.strptime(deadline_text, fmt)
        except ValueError:
            continue

    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B", "%d %b"]:
        try:
            parsed = datetime.strptime(deadline_text, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed.replace(hour=21, minute=0, second=0, microsecond=0)
        except ValueError:
            continue

    return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_participant(update):
        name = get_name(chat_id)
        partner = get_name(get_partner(chat_id))
        await update.message.reply_text(
            f"Hey {name}! I'm your Nag Bot 🎯\n\n"
            "Commands:\n"
            f"/add <task> by <deadline> — Add a task for {partner}\n"
            "/done <task> — Mark a task as done\n"
            "/tasks — See all open tasks\n"
            "/nag — Send immediate reminders\n\n"
            "Example: /add Fix the faucet by Friday"
        )
    else:
        await update.message.reply_text(
            f"Hey! Your chat ID is: {chat_id}\n"
            "Add this to your .env file to get started."
        )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_participant(update):
        await update.message.reply_text("You're not a participant in this bot 😤")
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /add Fix the faucet by Friday")
        return

    parts = text.rsplit(" by ", 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "I need a deadline! Use format:\n/add <task> by <deadline>\n\n"
            "Deadlines: today, tomorrow, tonight, Monday-Sunday, 3 days, 5 hours, 13 April, 13 April 9AM, 2026-05-01"
        )
        return

    description = parts[0].strip()
    deadline_text = parts[1].strip()
    deadline = parse_deadline(deadline_text)

    if not deadline:
        await update.message.reply_text(
            f"Couldn't understand deadline: '{deadline_text}'\n\n"
            "Try: today, tomorrow, tonight, Monday, 3 days, 5 hours, 13 April, 13 April 9AM, or YYYY-MM-DD"
        )
        return

    chat_id = update.effective_chat.id
    assigned_to = get_partner(chat_id)
    task = add_task(description, deadline, assigned_to, chat_id)
    schedule_task_reminders(task)

    partner_name = get_name(assigned_to)
    deadline_display = deadline.strftime("%B %d, %I:%M %p")
    await update.message.reply_text(
        f"✅ Task added for {partner_name}!\n\n"
        f"📋 {description}\n"
        f"⏰ Deadline: {deadline_display}\n\n"
        f"I'll send 3 reminders with escalating sass. They won't know what hit them."
    )


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_participant(update):
        await update.message.reply_text("You're not a participant in this bot!")
        return

    chat_id = update.effective_chat.id
    query = " ".join(context.args) if context.args else ""
    if not query:
        tasks = get_open_tasks(assigned_to=chat_id)
        if not tasks:
            await update.message.reply_text("No open tasks! You're free... for now 👀")
            return
        task_list = "\n".join(f"  /done {t['description']}" for t in tasks)
        await update.message.reply_text(f"Which one did you finish?\n\n{task_list}")
        return

    task = find_task_by_description(query, assigned_to=chat_id)
    if not task:
        await update.message.reply_text(
            f"Can't find a task matching '{query}' 🤔\nUse /tasks to see your tasks."
        )
        return

    complete_task(task["id"])
    cancel_task_reminders(task["id"])

    completion_msg = generate_completion_message(task["description"])
    await update.message.reply_text(completion_msg)

    creator = task["created_by"]
    if app_instance and creator:
        await app_instance.bot.send_message(
            chat_id=creator,
            text=f"✅ {get_name(chat_id)} completed: {task['description']}",
        )


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_participant(update):
        await update.message.reply_text("You're not a participant in this bot!")
        return

    chat_id = update.effective_chat.id
    my_tasks = get_open_tasks(assigned_to=chat_id)
    created_tasks = get_open_tasks(created_by=chat_id)

    if not my_tasks and not created_tasks:
        await update.message.reply_text("No open tasks! All clear 🎉")
        return

    def format_tasks(tasks):
        lines = []
        for t in tasks:
            deadline = t["deadline"]
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline)
            deadline_str = deadline.strftime("%b %d")
            sass_level = "🟢" if t["reminders_sent"] == 0 else "🟡" if t["reminders_sent"] == 1 else "🔴"
            lines.append(f"{sass_level} {t['description']} (by {deadline_str}) — {t['reminders_sent']}/3 reminders sent")
        return "\n".join(lines)

    msg_parts = []
    if my_tasks:
        msg_parts.append(f"📋 Your tasks:\n\n{format_tasks(my_tasks)}")
    if created_tasks:
        partner = get_name(get_partner(chat_id))
        msg_parts.append(f"📤 Tasks you gave {partner}:\n\n{format_tasks(created_tasks)}")

    await update.message.reply_text("\n\n".join(msg_parts))


async def cmd_nag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_participant(update):
        await update.message.reply_text("Nice try 😏")
        return

    chat_id = update.effective_chat.id
    tasks = get_open_tasks(created_by=chat_id)
    if not tasks:
        await update.message.reply_text("No open tasks to nag about!")
        return

    from sass_engine import generate_reminder

    for task in tasks:
        deadline = task["deadline"]
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        deadline_str = deadline.strftime("%B %d, %I:%M %p")
        sass_level = min(task["reminders_sent"] + 1, 3)
        message = generate_reminder(task["description"], sass_level, deadline_str)

        if app_instance and task["assigned_to"]:
            await app_instance.bot.send_message(chat_id=task["assigned_to"], text=message)

    await update.message.reply_text(f"💅 Sent {len(tasks)} nag(s). You're welcome.")


async def send_reminder(task_id: int, message: str, reminder_number: int, assigned_to: int = 0, created_by: int = 0):
    if app_instance and assigned_to:
        await app_instance.bot.send_message(chat_id=assigned_to, text=message)
    if app_instance and created_by and reminder_number == 3:
        await app_instance.bot.send_message(
            chat_id=created_by,
            text=f"📢 Final reminder sent for task #{task_id}. All 3 sass levels deployed.",
        )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in (ARUSHI_CHAT_ID, ANKUSH_CHAT_ID):
        await update.message.reply_text(f"Your chat ID is: {chat_id}")
        return
    await update.message.reply_text("I don't understand that. Try /start for commands!")


async def post_init(application: Application):
    global app_instance
    app_instance = application

    await application.bot.set_my_commands([
        BotCommand("start", "Get started"),
        BotCommand("add", "Add a task for your partner"),
        BotCommand("done", "Mark task as done"),
        BotCommand("tasks", "See open tasks"),
        BotCommand("nag", "Send immediate reminders"),
    ])

    set_reminder_callback(send_reminder)
    scheduler.start()
    reschedule_all_pending()
    logger.info("Bot started! Scheduler running.")


def main():
    init_db()
    backfill_tasks(ARUSHI_CHAT_ID, ANKUSH_CHAT_ID)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("add", cmd_add))
    application.add_handler(CommandHandler("done", cmd_done))
    application.add_handler(CommandHandler("tasks", cmd_tasks))
    application.add_handler(CommandHandler("nag", cmd_nag))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    logger.info("Starting Nag Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
