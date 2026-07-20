"""Small HTTP ingestion endpoint so an external weekly-menu tool can push
meal reminders into Nag Bot.

The bot is otherwise a long-polling process with no web layer; this adds a tiny
aiohttp server that runs on the same event loop. It is gated behind a required
bearer token (`MENU_API_TOKEN`) — without one, the server refuses to start so we
never expose an unauthenticated way to inject reminders.

Payload (POST /menu):

    {
        "chat_id": 123456789,          # either partner's Telegram chat id
        "replace": true,               # optional: clear future unsent meals first
        "meals": [
            {"at": "2026-07-20 07:00", "text": "Breakfast: Poha"},
            {"at": "2026-07-20 13:00", "text": "Lunch: Bhindi + Rajma"},
            {"at": "2026-07-20 17:00", "text": "Snack: Upma"},
            {"at": "2026-07-20 20:00", "text": "Dinner: Pasta"}
        ]
    }

`at` accepts ISO datetimes ("2026-07-20 07:00", "2026-07-20T07:00"). If a
`deadline_parser` is supplied (the bot passes its own `parse_deadline`), fuzzy
forms like "monday 7am" also work. Times are naive local time, consistent with
the rest of the bot.
"""
import logging
import os
from datetime import datetime

from aiohttp import web

from database import (
    get_couple_for_chat,
    add_meal_reminder,
    clear_future_meal_reminders,
)
from scheduler import schedule_meal_reminder, cancel_meal_reminder

logger = logging.getLogger(__name__)

_ISO_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]


def _default_parse_at(value: str) -> datetime | None:
    value = value.strip()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def create_menu_app(deadline_parser=None, token: str = None) -> web.Application:
    def parse_at(value: str) -> datetime | None:
        dt = _default_parse_at(value)
        if dt is None and deadline_parser is not None:
            dt = deadline_parser(value)
        return dt

    @web.middleware
    async def auth_middleware(request, handler):
        if request.path == "/health":
            return await handler(request)
        provided = request.headers.get("Authorization", "")
        if provided.startswith("Bearer "):
            provided = provided[len("Bearer "):]
        else:
            provided = request.headers.get("X-API-Token", "")
        if not token or provided != token:
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def health(request):
        return web.json_response({"status": "ok"})

    async def post_menu(request):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON body"}, status=400)

        chat_id = payload.get("chat_id")
        if chat_id is None:
            return web.json_response({"error": "chat_id is required"}, status=400)
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            return web.json_response({"error": "chat_id must be an integer"}, status=400)

        couple = get_couple_for_chat(chat_id)
        if not couple:
            return web.json_response({"error": "no couple found for chat_id"}, status=404)
        if not couple["paired"]:
            return web.json_response({"error": "couple is not paired yet"}, status=409)

        meals = payload.get("meals")
        if not isinstance(meals, list) or not meals:
            return web.json_response({"error": "meals must be a non-empty list"}, status=400)

        parsed = []
        errors = []
        for i, item in enumerate(meals):
            if not isinstance(item, dict):
                errors.append({"index": i, "error": "must be an object"})
                continue
            text = str(item.get("text") or "").strip()
            at_raw = item.get("at")
            if not text:
                errors.append({"index": i, "error": "text is required"})
                continue
            if not at_raw:
                errors.append({"index": i, "error": "at is required"})
                continue
            when = parse_at(str(at_raw))
            if when is None:
                errors.append({"index": i, "error": f"could not parse 'at': {at_raw!r}"})
                continue
            parsed.append((when, text))

        if errors:
            return web.json_response(
                {"error": "some meals could not be parsed", "details": errors},
                status=400,
            )

        couple_id = couple["couple_id"]

        # replace: wipe future unsent reminders so re-ingesting a week doesn't duplicate
        if payload.get("replace"):
            for mid in clear_future_meal_reminders(couple_id, after=datetime.now()):
                cancel_meal_reminder(mid)

        now = datetime.now()
        scheduled = 0
        skipped_past = 0
        for when, text in parsed:
            meal = add_meal_reminder(couple_id, text, when)
            if when <= now:
                skipped_past += 1
            else:
                scheduled += 1
            schedule_meal_reminder(meal)

        logger.info(
            "Menu ingest: couple=%s scheduled=%s skipped_past=%s",
            couple_id, scheduled, skipped_past,
        )
        return web.json_response({
            "ok": True,
            "couple_id": couple_id,
            "scheduled": scheduled,
            "skipped_past": skipped_past,
        })

    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/health", health)
    app.router.add_post("/menu", post_menu)
    return app


async def start_menu_api(deadline_parser=None):
    """Start the menu HTTP server on the running loop. Returns the AppRunner
    (or None if disabled). Requires MENU_API_TOKEN to be set."""
    token = os.getenv("MENU_API_TOKEN")
    if not token:
        logger.warning(
            "MENU_API_TOKEN not set — menu HTTP API disabled "
            "(refusing to expose an unauthenticated ingestion endpoint)."
        )
        return None

    host = os.getenv("MENU_API_HOST", "0.0.0.0")
    port = int(os.getenv("MENU_API_PORT", "8080"))
    app = create_menu_app(deadline_parser, token=token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Menu API listening on %s:%s", host, port)
    return runner


async def stop_menu_api(runner):
    if runner is not None:
        await runner.cleanup()
