from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from database import get_task, get_tasks_needing_reminder, mark_reminder_sent
from sass_engine import generate_reminder

scheduler = AsyncIOScheduler()

_send_reminder_callback = None


def set_reminder_callback(callback):
    global _send_reminder_callback
    _send_reminder_callback = callback


def compute_reminder_times(created_at: datetime, deadline: datetime) -> list[datetime]:
    total_duration = deadline - created_at
    if total_duration <= timedelta(0):
        return [created_at, created_at, created_at]

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

    if deadline <= now:
        scheduler.add_job(
            _fire_reminder,
            trigger=DateTrigger(run_date=now + timedelta(seconds=10)),
            args=[task["id"]],
            id=f"reminder_{task['id']}_overdue",
            replace_existing=True,
        )
        return

    remaining_until_deadline = deadline - now
    remaining_reminders = 3 - already_sent

    for i in range(already_sent, 3):
        scheduled_time = reminder_times[i]
        if scheduled_time <= now:
            interval = remaining_until_deadline / remaining_reminders
            offset = interval * (i - already_sent + 1)
            scheduled_time = now + offset

        scheduler.add_job(
            _fire_reminder,
            trigger=DateTrigger(run_date=scheduled_time),
            args=[task["id"]],
            id=f"reminder_{task['id']}_{i + 1}",
            replace_existing=True,
        )


async def _fire_reminder(task_id: int):
    if _send_reminder_callback is None:
        return

    task = get_task(task_id)
    if task is None or task["completed"]:
        return

    reminder_number = min(task["reminders_sent"] + 1, 3)
    deadline = task["deadline"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline)
    deadline_str = deadline.strftime("%B %d, %I:%M %p")
    message = generate_reminder(task["description"], reminder_number, deadline_str)
    mark_reminder_sent(task_id, couple_id=task["couple_id"])
    await _send_reminder_callback(
        task_id,
        message,
        reminder_number,
        task.get("assigned_to", 0),
        task.get("created_by", 0),
    )


def cancel_task_reminders(task_id: int):
    for i in range(1, 4):
        job_id = f"reminder_{task_id}_{i}"
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)
    overdue_id = f"reminder_{task_id}_overdue"
    if scheduler.get_job(overdue_id):
        scheduler.remove_job(overdue_id)


def reschedule_all_pending():
    tasks = get_tasks_needing_reminder()
    for task in tasks:
        schedule_task_reminders(task)
