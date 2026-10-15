"""
qbank_patch.py - auto Q-Bank login (ID + password) for FULL-plan students only.

What it does
  * Full plan (lectures + notes + MCQ/Q-Bank): a unique Student ID and a strong
    password are created automatically, sent to the student in their bot, and
    pushed to Supabase (students table) so the CBT portal login works.
  * Lectures-only / revoked / banned / expired: the login is switched off in
    Supabase automatically (and switched back on if the plan is upgraded again).
  * Student command /mylogin shows their login again.
  * Admin commands: /reset_pass <telegram_id>  and  /sync_students

Install: put this file next to your bot file and add these two lines right above
`async def main():`
    import qbank_patch
    qbank_patch.apply(globals())
"""
import asyncio
import json
import logging
import os
import secrets
from datetime import datetime

import aiohttp
from telethon import Button, events

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://iafqcssktvejitssqawi.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_I6SvDlS24OOid9g9DiA9qQ_jquGYE4C")
SYNC_EVERY_SECONDS = 600

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I confusion
_pick = lambda n: "".join(secrets.choice(_ALPHA) for _ in range(n))

_G = {}
_lock = None
_pending = False
_task_started = False


# ---------------------------------------------------------------- Supabase
async def _rest(method, path, body=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.request(
            method, f"{SUPABASE_URL}/rest/v1/{path}", headers=headers,
            data=json.dumps(body) if body is not None else None,
        ) as r:
            if r.status >= 300:
                raise RuntimeError(f"Supabase {r.status}: {(await r.text())[:200]}")


async def _push(qid, passkey, name, active, expiry):
    row = {
        "student_id": qid,
        "student_name": name,
        "passkey": passkey,
        "is_demo": False,
        "active": active,
        "expires_at": f"{expiry}T23:59:59Z" if expiry else None,
    }
    await _rest("POST", "students?on_conflict=student_id", row)


# ---------------------------------------------------------------- helpers
def _db():
    return _G["g"]["db"]  # looked up each time: the bot may reassign db on restore


def _display_name(uid):
    u = _db().get("users", {}).get(str(uid), {})
    return (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username") or f"Candidate {uid}")


def _is_full(uid):
    d, g = _db(), _G["g"]
    return (
        uid != g["ADMIN_ID"]
        and uid in d.get("approved", [])
        and uid not in d.get("banned", [])
        and d.get("approved_details", {}).get(str(uid), {}).get("content_tier") == "full"
    )


def _get_or_create(user_id):
    """Replacement for the bot's get_or_create_qbank_creds (unique ID, strong password)."""
    d = _db()
    s = str(user_id)
    det = d["approved_details"].setdefault(s, {})
    if not det.get("qbank_id") or not det.get("qbank_pass"):
        used = {x.get("qbank_id") for x in d["approved_details"].values()}
        qid = "STU-" + _pick(5)
        while qid in used:
            qid = "STU-" + _pick(5)
        det["qbank_id"] = qid
        det["qbank_pass"] = _pick(8)
        det["qb_state"] = None
        det["creds_sent"] = False
        _G["orig_save"](d)
    return det["qbank_id"], det["qbank_pass"]


async def _notify(uid):
    g = _G["g"]
    qid, pw = _get_or_create(uid)
    text = (
        "🎉 **Your CBT Q-Bank login is ready!**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Student ID:** `{qid}`\n"
        f"🔑 **Password:** `{pw}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the interactive CBT app (auto-login). "
        "Send /mylogin any time to see this again."
    )
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", g["generate_webapp_launch_url"](uid))]]
    pref = _db().get("users", {}).get(str(uid), {}).get("bot_used")
    bots = g["active_bots"]
    order = ([bots[pref]] if pref in bots else []) + [b for k, b in bots.items() if k != pref]
    for bot in order:
        try:
            await bot.send_message(uid, text, buttons=buttons)
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- reconcile
async def _reconcile():
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        d, g = _db(), _G["g"]
        changed = False
        for s, det in list(d.get("approved_details", {}).items()):
            uid = int(s)
            if uid == g["ADMIN_ID"]:
                continue
            full = _is_full(uid)
            if full and not det.get("qbank_id"):
                _get_or_create(uid)
            if not det.get("qbank_id"):
                continue
            if "creds_sent" not in det:
                det["creds_sent"] = True  # logins issued before this patch: already shown in /start
            expiry = det.get("expiry")
            expired = False
            if expiry and d.get("settings", {}).get("expiry_enabled"):
                try:
                    expired = datetime.now().date() > datetime.strptime(expiry, "%Y-%m-%d").date()
                except Exception:
                    pass
            want = f"on:{expiry}" if (full and not expired) else "off"
            if det.get("qb_state") == want:
                continue
            try:
                await _push(det["qbank_id"], det["qbank_pass"], _display_name(uid),
                            want != "off", expiry)
            except Exception as e:
                logging.warning("Q-Bank sync failed for %s: %s", s, e)
                continue
            det["qb_state"] = want
            changed = True
            if want != "off" and not det.get("creds_sent"):
                if await _notify(uid):
                    det["creds_sent"] = True
        if changed:
            _G["orig_save"](d)


async def _run():
    global _pending
    _pending = False
    try:
        await _reconcile()
    except Exception:
        logging.exception("Q-Bank reconcile failed")


def _schedule():
    global _pending
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _pending:
        return
    _pending = True
    loop.call_later(1.5, lambda: loop.create_task(_run()))


async def _periodic():
    while True:
        await _run()
        await asyncio.sleep(SYNC_EVERY_SECONDS)


def _ensure_task():
    global _task_started
    if not _task_started:
        _task_started = True
        asyncio.get_running_loop().create_task(_periodic())


# ---------------------------------------------------------------- apply
def apply(g):
    _G["g"] = g
    _G["orig_save"] = g["save_db"]
    orig_bot_setup = g["setup_bot_handlers"]
    orig_mgr_setup = g["setup_manager_bot_handlers"]
    orig_save = g["save_db"]

    def save_db(data):
        orig_save(data)
        _schedule()

    g["save_db"] = save_db
    g["get_or_create_qbank_creds"] = _get_or_create

    def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
        box = orig_bot_setup(bot_client=bot_client, bot_key=bot_key,
                             bot_topics=bot_topics, bot_title=bot_title)
        _ensure_task()

        @bot_client.on(events.NewMessage(pattern=r"^/mylogin$"))
        async def mylogin(event):
            uid = event.sender_id
            if uid == g["ADMIN_ID"]:
                await event.respond("ℹ️ Admin accounts do not use a student Q-Bank login.")
                return
            if g["is_banned"](uid) or not _is_full(uid):
                await event.respond(
                    "🔒 The CBT Q-Bank login is included in the **Full plan** "
                    f"(Lectures + Notes + MCQ).\nTo upgrade, contact {g['OWNER_CONTACT']}."
                )
                return
            allowed, _ = g["check_access"](uid, bot_key)
            if not allowed:
                await event.respond("🔒 Your access is not active. Contact " + g["OWNER_CONTACT"])
                return
            qid, pw = _get_or_create(uid)
            await event.respond(
                f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`",
                buttons=[[Button.url("🌐 Launch MBBS CBT Q-Bank", g["generate_webapp_launch_url"](uid))]],
            )

        return box

    def setup_manager_bot_handlers(client):
        orig_mgr_setup(client)
        _ensure_task()

        @client.on(events.NewMessage(pattern=r"^/reset_pass (\d+)$"))
        async def reset_pass(event):
            if event.sender_id != g["ADMIN_ID"]:
                return
            uid = int(event.pattern_match.group(1))
            if not _is_full(uid):
                await event.respond("⚠️ That user is not on the Full plan.")
                return
            det = _db()["approved_details"][str(uid)]
            _get_or_create(uid)
            det["qbank_pass"] = _pick(8)
            det["qb_state"] = None
            det["creds_sent"] = False
            _G["orig_save"](_db())
            await _run()
            await event.respond(f"✅ New password generated and sent to `{uid}`.")

        @client.on(events.NewMessage(pattern=r"^/sync_students$"))
        async def sync_students(event):
            if event.sender_id != g["ADMIN_ID"]:
                return
            for det in _db().get("approved_details", {}).values():
                det["qb_state"] = None
                det["creds_sent"] = det.get("creds_sent", True)
            _G["orig_save"](_db())
            await _run()
            on = sum(1 for x in _db()["approved_details"].values()
                     if str(x.get("qb_state", "")).startswith("on"))
            await event.respond(f"✅ Synced to Supabase. Active Q-Bank logins: `{on}`")

    g["setup_bot_handlers"] = setup_bot_handlers
    g["setup_manager_bot_handlers"] = setup_manager_bot_handlers
    logging.info("qbank_patch applied: auto Q-Bank logins for Full plan are active.")
