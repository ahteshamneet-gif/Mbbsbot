#!/usr/bin/env python3
# ============================================================
# MBBS Lecture & CBT Q-Bank Bot - Unified Production Engine (fixed)
#  - Student UI: Subject -> Lectures / Notes / MCQ Hub, #hashtag units + Search
#  - Year-wise Demo bot (student picks year, or admin locks one year)
#  - Supabase cloud DB + Telegram "Saved Messages" backup/restore fallback
#  - Button-driven admin panel
# ============================================================

import asyncio
import io
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, MessageNotModifiedError
from telethon.sessions import StringSession

# ============================================================
# CONFIGURATION  (secrets ONLY from environment variables)
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

CBT_WEBAPP_BASE_URL = os.getenv("CBT_WEBAPP_BASE_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/index.html")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://iafqcssktvejitssqawi.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

SESSION_STRING = re.sub(r"\s+", "", os.getenv("SESSION_STRING", "")).strip("'\"`")
PAID_USERS_JSON_RAW = os.getenv("PAID_USERS_BACKUP", "").strip()
SYNC_INTERVAL_SECONDS = 600
BACKUP_INTERVAL_SECONDS = 6 * 3600

BOT_TOKENS = {
    "all": os.getenv("BOT_TOKEN_ALL", "").strip(),
    "year_1": os.getenv("BOT_TOKEN_Y1", "").strip(),
    "year_2": os.getenv("BOT_TOKEN_Y2", "").strip(),
    "year_3": os.getenv("BOT_TOKEN_Y3", "").strip(),
    "final_year": os.getenv("BOT_TOKEN_FINAL", "").strip(),
    "demo": os.getenv("BOT_TOKEN_DEMO", "").strip(),
    "manager": os.getenv("BOT_TOKEN_MANAGER", "").strip(),
}

# ============================================================
# SUBJECTS PER YEAR
# ============================================================

NOTES_TOPIC = 33
TOPICS_ALL = {
    "Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Microbiology": 5, "Notes": 33,
    "Pathology": 49, "Pharmacology": 50, "Forensic Medicine and Toxicology": 51,
    "Community Medicine": 52, "General Medicine": 53, "General Surgery": 54,
    "Obstetrics and Gynecology": 55, "Pediatrics": 56, "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58, "Orthopedics": 59, "Anesthesiology": 60,
    "Radiology": 61, "Dermatology": 62, "Psychiatry": 63,
}
TOPICS_Y1 = {"Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Notes": 33}
# FIX: Forensic Medicine removed from 2nd year
TOPICS_Y2 = {"Pathology": 49, "Pharmacology": 50, "Microbiology": 5, "Notes": 33}
TOPICS_Y3 = {
    "Community Medicine": 52, "Ophthalmology": 57, "Otorhinolaryngology (ENT)": 58,
    "Forensic Medicine and Toxicology": 51, "Notes": 33,
}
TOPICS_FINAL = {
    "General Medicine": 53, "General Surgery": 54, "Obstetrics and Gynecology": 55,
    "Pediatrics": 56, "Orthopedics": 59, "Anesthesiology": 60, "Radiology": 61,
    "Dermatology": 62, "Psychiatry": 63, "Notes": 33,
}

# FIX: "demo" is NOT here any more - demo subjects depend on the chosen year
BOT_SUBJECTS_MAP = {
    "all": TOPICS_ALL, "year_1": TOPICS_Y1, "year_2": TOPICS_Y2,
    "year_3": TOPICS_Y3, "final_year": TOPICS_FINAL,
}
BOT_TITLES_MAP = {
    "all": "MBBS Full Library (All Subjects)",
    "year_1": "MBBS 1st Year Library",
    "year_2": "MBBS 2nd Year Library",
    "year_3": "MBBS 3rd Year Library",
    "final_year": "MBBS 4th / Final Year Library",
    "demo": "MBBS Demo Trial Experience",
    "manager": "Admin Manager",
}
TIER_LABELS = {"all": "All Years", "year_1": "1st Year", "year_2": "2nd Year",
               "year_3": "3rd Year", "final_year": "Final Year"}
TIER_SHORT = {"all": "All", "year_1": "1st", "year_2": "2nd", "year_3": "3rd", "final_year": "Final"}
CONTENT_LABELS = {"full": "Full (Lec + Notes + Q-Bank)", "lectures_only": "Lectures & Notes Only"}
YEAR_CHOICES = ["year_1", "year_2", "year_3", "final_year"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)

# ============================================================
# DATABASE & HYBRID CLOUD STORAGE
# ============================================================

DB_FILE = "bot_database.json"
DEFAULT_SETTINGS = {
    "expiry_enabled": False, "tier_access_enabled": False,
    "daily_limit_enabled": False, "daily_limit_max": 30,
    "cloud_backup_enabled": True,
    "demo_duration_mins": 10, "demo_max_downloads": 2,
    "demo_year_tier": "all",  # "all" = student chooses year; else locked year
    "demo_auto_start": True,
    "default_content": "full", "default_days": 0,
}


def _empty_db():
    return {"users": {}, "banned": [], "approved": [], "approved_details": {},
            "settings": DEFAULT_SETTINGS.copy(), "daily_downloads": {},
            "demo_sessions": {}, "pending": {}}


def normalize_db(data):
    base = _empty_db()
    if isinstance(data, dict):
        base.update(data)
    if not isinstance(base.get("settings"), dict):
        base["settings"] = {}
    for k, v in DEFAULT_SETTINGS.items():
        base["settings"].setdefault(k, v)
    for key in ("users", "approved_details", "daily_downloads", "demo_sessions", "pending"):
        if not isinstance(base.get(key), dict):
            base[key] = {}
    for key in ("banned", "approved"):
        if not isinstance(base.get(key), list):
            base[key] = []
    for key in ("approved", "banned"):
        clean = []
        for x in base[key]:
            try:
                v = int(x)
                if v not in clean:
                    clean.append(v)
            except Exception:
                pass
        base[key] = clean
    for uid in base["approved"]:
        base["approved_details"].setdefault(str(uid), {
            "tier": "all", "content_tier": "full", "expiry": None,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return base


def load_db():
    data = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logging.exception("Failed to read database file")
    data = normalize_db(data)
    if PAID_USERS_JSON_RAW:
        try:
            env = json.loads(PAID_USERS_JSON_RAW)
            if isinstance(env, dict):
                for uid, val in env.get("users", {}).items():
                    data["users"].setdefault(str(uid), val)
                for uid in env.get("approved", []):
                    if int(uid) not in data["approved"]:
                        data["approved"].append(int(uid))
                for uid, val in env.get("approved_details", {}).items():
                    data["approved_details"].setdefault(str(uid), val)
                logging.info("Merged paid users from PAID_USERS_BACKUP.")
        except Exception:
            logging.exception("Failed parsing PAID_USERS_BACKUP")
    return normalize_db(data)


db = load_db()
_cloud_ok = False
_cloud_save_pending = False


def _cloud_headers():
    return {"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json"}


async def cloud_load_db():
    if not SUPABASE_SERVICE_KEY:
        return False, None
    try:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"{SUPABASE_URL}/rest/v1/bot_state?id=eq.1&select=data",
                             headers=_cloud_headers()) as r:
                if r.status >= 300:
                    logging.warning("Cloud load failed %s: %s", r.status, (await r.text())[:200])
                    return False, None
                rows = await r.json()
                return True, (rows[0]["data"] if rows else None)
    except Exception:
        logging.exception("Cloud load failed")
        return False, None


async def cloud_save_db():
    global _cloud_save_pending
    _cloud_save_pending = False
    if not SUPABASE_SERVICE_KEY or not _cloud_ok:
        return
    try:
        headers = _cloud_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{SUPABASE_URL}/rest/v1/bot_state?on_conflict=id", headers=headers,
                              data=json.dumps({"id": 1, "data": db})) as r:
                if r.status >= 300:
                    logging.warning("Cloud save failed %s: %s", r.status, (await r.text())[:200])
    except Exception:
        logging.exception("Cloud save failed")


def schedule_cloud_save():
    global _cloud_save_pending
    if _cloud_save_pending or not _cloud_ok:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _cloud_save_pending = True
    loop.call_later(2.0, lambda: loop.create_task(cloud_save_db()))


def _write_local(data):
    try:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DB_FILE)
    except Exception:
        logging.exception("Failed to write database file")


def _write_db(data):
    _write_local(data)
    schedule_cloud_save()


def save_db(data):
    _write_db(data)
    schedule_reconcile()


def ensure_admin():
    if ADMIN_ID not in db["approved"]:
        db["approved"].append(ADMIN_ID)
    old = db["approved_details"].get(str(ADMIN_ID), {})
    db["approved_details"][str(ADMIN_ID)] = {
        "tier": "all", "content_tier": "full", "expiry": None, "added_at": "SYSTEM",
        **{k: v for k, v in old.items() if k in ("qbank_id", "qbank_pass", "qb_state", "creds_sent")},
    }


def _merge_local_into(cloud):
    local = db
    for uid in local["approved"]:
        if uid not in cloud["approved"]:
            cloud["approved"].append(uid)
            cloud["approved_details"].setdefault(str(uid), local["approved_details"].get(str(uid), {}))
    for uid in local["banned"]:
        if uid not in cloud["banned"]:
            cloud["banned"].append(uid)
    for k in ("users", "demo_sessions", "pending"):
        for uid, v in local.get(k, {}).items():
            cloud[k].setdefault(uid, v)
    return cloud


async def restore_db_from_cloud(retries=4, merge_local=False):
    global _cloud_ok
    if not SUPABASE_SERVICE_KEY:
        return False
    for i in range(retries):
        ok, cloud = await cloud_load_db()
        if ok:
            if cloud:
                cloud = normalize_db(cloud)
                if merge_local:
                    cloud = _merge_local_into(cloud)
                db.clear()
                db.update(cloud)
                logging.info("Database restored from Supabase: %d paid users", len(db["approved"]))
            else:
                logging.info("No cloud DB yet; seeding it from local data.")
            ensure_admin()
            _cloud_ok = True
            _write_local(db)
            await cloud_save_db()
            return True
        await asyncio.sleep(3 * (i + 1))
    logging.error("Could not reach Supabase cloud DB; running on local data.")
    return False


ensure_admin()
_write_local(db)

# ============================================================
# HELPERS & Q-BANK CREDENTIALS
# ============================================================

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _pick(n):
    return "".join(secrets.choice(_ALPHA) for _ in range(n))


def esc(s):
    return re.sub(r"[*_`\[\]]", "", str(s or ""))


def display_name(uid):
    u = db.get("users", {}).get(str(uid), {})
    return (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username") or f"Candidate {uid}")


def get_or_create_qbank_creds(user_id, sync=True):
    s_uid = str(user_id)
    det = db["approved_details"].setdefault(s_uid, {})
    if not det.get("qbank_id") or not det.get("qbank_pass"):
        used = {x.get("qbank_id") for x in db["approved_details"].values()}
        qid = "STU-" + _pick(5)
        while qid in used:
            qid = "STU-" + _pick(5)
        det["qbank_id"] = qid
        det["qbank_pass"] = _pick(8)
        det["qb_state"] = None
        det["creds_sent"] = False
        # FIX: save_db also triggers Supabase reconcile (was _write_db -> never synced)
        (save_db if sync else _write_db)(db)
    return det["qbank_id"], det["qbank_pass"]


def has_qbank(user_id):
    uid = int(user_id)
    return (uid != ADMIN_ID and uid in db["approved"] and uid not in db["banned"]
            and db["approved_details"].get(str(uid), {}).get("content_tier") == "full")


def generate_webapp_launch_url(user_id):
    if int(user_id) == ADMIN_ID:
        return CBT_WEBAPP_BASE_URL
    qid, qpass = get_or_create_qbank_creds(user_id)
    return f"{CBT_WEBAPP_BASE_URL}?uid={quote(qid)}&key={quote(qpass)}"


def generate_demo_webapp_url(qid, qpass):
    return f"{CBT_WEBAPP_BASE_URL}?uid={quote(qid)}&key={quote(qpass)}"


# ============================================================
# SUPABASE STUDENT SYNC & CLIENTS
# ============================================================

async def supabase_upsert_student(student_id, passkey, name, active=True, expires_at=None, is_demo=False):
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY  # prefer service key for writes
    if not SUPABASE_URL or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set")
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    row = {"student_id": student_id, "student_name": name, "passkey": passkey,
           "is_demo": is_demo, "active": active, "expires_at": expires_at}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(f"{SUPABASE_URL}/rest/v1/students?on_conflict=student_id",
                          headers=headers, data=json.dumps(row)) as r:
            if r.status >= 300:
                raise RuntimeError(f"Supabase {r.status}: {(await r.text())[:200]}")


def _make_user_client():
    if not SESSION_STRING:
        return TelegramClient("session", API_ID, API_HASH)
    try:
        return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    except Exception:
        logging.warning("Invalid SESSION_STRING, falling back to 'session' file.")
        return TelegramClient("session", API_ID, API_HASH)


user_client = _make_user_client()
active_bots = {}
START_TIME = time.time()

user_state = {}          # uid -> {"subject","kind","tag","page","q"}
user_search_state = {}   # uid -> True while waiting for a search text
TOPIC_CACHE = {}
TOPIC_LOCKS = {}
TOPIC_CACHE_TTL = 600
ADMIN_STATES = {}
PAGE_SIZE = 8
UNITS_PER_PAGE = 10

_reconcile_lock = None
_reconcile_pending = False


async def send_via_any(chat_id, text, buttons=None, pref=None):
    if pref is None:
        pref = db.get("users", {}).get(str(chat_id), {}).get("bot_used")
    bots = [active_bots[pref]] if pref in active_bots else []
    bots += [b for k, b in active_bots.items() if k != pref]
    for bot in bots:
        try:
            await bot.send_message(chat_id, text, buttons=buttons)
            return True
        except FloodWaitError as e:
            await asyncio.sleep(min(e.seconds, 15) + 1)
            try:
                await bot.send_message(chat_id, text, buttons=buttons)
                return True
            except Exception:
                continue
        except Exception:
            continue
    return False


async def send_login_card(chat_id, user_id, title="🎉 **Your CBT Q-Bank login is ready!**"):
    qid, pw = get_or_create_qbank_creds(user_id, sync=False)
    text = (f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap below to open the interactive CBT app (auto-login).\n"
            "Send /mylogin any time to see this again.")
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))]]
    return await send_via_any(chat_id, text, buttons)


def is_expired(det):
    expiry = det.get("expiry")
    if expiry and db["settings"].get("expiry_enabled"):
        try:
            return datetime.now().date() > datetime.strptime(expiry, "%Y-%m-%d").date()
        except Exception:
            return False
    return False


async def reconcile_now():
    """Make Supabase match the bot: Full plan -> login ON; anything else -> OFF."""
    global _reconcile_lock, _reconcile_pending
    _reconcile_pending = False
    if _reconcile_lock is None:
        _reconcile_lock = asyncio.Lock()
    async with _reconcile_lock:
        changed = False
        for s, det in list(db.get("approved_details", {}).items()):
            try:
                uid = int(s)
            except Exception:
                continue
            if uid == ADMIN_ID:
                continue
            full = has_qbank(uid)
            if full and not det.get("qbank_id"):
                get_or_create_qbank_creds(uid, sync=False)
            if not det.get("qbank_id"):
                continue
            if "creds_sent" not in det:
                det["creds_sent"] = True
            expiry = det.get("expiry")
            want = f"on:{expiry}" if (full and not is_expired(det)) else "off"
            if det.get("qb_state") == want:
                continue
            try:
                await supabase_upsert_student(
                    det["qbank_id"], det["qbank_pass"], display_name(uid),
                    active=(want != "off"),
                    expires_at=f"{expiry}T23:59:59Z" if expiry else None)
            except Exception as e:
                logging.warning("Q-Bank sync failed for %s: %s", s, e)
                continue
            det["qb_state"] = want
            changed = True
            if want != "off" and not det.get("creds_sent"):
                if await send_login_card(uid, uid):
                    det["creds_sent"] = True
        if changed:
            _write_db(db)


def schedule_reconcile():
    global _reconcile_pending
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _reconcile_pending:
        return
    _reconcile_pending = True
    loop.call_later(1.5, lambda: loop.create_task(reconcile_now()))


# ============================================================
# ACCESS CONTROL, DEMO YEAR LOGIC, DOWNLOAD LIMITS
# ============================================================

def demo_year(uid):
    """Year used by the demo bot for this user (None = not chosen yet)."""
    lock = db["settings"].get("demo_year_tier", "all")
    if lock in YEAR_CHOICES:
        return lock
    return db["demo_sessions"].get(str(uid), {}).get("year")


def get_subjects(bot_key, user_id=None):
    """Subject dict for a bot. Demo bot follows the selected/locked year.
    Returns None for demo when the student must still pick a year."""
    if bot_key == "demo":
        yr = demo_year(user_id)
        return BOT_SUBJECTS_MAP.get(yr) if yr else None
    return BOT_SUBJECTS_MAP.get(bot_key, TOPICS_ALL)


def demo_status(uid):
    """-> (ok, message). Starts a demo automatically if enabled."""
    s = db["settings"]
    sess = db["demo_sessions"].get(str(uid))
    if not sess:
        if not s.get("demo_auto_start"):
            return False, f"⏳ Demo is not started for you yet. Ask {OWNER_CONTACT}."
        sess = {"started": time.time(), "downloads": 0, "year": None}
        db["demo_sessions"][str(uid)] = sess
        _write_db(db)
    left = sess["started"] + s["demo_duration_mins"] * 60 - time.time()
    if left <= 0:
        return False, f"⌛ Your demo has ended. For full access contact {OWNER_CONTACT}."
    return True, ""


def check_access(uid, key):
    if uid == ADMIN_ID:
        return True, ""
    if key == "manager":
        return False, "🔒 Admin only bot."
    if uid in db["banned"]:
        return False, "🚫 You are banned from this bot."
    if key == "demo":
        return demo_status(uid)
    if uid not in db["approved"]:
        return False, "not_approved"
    det = db["approved_details"].get(str(uid), {})
    if is_expired(det):
        return False, f"⌛ Your plan has expired. Renew via {OWNER_CONTACT}."
    if db["settings"].get("tier_access_enabled") and key != "all":
        if det.get("tier", "all") not in ("all", key):
            return False, (f"🔒 Your plan is **{TIER_LABELS.get(det.get('tier'), '?')}**. "
                           f"This bot is for {TIER_LABELS.get(key)}.")
    return True, ""


def can_download(uid, key):
    if uid == ADMIN_ID:
        return True, ""
    s = db["settings"]
    if key == "demo":
        sess = db["demo_sessions"].get(str(uid), {})
        if sess.get("downloads", 0) >= s["demo_max_downloads"]:
            return False, f"🔒 Demo download limit reached. Full access: {OWNER_CONTACT}"
    elif s.get("daily_limit_enabled"):
        rec = db["daily_downloads"].get(str(uid), {})
        if rec.get("date") == datetime.now().strftime("%Y-%m-%d") and rec.get("count", 0) >= s["daily_limit_max"]:
            return False, f"📅 Daily limit ({s['daily_limit_max']}) reached. Try tomorrow."
    return True, ""


def record_download(uid, key):
    if uid == ADMIN_ID:
        return
    if key == "demo":
        sess = db["demo_sessions"].setdefault(str(uid), {"started": time.time(), "downloads": 0, "year": None})
        sess["downloads"] = sess.get("downloads", 0) + 1
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        rec = db["daily_downloads"].get(str(uid), {})
        if rec.get("date") != today:
            rec = {"date": today, "count": 0}
        rec["count"] += 1
        db["daily_downloads"][str(uid)] = rec
    _write_db(db)


async def ensure_demo_creds(uid):
    sess = db["demo_sessions"].setdefault(str(uid), {"started": time.time(), "downloads": 0, "year": None})
    if not sess.get("qid"):
        sess["qid"], sess["qpass"] = "DEMO-" + _pick(4), _pick(8)
        exp = datetime.fromtimestamp(
            sess["started"] + db["settings"]["demo_duration_mins"] * 60, timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            await supabase_upsert_student(sess["qid"], sess["qpass"], f"Demo {display_name(uid)}",
                                          True, exp, is_demo=True)
        except Exception as e:
            logging.warning("Demo creds sync failed: %s", e)
            sess.pop("qid", None)
            return None
        _write_db(db)
    return generate_demo_webapp_url(sess["qid"], sess["qpass"])


# ============================================================
# TOPIC CONTENT (read via the user client, delivered by the bot)
# ============================================================

async def get_topic_items(topic_id):
    now = time.time()
    c = TOPIC_CACHE.get(topic_id)
    if c and now - c[0] < TOPIC_CACHE_TTL:
        return c[1]
    lock = TOPIC_LOCKS.setdefault(topic_id, asyncio.Lock())
    async with lock:
        c = TOPIC_CACHE.get(topic_id)
        if c and time.time() - c[0] < TOPIC_CACHE_TTL:
            return c[1]
        items = []
        try:
            async for m in user_client.iter_messages(GROUP_ID, reply_to=topic_id, limit=1500):
                if not m.media and not m.text:
                    continue
                text = m.text or ""
                name = (text.strip().split("\n")[0] if text.strip()
                        else (m.file.name if m.file and m.file.name else f"File {m.id}"))
                items.append({"id": m.id, "name": name[:60], "text": text.lower(),
                              "tags": [t.lower() for t in re.findall(r"#(\w+)", text)]})
            items.reverse()  # oldest first
        except Exception:
            logging.exception("Failed loading topic %s", topic_id)
            return c[1] if c else []
        TOPIC_CACHE[topic_id] = (time.time(), items)
        return items


def subject_slug(subject):
    return re.sub(r"\W", "", subject.lower())


async def items_for(st):
    subject, kind = st["subject"], st["kind"]
    if subject == "Notes":
        items = await get_topic_items(NOTES_TOPIC)
    elif kind == "not":
        slug = subject_slug(subject)[:5]
        items = [i for i in await get_topic_items(NOTES_TOPIC) if any(slug in t for t in i["tags"])]
    else:
        items = await get_topic_items(TOPICS_ALL[subject])
    return items


# ============================================================
# UI HELPERS
# ============================================================

async def show(event, text, buttons=None):
    try:
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)
    except MessageNotModifiedError:
        pass


def track_user(sender, key):
    uid = str(sender.id)
    u = db["users"].setdefault(uid, {"joined": datetime.now().strftime("%Y-%m-%d %H:%M")})
    u.update({"first_name": sender.first_name or "", "last_name": sender.last_name or "",
              "username": sender.username or "", "bot_used": key})
    _write_db(db)


def year_picker_buttons():
    rows = [[Button.inline(TIER_LABELS[y], f"y:{y}".encode())] for y in YEAR_CHOICES]
    return rows


async def show_home(event, uid, key):
    ok, why = check_access(uid, key)
    if not ok:
        return await show_denied(event, uid, key, why)
    subjects = get_subjects(key, uid)
    if subjects is None:  # demo, year not chosen yet
        return await show(event, "🎓 **Demo Trial**\n\nSelect your MBBS year to see its subjects:",
                          year_picker_buttons())
    if uid == ADMIN_ID and key == "demo":
        subjects = subjects or TOPICS_ALL
    names = list(subjects.keys())
    rows = [[Button.inline(f"📚 {n}", f"s:{n}".encode()) for n in names[i:i + 2]]
            for i in range(0, len(names), 2)]
    if key == "demo" and db["settings"].get("demo_year_tier", "all") == "all":
        rows.append([Button.inline("🔄 Change Year", b"chy")])
    if key != "demo" and has_qbank(uid):
        rows.append([Button.url("🧠 CBT Q-Bank", generate_webapp_launch_url(uid))])
    head = f"🏥 **{BOT_TITLES_MAP.get(key, 'MBBS Library')}**"
    if key == "demo":
        head += f"\n🎓 Year: **{TIER_LABELS.get(demo_year(uid), '?')}**"
        sess = db["demo_sessions"].get(str(uid), {})
        left = sess.get("started", time.time()) + db["settings"]["demo_duration_mins"] * 60 - time.time()
        head += (f"\n⏱ {max(0, int(left // 60))} min left | "
                 f"📥 {sess.get('downloads', 0)}/{db['settings']['demo_max_downloads']} downloads")
    await show(event, head + "\n\nChoose a subject:", rows)


async def show_denied(event, uid, key, why):
    if why == "not_approved":
        rows = [[Button.inline("📩 Request Access", b"req")]]
        return await show(event, f"🔐 You don't have access yet.\nContact {OWNER_CONTACT} or request below.", rows)
    await show(event, why)


async def show_subject(event, uid, key, subject):
    subjects = get_subjects(key, uid) or (TOPICS_ALL if uid == ADMIN_ID else {})
    if subject not in subjects:
        return await show_home(event, uid, key)
    if subject == "Notes":
        user_state[uid] = {"subject": "Notes", "kind": "lec", "tag": None, "page": 0, "q": None}
        return await render_list(event, uid, key)
    if has_qbank(uid) or uid == ADMIN_ID:
        mcq = Button.url("🧠 MCQ Hub", generate_webapp_launch_url(uid))
    else:
        mcq = Button.inline("🧠 MCQ Hub 🔒", b"noqb")
    rows = [[Button.inline("🎬 Lectures", f"k:lec:{subject}".encode()),
             Button.inline("📝 Notes", f"k:not:{subject}".encode())],
            [mcq], [Button.inline("⬅️ Back", b"home")]]
    await show(event, f"📘 **{esc(subject)}**\n\nWhat do you need?", rows)


async def render_list(event, uid, key):
    st = user_state.get(uid)
    if not st:
        return await show_home(event, uid, key)
    items = await items_for(st)
    if not items:
        return await show(event, "📭 Nothing uploaded here yet.", [[Button.inline("⬅️ Back", b"back")]])

    # units view (hashtags) when nothing selected
    if not st["tag"] and not st["q"]:
        tags = sorted({t for i in items for t in i["tags"]})
        if tags:
            st["tags"] = tags
            p = st.get("upage", 0)
            chunk = tags[p * UNITS_PER_PAGE:(p + 1) * UNITS_PER_PAGE]
            rows = [[Button.inline(f"#{t}", f"u:{tags.index(t)}".encode()) for t in chunk[i:i + 2]]
                    for i in range(0, len(chunk), 2)]
            nav = []
            if p > 0:
                nav.append(Button.inline("◀️", f"up:{p - 1}".encode()))
            if (p + 1) * UNITS_PER_PAGE < len(tags):
                nav.append(Button.inline("▶️", f"up:{p + 1}".encode()))
            if nav:
                rows.append(nav)
            rows.append([Button.inline("📋 All", b"u:all"), Button.inline("🔍 Search", b"q")])
            rows.append([Button.inline("⬅️ Back", b"back")])
            return await show(event, f"📂 **{esc(st['subject'])}** - pick a unit:", rows)

    if st["tag"]:
        items = [i for i in items if st["tag"] in i["tags"]]
    if st["q"]:
        items = [i for i in items if st["q"] in i["text"] or st["q"] in i["name"].lower()]
    total = len(items)
    p = min(st["page"], max(0, (total - 1) // PAGE_SIZE))
    st["page"] = p
    chunk = items[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
    rows = [[Button.inline(f"▶️ {i['name'][:40]}", f"g:{i['id']}".encode())] for i in chunk]
    nav = []
    if p > 0:
        nav.append(Button.inline("◀️ Prev", f"p:{p - 1}".encode()))
    if (p + 1) * PAGE_SIZE < total:
        nav.append(Button.inline("Next ▶️", f"p:{p + 1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("🔍 Search", b"q"), Button.inline("⬅️ Back", b"ub")])
    label = f"#{st['tag']}" if st["tag"] else (f"“{esc(st['q'])}”" if st["q"] else "All")
    await show(event, f"📂 **{esc(st['subject'])}** | {label} | {total} item(s)"
               if total else f"🔎 No results for {label}.", rows)


async def deliver(event, uid, key, msg_id):
    ok, why = can_download(uid, key)
    if not ok:
        return await event.answer(why.replace("**", ""), alert=True)
    ok, why = check_access(uid, key)
    if not ok:
        return await event.answer("Access ended.", alert=True)
    try:
        m = await event.client.get_messages(GROUP_ID, ids=msg_id)
        if not m:
            return await event.answer("File not found.", alert=True)
        cap = (m.text or "")[:1000]
        if m.media:
            await event.client.send_file(event.chat_id, m.media, caption=cap, parse_mode=None)
        else:
            await event.client.send_message(event.chat_id, cap, parse_mode=None)
        record_download(uid, key)
        await event.answer("✅ Sent")
    except FloodWaitError as e:
        await event.answer(f"Too fast, wait {e.seconds}s", alert=True)
    except Exception:
        logging.exception("Deliver failed")
        await event.answer("❌ Could not send. Bot must be a member of the group.", alert=True)


# ============================================================
# ADMIN PANEL
# ============================================================

def onoff(v):
    return "✅" if v else "❌"


async def admin_home(event):
    s = db["settings"]
    yr = s["demo_year_tier"]
    rows = [
        [Button.inline(f"{onoff(s['expiry_enabled'])} Expiry", b"ad:t:expiry_enabled"),
         Button.inline(f"{onoff(s['tier_access_enabled'])} Tier Lock", b"ad:t:tier_access_enabled")],
        [Button.inline(f"{onoff(s['daily_limit_enabled'])} Daily Limit", b"ad:t:daily_limit_enabled"),
         Button.inline(f"{onoff(s['cloud_backup_enabled'])} Auto Backup", b"ad:t:cloud_backup_enabled")],
        [Button.inline(f"{onoff(s['demo_auto_start'])} Demo Auto-Start", b"ad:t:demo_auto_start")],
        [Button.inline(f"🎓 Demo Year: {TIER_SHORT.get(yr, 'Student picks')}", b"ad:dy")],
        [Button.inline(f"⏱ Demo {s['demo_duration_mins']}m", b"ad:n:demo_duration_mins:5"),
         Button.inline("➖", b"ad:n:demo_duration_mins:-5")],
        [Button.inline(f"📥 Demo DL {s['demo_max_downloads']}", b"ad:n:demo_max_downloads:1"),
         Button.inline("➖", b"ad:n:demo_max_downloads:-1")],
        [Button.inline(f"📅 Daily Max {s['daily_limit_max']}", b"ad:n:daily_limit_max:5"),
         Button.inline("➖", b"ad:n:daily_limit_max:-5")],
        [Button.inline("➕ Add User", b"ad:add"), Button.inline("➖ Remove", b"ad:rm")],
        [Button.inline("🚫 Ban", b"ad:ban"), Button.inline("♻️ Unban", b"ad:unban")],
        [Button.inline("▶️ Start Demo for ID", b"ad:demo"), Button.inline("🕓 Pending", b"ad:pend")],
        [Button.inline("👥 Users", b"ad:list"), Button.inline("📊 Stats", b"ad:stats")],
        [Button.inline("💾 Backup Now", b"ad:bk"), Button.inline("🔄 Sync Q-Bank", b"ad:sync")],
    ]
    await show(event, "🛠 **Admin Control Center**\n(+ buttons increase, ➖ decrease)", rows)


def approve_user(uid, tier="all", content=None, days=None):
    s = db["settings"]
    content = content or s["default_content"]
    days = s["default_days"] if days is None else days
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d") if days else None
    if uid not in db["approved"]:
        db["approved"].append(uid)
    det = db["approved_details"].setdefault(str(uid), {})
    det.update({"tier": tier, "content_tier": content, "expiry": expiry,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    if uid in db["banned"]:
        db["banned"].remove(uid)
    db["pending"].pop(str(uid), None)
    det["qb_state"] = None
    save_db(db)


async def admin_callback(event, data):
    s = db["settings"]
    parts = data.split(":")
    act = parts[1]
    if act == "home":
        return await admin_home(event)
    if act == "t":
        s[parts[2]] = not s[parts[2]]
        save_db(db)
        return await admin_home(event)
    if act == "n":
        s[parts[2]] = max(1, s[parts[2]] + int(parts[3]))
        _write_db(db)
        return await admin_home(event)
    if act == "dy":
        order = ["all"] + YEAR_CHOICES
        s["demo_year_tier"] = order[(order.index(s["demo_year_tier"]) + 1) % len(order)]
        _write_db(db)
        return await admin_home(event)
    if act in ("add", "rm", "ban", "unban", "demo"):
        ADMIN_STATES[ADMIN_ID] = {"act": act}
        return await show(event, "Send the **numeric Telegram user ID**:",
                          [[Button.inline("⬅️ Cancel", b"ad:home")]])
    if act == "tier":
        st = ADMIN_STATES.get(ADMIN_ID, {})
        st["tier"] = parts[2]
        rows = [[Button.inline(v, f"ad:cont:{k}".encode())] for k, v in CONTENT_LABELS.items()]
        return await show(event, "Choose content plan:", rows)
    if act == "cont":
        st = ADMIN_STATES.pop(ADMIN_ID, {})
        if "uid" not in st:
            return await admin_home(event)
        approve_user(st["uid"], st.get("tier", "all"), parts[2])
        await send_via_any(st["uid"], "✅ Your access has been approved! Send /start.")
        return await show(event, f"✅ Approved `{st['uid']}`.", [[Button.inline("🛠 Panel", b"ad:home")]])
    if act in ("ap", "rj"):
        uid = int(parts[2])
        if act == "ap":
            approve_user(uid)
            await send_via_any(uid, "✅ Your access has been approved! Send /start.")
        else:
            db["pending"].pop(str(uid), None)
            _write_db(db)
        return await show(event, ("✅ Approved" if act == "ap" else "❌ Rejected") + f" `{uid}`",
                          [[Button.inline("🛠 Panel", b"ad:home")]])
    if act == "pend":
        if not db["pending"]:
            return await show(event, "No pending requests.", [[Button.inline("⬅️ Back", b"ad:home")]])
        rows = []
        for u in list(db["pending"])[:15]:
            rows.append([Button.inline(f"✅ {display_name(u)[:18]}", f"ad:ap:{u}".encode()),
                         Button.inline("❌", f"ad:rj:{u}".encode())])
        rows.append([Button.inline("⬅️ Back", b"ad:home")])
        return await show(event, "🕓 **Pending requests**", rows)
    if act == "list":
        lines = []
        for u in db["approved"][:40]:
            d = db["approved_details"].get(str(u), {})
            lines.append(f"`{u}` {esc(display_name(u))[:16]} | {TIER_SHORT.get(d.get('tier'), '?')} | "
                         f"{'Full' if d.get('content_tier') == 'full' else 'Lec'} | {d.get('expiry') or '∞'}")
        return await show(event, "👥 **Approved users**\n" + "\n".join(lines),
                          [[Button.inline("⬅️ Back", b"ad:home")]])
    if act == "stats":
        up = int((time.time() - START_TIME) // 60)
        txt = (f"📊 Users seen: {len(db['users'])}\n✅ Approved: {len(db['approved'])}\n"
               f"🚫 Banned: {len(db['banned'])}\n🎓 Demo sessions: {len(db['demo_sessions'])}\n"
               f"🕓 Pending: {len(db['pending'])}\n☁️ Cloud DB: {'ON' if _cloud_ok else 'OFF'}\n"
               f"🤖 Bots: {', '.join(active_bots)}\n⏱ Uptime: {up} min")
        return await show(event, txt, [[Button.inline("⬅️ Back", b"ad:home")]])
    if act == "bk":
        await do_backup()
        return await event.answer("💾 Backup sent to Saved Messages", alert=True)
    if act == "sync":
        for d in db["approved_details"].values():
            d["qb_state"] = None
        await reconcile_now()
        return await event.answer("🔄 Sync done", alert=True)


async def admin_text(event, text):
    """Handle numeric ID input for admin actions. Returns True if consumed."""
    st = ADMIN_STATES.get(ADMIN_ID)
    if not st or "act" not in st or not text.strip().lstrip("-").isdigit():
        return False
    uid = int(text.strip())
    act = st["act"]
    if act == "add":
        st["uid"] = uid
        st.pop("act")
        rows = [[Button.inline(v, f"ad:tier:{k}".encode())] for k, v in TIER_LABELS.items()]
        await event.respond(f"Plan for `{uid}` - choose year access:", buttons=rows)
        return True
    ADMIN_STATES.pop(ADMIN_ID, None)
    if act == "rm":
        if uid in db["approved"] and uid != ADMIN_ID:
            db["approved"].remove(uid)
            db["approved_details"].get(str(uid), {})["qb_state"] = None
            save_db(db)
            await reconcile_now()
        msg = f"➖ Removed `{uid}`"
    elif act == "ban":
        if uid != ADMIN_ID and uid not in db["banned"]:
            db["banned"].append(uid)
        save_db(db)
        msg = f"🚫 Banned `{uid}`"
    elif act == "unban":
        if uid in db["banned"]:
            db["banned"].remove(uid)
        save_db(db)
        msg = f"♻️ Unbanned `{uid}`"
    else:  # demo
        db["demo_sessions"][str(uid)] = {"started": time.time(), "downloads": 0, "year": None}
        _write_db(db)
        await send_via_any(uid, "🎓 Your demo has started! Send /start.", pref="demo")
        msg = f"▶️ Demo started for `{uid}`"
    await event.respond(msg, buttons=[[Button.inline("🛠 Panel", b"ad:home")]])
    return True


# ============================================================
# BACKUP (Telegram Saved Messages fallback)
# ============================================================

async def do_backup():
    try:
        bio = io.BytesIO(json.dumps(db, indent=2).encode("utf-8"))
        bio.name = "bot_database_backup.json"
        await user_client.send_file("me", bio, caption=f"bot_database_backup {datetime.now():%Y-%m-%d %H:%M}")
    except Exception:
        logging.exception("Backup failed")


async def tg_restore_if_needed():
    if _cloud_ok or len(db["approved"]) > 1:
        return
    try:
        async for m in user_client.iter_messages("me", limit=60, search="bot_database_backup"):
            if m.file and (m.file.name or "").startswith("bot_database_backup"):
                raw = await m.download_media(bytes)
                data = normalize_db(json.loads(raw.decode("utf-8")))
                db.clear()
                db.update(data)
                ensure_admin()
                _write_local(db)
                logging.info("DB auto-restored from Telegram backup (%d users).", len(db["approved"]))
                return
    except Exception:
        logging.exception("Telegram restore failed")


# ============================================================
# BOT HANDLERS
# ============================================================

def register(client, key):
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_message(event):
        uid = event.sender_id
        text = (event.raw_text or "").strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        sender = await event.get_sender()
        if sender:
            track_user(sender, key)

        if uid == ADMIN_ID:
            if cmd in ("/admin", "/panel") or (key == "manager" and cmd == "/start"):
                return await admin_home(event)
            if cmd == "/restore" and event.is_reply:
                r = await event.get_reply_message()
                try:
                    data = normalize_db(json.loads((await r.download_media(bytes)).decode("utf-8")))
                    db.clear()
                    db.update(data)
                    ensure_admin()
                    save_db(db)
                    return await event.respond(f"✅ Restored {len(db['approved'])} users.")
                except Exception as e:
                    return await event.respond(f"❌ Restore failed: {e}")
            if not cmd and await admin_text(event, text):
                return

        if key == "manager":
            return await event.respond("🔒 Admin only. Use the student bots.") if uid != ADMIN_ID else None

        if cmd == "/mylogin":
            if has_qbank(uid):
                return await send_login_card(uid, uid, "🔑 **Your CBT login**")
            return await event.respond("You don't have a Q-Bank plan.")
        if cmd == "/year" and key == "demo":
            if db["settings"]["demo_year_tier"] != "all" and uid != ADMIN_ID:
                return await event.respond("Year is locked by admin for this demo.")
            return await event.respond("Select your MBBS year:", buttons=year_picker_buttons())
        if cmd in ("/start", "/menu", "/help"):
            user_search_state.pop(uid, None)
            return await show_home(event, uid, key)

        if user_search_state.get(uid) and text and not cmd:
            user_search_state.pop(uid, None)
            st = user_state.get(uid)
            if st:
                st["q"], st["tag"], st["page"] = text.lower()[:40], None, 0
                return await render_list(event, uid, key)

    @client.on(events.CallbackQuery)
    async def on_cb(event):
        uid = event.sender_id
        data = event.data.decode()
        try:
            if data.startswith("ad:"):
                if uid != ADMIN_ID:
                    return await event.answer("Admin only", alert=True)
                return await admin_callback(event, data)

            if key == "manager":
                return await event.answer("Admin only", alert=True)

            if data == "req":
                db["pending"][str(uid)] = time.time()
                _write_db(db)
                await send_via_any(ADMIN_ID, f"🕓 Access request from **{esc(display_name(uid))}** (`{uid}`)",
                                   [[Button.inline("✅ Approve", f"ad:ap:{uid}".encode()),
                                     Button.inline("❌ Reject", f"ad:rj:{uid}".encode())]])
                return await show(event, "📩 Request sent. You'll be notified once approved.")

            ok, why = check_access(uid, key)
            if not ok:
                return await show_denied(event, uid, key, why)

            if data.startswith("y:"):  # demo year selection
                yr = data[2:]
                if key != "demo" or yr not in YEAR_CHOICES:
                    return await event.answer("Invalid", alert=True)
                if db["settings"]["demo_year_tier"] == "all" or uid == ADMIN_ID:
                    sess = db["demo_sessions"].setdefault(
                        str(uid), {"started": time.time(), "downloads": 0, "year": None})
                    sess["year"] = yr
                    _write_db(db)
                user_state.pop(uid, None)
                return await show_home(event, uid, key)
            if data == "chy":
                return await show(event, "Select your MBBS year:", year_picker_buttons())
            if data == "home":
                user_state.pop(uid, None)
                return await show_home(event, uid, key)
            if data == "noqb":
                return await event.answer("🔒 MCQ Hub needs the Full plan. Contact " + OWNER_CONTACT, alert=True)
            if data.startswith("s:"):
                return await show_subject(event, uid, key, data[2:])
            if data.startswith("k:"):
                _, kind, subject = data.split(":", 2)
                subjects = get_subjects(key, uid) or (TOPICS_ALL if uid == ADMIN_ID else {})
                if subject not in subjects:
                    return await show_home(event, uid, key)
                user_state[uid] = {"subject": subject, "kind": kind, "tag": None, "page": 0, "q": None}
                return await render_list(event, uid, key)

            st = user_state.get(uid)
            if data.startswith("u:") and st:
                if data == "u:all":
                    st.update(tag=None, q=None, page=0, all=True)
                    return await render_list_all(event, uid, key)
                tags = st.get("tags", [])
                idx = int(data[2:])
                if idx >= len(tags):
                    return await event.answer("Expired, reopen.", alert=True)
                st.update(tag=tags[idx], q=None, page=0, all=False)
                return await render_list(event, uid, key)
            if data.startswith("up:") and st:
                st["upage"] = int(data[3:])
                return await render_list(event, uid, key)
            if data.startswith("p:") and st:
                st["page"] = int(data[2:])
                return await (render_list_all(event, uid, key) if st.get("all") and not st["tag"] and not st["q"]
                              else render_list(event, uid, key))
            if data == "q" and st:
                user_search_state[uid] = True
                return await show(event, "🔍 Type the topic/keyword to search:",
                                  [[Button.inline("⬅️ Cancel", b"ub")]])
            if data == "ub" and st:  # back to units
                st.update(tag=None, q=None, page=0, all=False)
                user_search_state.pop(uid, None)
                return await render_list(event, uid, key)
            if data == "back" and st:
                subj = st["subject"]
                user_state.pop(uid, None)
                user_search_state.pop(uid, None)
                return await (show_home(event, uid, key) if subj == "Notes"
                              else show_subject(event, uid, key, subj))
            if data.startswith("g:"):
                return await deliver(event, uid, key, int(data[2:]))
        except MessageNotModifiedError:
            pass
        except Exception:
            logging.exception("Callback error: %s", data)
            try:
                await event.answer("⚠️ Something went wrong. Send /start", alert=True)
            except Exception:
                pass


async def render_list_all(event, uid, key):
    """Flat list of every item (no unit grouping) when user taps 'All'."""
    st = user_state[uid]
    items = await items_for(st)
    total = len(items)
    p = min(st["page"], max(0, (total - 1) // PAGE_SIZE))
    st["page"] = p
    chunk = items[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
    rows = [[Button.inline(f"▶️ {i['name'][:40]}", f"g:{i['id']}".encode())] for i in chunk]
    nav = []
    if p > 0:
        nav.append(Button.inline("◀️ Prev", f"p:{p - 1}".encode()))
    if (p + 1) * PAGE_SIZE < total:
        nav.append(Button.inline("Next ▶️", f"p:{p + 1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("🔍 Search", b"q"), Button.inline("⬅️ Back", b"ub")])
    await show(event, f"📂 **{esc(st['subject'])}** | All | {total} item(s)", rows)


# ============================================================
# BACKGROUND LOOPS, WEB SERVER, MAIN
# ============================================================

async def sync_loop():
    while True:
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
        try:
            await reconcile_now()
            TOPIC_CACHE.clear()
        except Exception:
            logging.exception("Sync loop error")


async def backup_loop():
    while True:
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
        if db["settings"].get("cloud_backup_enabled"):
            await do_backup()


async def start_web():
    async def health(_):
        return web.json_response({"ok": True, "bots": list(active_bots), "uptime": int(time.time() - START_TIME)})
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Health server on port %s", PORT)


async def main():
    if not API_ID or not API_HASH:
        raise SystemExit("Set API_ID and API_HASH environment variables.")
    await user_client.start()
    await restore_db_from_cloud(merge_local=False)
    await tg_restore_if_needed()

    for key, token in BOT_TOKENS.items():
        if not token:
            continue
        try:
            c = TelegramClient(StringSession(), API_ID, API_HASH)
            await c.start(bot_token=token)
            register(c, key)
            active_bots[key] = c
            logging.info("Bot started: %s", key)
        except Exception:
            logging.exception("Failed to start bot %s", key)
    if not active_bots:
        raise SystemExit("No bot tokens configured (BOT_TOKEN_ALL / Y1 / Y2 / Y3 / FINAL / DEMO / MANAGER).")

    await start_web()
    await reconcile_now()
    asyncio.create_task(sync_loop())
    asyncio.create_task(backup_loop())
    await asyncio.gather(*[c.run_until_disconnected() for c in active_bots.values()])


if __name__ == "__main__":
    asyncio.run(main())
