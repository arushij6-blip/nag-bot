"""Smoke tests for the Pensieve integration and regression checks for existing
Nag Bot behavior. Plain-python (no pytest dependency):

    python tests/test_pensieve_integration.py

Sets DATA_DIR to a temp dir before importing anything that touches the DB.
"""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

# Isolate the DB before importing the app modules.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="nagbot-test-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import bot
import pensieve_client
from menu_api import create_menu_app

PASS, FAIL = "✅", "❌"
_failures = []


def check(name, cond):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        _failures.append(name)


# ----- fakes ---------------------------------------------------------------
class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


def fake_update(text, chat_id=111):
    msg = FakeMessage(text)
    return SimpleNamespace(
        message=msg,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(first_name="Tester"),
    )


def set_couple(couple):
    """Patch resolve_caller's DB lookup in the bot module."""
    bot.get_couple_for_chat = lambda chat_id: couple


PAIRED = {"couple_id": 1, "self_chat_id": 111, "partner_chat_id": 222,
          "paired": True, "self_name": "A", "partner_name": "B"}
UNPAIRED = {**PAIRED, "paired": False}


# ----- existing behavior (regressions) -------------------------------------
def test_parse_deadline_intact():
    print("parse_deadline (existing):")
    check("'tomorrow' parses", bot.parse_deadline("tomorrow") is not None)
    check("'13 April 9AM' parses", bot.parse_deadline("13 April 9AM") is not None)
    check("'2026-05-13 09:00' parses", bot.parse_deadline("2026-05-13 09:00") is not None)
    check("garbage returns None", bot.parse_deadline("blah blah") is None)


def test_freetext_unknown_chat():
    print("handle_freetext — unknown chat (existing nudge):")
    set_couple(None)
    upd = fake_update("hello")
    asyncio.run(bot.handle_freetext(upd, None))
    check("nudges to /start", upd.message.replies == ["Send /start to begin."])


def test_freetext_pensieve_disabled():
    print("handle_freetext — paired, Pensieve OFF (unchanged behavior):")
    set_couple(PAIRED)
    os.environ.pop("PENSIEVE_INBOX_URL", None)
    upd = fake_update("buy milk")
    asyncio.run(bot.handle_freetext(upd, None))
    check("falls back to 'I don't understand'",
          upd.message.replies == ["I don't understand that. Try /start for commands!"])


# ----- new behavior --------------------------------------------------------
def test_freetext_forward_success(monkeypatched=True):
    print("handle_freetext — paired, Pensieve ON, forward OK:")
    set_couple(PAIRED)
    captured = {}

    async def fake_forward(text, chat_id, couple_id=None):
        captured.update(text=text, chat_id=chat_id, couple_id=couple_id)
        return True

    orig_enabled, orig_forward = pensieve_client.is_enabled, pensieve_client.forward_to_inbox
    pensieve_client.is_enabled = lambda: True
    pensieve_client.forward_to_inbox = fake_forward
    try:
        upd = fake_update("plan dinner for friday", chat_id=111)
        asyncio.run(bot.handle_freetext(upd, None))
        check("stays silent on success (Claire sends the real ack)", upd.message.replies == [])
        check("forwarded correct text", captured.get("text") == "plan dinner for friday")
        check("forwarded self chat_id", captured.get("chat_id") == 111)
        check("forwarded couple_id", captured.get("couple_id") == 1)
    finally:
        pensieve_client.is_enabled, pensieve_client.forward_to_inbox = orig_enabled, orig_forward


def test_freetext_forward_failure():
    print("handle_freetext — paired, Pensieve ON, forward FAILS:")
    set_couple(PAIRED)
    orig_enabled, orig_forward = pensieve_client.is_enabled, pensieve_client.forward_to_inbox
    pensieve_client.is_enabled = lambda: True

    async def fail_forward(*a, **k):
        return False

    pensieve_client.forward_to_inbox = fail_forward
    try:
        upd = fake_update("x")
        asyncio.run(bot.handle_freetext(upd, None))
        check("tells user to retry",
              upd.message.replies == ["Hmm, I couldn't file that just now. Try again in a moment?"])
    finally:
        pensieve_client.is_enabled, pensieve_client.forward_to_inbox = orig_enabled, orig_forward


def test_freetext_unpaired_not_forwarded():
    print("handle_freetext — unpaired couple, Pensieve ON (must NOT forward):")
    set_couple(UNPAIRED)
    called = {"n": 0}
    orig_enabled, orig_forward = pensieve_client.is_enabled, pensieve_client.forward_to_inbox
    pensieve_client.is_enabled = lambda: True

    async def counting_forward(*a, **k):
        called["n"] += 1
        return True

    pensieve_client.forward_to_inbox = counting_forward
    try:
        upd = fake_update("hi")
        asyncio.run(bot.handle_freetext(upd, None))
        check("did not forward", called["n"] == 0)
        check("default reply", upd.message.replies == ["I don't understand that. Try /start for commands!"])
    finally:
        pensieve_client.is_enabled, pensieve_client.forward_to_inbox = orig_enabled, orig_forward


def test_pensieve_client_disabled_and_live():
    print("pensieve_client.forward_to_inbox:")
    os.environ.pop("PENSIEVE_INBOX_URL", None)
    check("disabled when URL unset", asyncio.run(pensieve_client.forward_to_inbox("x", 1)) is False)

    async def run_live():
        received = {}

        async def inbox(request):
            received["payload"] = await request.json()
            received["auth"] = request.headers.get("Authorization")
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_post("/inbox", inbox)
        async with TestClient(TestServer(app)) as client:
            base = f"http://{client.host}:{client.port}"
            os.environ["PENSIEVE_INBOX_URL"] = base
            os.environ["PENSIEVE_INBOX_TOKEN"] = "secret"
            ok = await pensieve_client.forward_to_inbox("cook rice", chat_id=111, couple_id=1)
            return ok, received

    ok, received = asyncio.run(run_live())
    check("returns True on 200", ok is True)
    check("posts source=telegram", received["payload"]["source"] == "telegram")
    check("posts text", received["payload"]["text"] == "cook rice")
    check("sends bearer token", received["auth"] == "Bearer secret")
    os.environ.pop("PENSIEVE_INBOX_URL", None)
    os.environ.pop("PENSIEVE_INBOX_TOKEN", None)


# ----- menu_api /deliver + regression on /menu -----------------------------
def test_menu_api():
    print("menu_api HTTP layer:")

    async def run():
        sent = []

        async def send_cb(chat_id, text):
            sent.append((chat_id, text))
            return True

        app = create_menu_app(token="tok", send_callback=send_cb)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/health")
            check("/health open (200)", r.status == 200)

            r = await c.post("/deliver", json={"text": "hi", "chat_id": 111})
            check("/deliver needs auth (401)", r.status == 401)

            H = {"Authorization": "Bearer tok"}
            r = await c.post("/deliver", json={"text": "hi", "chat_id": 111}, headers=H)
            check("/deliver chat_id -> 200", r.status == 200)
            check("send_callback invoked", sent == [(111, "hi")])

            r = await c.post("/deliver", json={"chat_id": 111}, headers=H)
            check("/deliver missing text -> 400", r.status == 400)

            r = await c.post("/deliver", json={"text": "hi"}, headers=H)
            check("/deliver no target -> 400", r.status == 400)

            # regression: /menu still validates its input (chat_id required)
            r = await c.post("/menu", json={"meals": []}, headers=H)
            check("/menu still rejects missing chat_id (400)", r.status == 400)

        # regression: delivery unavailable when no callback wired
        app2 = create_menu_app(token="tok", send_callback=None)
        async with TestClient(TestServer(app2)) as c2:
            r = await c2.post("/deliver", json={"text": "hi", "chat_id": 1},
                              headers={"Authorization": "Bearer tok"})
            check("/deliver 503 when no send_callback", r.status == 503)

    asyncio.run(run())


def main():
    print("\n=== Pensieve integration + Nag Bot regression tests ===\n")
    test_parse_deadline_intact()
    test_freetext_unknown_chat()
    test_freetext_pensieve_disabled()
    test_freetext_forward_success()
    test_freetext_forward_failure()
    test_freetext_unpaired_not_forwarded()
    test_pensieve_client_disabled_and_live()
    test_menu_api()

    print()
    if _failures:
        print(f"{FAIL} {len(_failures)} check(s) failed: {_failures}")
        sys.exit(1)
    print(f"{PASS} All checks passed.")


if __name__ == "__main__":
    main()
