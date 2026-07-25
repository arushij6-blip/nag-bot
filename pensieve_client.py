"""Outbound client: forward captured Telegram messages to Pensieve's inbox.

Nag Bot is the data-entry point for the household OS (Pensieve). Free-text messages
from paired users are POSTed to Pensieve's `/inbox`, where they're split, routed,
and acted on.

If `PENSIEVE_INBOX_URL` is unset, forwarding is disabled and the bot behaves exactly
as before (free text gets the default "I don't understand" reply). Env is read at
call time so it works regardless of import order relative to `load_dotenv()`.
"""
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(os.getenv("PENSIEVE_INBOX_URL"))


async def forward_to_inbox(text: str, chat_id: int, couple_id: int | None = None) -> bool:
    """Send one captured message to Pensieve's inbox. Returns True on success.

    Never raises — capture must not be able to break the bot. A failure here just
    means the caller falls back to its default reply.
    """
    base_url = os.getenv("PENSIEVE_INBOX_URL")
    if not base_url:
        return False

    token = os.getenv("PENSIEVE_INBOX_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload = {"source": "telegram", "text": text, "chat_id": chat_id}
    if couple_id is not None:
        payload["couple_id"] = couple_id

    timeout = aiohttp.ClientTimeout(total=float(os.getenv("PENSIEVE_INBOX_TIMEOUT", "8")))
    url = f"{base_url.rstrip('/')}/inbox"
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    logger.warning("Pensieve inbox rejected message: HTTP %s", resp.status)
                    return False
                return True
    except Exception as e:  # network error, timeout, bad URL — never break the bot
        logger.warning("Failed to forward message to Pensieve inbox: %s", e)
        return False
