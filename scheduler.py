from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from database import get_tasks_needing_reminder, mark_reminder_sent
from sass_engine import generate_reminder

scheduler = AsyncIOScheduler()

_send_reminder_callback = None


def set_reminder_callback(callback):
    global _send_reminder_callback
    _send_reminder_callback = callback


def compute_reminder_times(created_at: datetime, deadline: datetime) -> list[datetime]:
    total_duration = deadline - created_at
    if total_duration <= timedelta(0):
        now = datetime.now()
        return [now, now + timedelta(hours=2), now + timedelta(hours=4)]

    interval = total_duration / 3
    return [
        created_at + interval * (i + 1) for i in range(3)
    ]


def schedule_task_reminders(task: dict):
    created_at = task["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    deadline = task["deadline"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline)

    reminder_times = compute_reminder_times(created_at, deadline)
    already_sent = task["reminders_sent"]

    now = datetime.now()
    remaining_until_deadline = deadline - now
    remaining_reminders = 3 - already_sent

    for i in range(already_sent, 3):
        scheduled_time = reminder_times[i]
        if scheduled_time <= now:
            if remaining_until_deadline <= timedelta(0):
                offset = timedelta(hours=2) * (i - already_sent + 1)
            else:
                interval = remaining_until_deadline / remaining_reminders
                offset = interval * (i - already_sent + 1)
            scheduled_time = now + offset

        scheduler.add_job(
            _fire_reminder,
            trigger=DateTrigger(run_date=scheduled_time),
            args=[task["id"], task["description"], i + 1, deadline],
            id=f"reminder_{task['id']}_{i + 1}",
            replace_existing=True,
        )


async def _fire_reminder(task_id: int, description: str, reminder_number: int, deadline: datetime):
    if _send_reminder_callback is None:
        return

    deadline_str = deadline.strftime("%B %d, %I:%M %p") if isinstance(deadline, datetime) else str(deadline)
    message = generate_reminder(description, reminder_number, deadline_str)
    mark_reminder_sent(task_id)
    await _send_reminder_callback(task_id, message, reminder_number)


def cancel_task_reminders(task_id: int):
    for i in range(1, 4):
        job_id = f"reminder_{task_id}_{i}"
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)


def reschedule_all_pending():
    tasks = get_tasks_needing_reminder()
    for task in tasks:
        schedule_task_reminders(task)
