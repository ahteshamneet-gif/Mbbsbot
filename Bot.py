#!/usr/bin/env python3
# ============================================================
# MBBS Lecture Bot - full single-file version
#  - Approvals/settings persist in Supabase (survive restarts)
#  - Year-wise / paid / demo / everyone broadcast
#  - Student bots (all, year_1..final_year, demo) + manager bot
# ============================================================

import asyncio
import io
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, MessageNotModifiedError
from telethon.sessions import StringSession

# ============================================================
# CONFIGURATION  (set ALL of these as environment variables)
# ============================================================


def _req(name):
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"Missing required environment variable: {name}")
    return v


API_ID = int(_req("API_ID"))
API_HASH = _req("API_HASH")
GROUP_ID = int(_req("GROUP_ID"))
ADMIN_ID = int(_req("ADMIN_ID"))
SUPABASE_URL = _req("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _req("SUPABASE_KEY")                      # publishable key (students table, as before)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()  # service_role key (bot_state table)

PORT = int(os.getenv("PORT", "8080"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")
CBT_WEBAPP_BASE_URL = os.getenv("CBT_WEBAPP_BASE_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/index.html")
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()  # Telethon user-account session string

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
# SUBJECTS & CURRICULUM TOPICS PER YEAR  (forum topic IDs)
# ============================================================

TOPICS_ALL = {
    "Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Microbiology": 5,
    "Pathology": 49, "Pharmacology": 50, "Forensic Medicine and Toxicology": 51,
    "Community Medicine": 52, "General Medicine": 53, "General Surgery": 54,
    "Obstetrics and Gynecology": 55, "Pediatrics": 56, "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58, "Orthopedics": 59, "Anesthesiology": 60,
    "Radiology": 61, "Dermatology": 62, "Psychiatry": 63,
}
TOPICS_Y1 = {"Anatomy": 2, "Physiology": 3, "Biochemistry": 4}
TOPICS_Y2 = {"Pathology": 49, "Pharmacology": 50, "Microbiology": 5}
TOPICS_Y3 = {
    "Community Medicine": 52, "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58, "Forensic Medicine and Toxicology": 51,
}
TOPICS_FINAL = {
    "General Medicine": 53, "General Surgery": 54, "Obstetrics and Gynecology": 55,
    "Pediatrics": 56, "Orthopedics": 59, "Anesthesiology": 60, "Radiology": 61,
    "Dermatology": 62, "Psychiatry": 63,
}

BOT_SUBJECTS_MAP = {
    "all": TOPICS_ALL,
    "year_1": TOPICS_Y1,
    "year_2": TOPICS_Y2,
    "year_3": TOPICS_Y3,
    "final_year": TOPICS_FINAL,
    "demo": TOPICS_ALL,
}

BOT_TITLES_MAP = {
    "all": "MBBS Full Library (All Subjects)",
    "year_1": "MBBS 1st Year Library",
    "year_2": "MBBS 2nd Year Library",
    "year_3": "MBBS 3rd Year Library",
    "final_year": "MBBS 4th / Final Year Library",
    "demo": "MBBS Demo Trial Experience",
}

TIER_LABELS = {
    "all": "All Years", "year_1": "1st Year", "year_2": "2nd Year",
    "year_3": "3rd Year", "final_year": "Final Year",
}
CONTENT_LABELS = {"full": "Lectures + CBT Q-Bank", "lectures_only": "Lectures only"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)

# ============================================================
# DATABASE & SETTINGS STORAGE  (local file + Supabase cloud copy)
# ============================================================

DB_FILE = "bot_database.json"
DEFAULT_SETTINGS = {
    "expiry_enabled": False,
    "tier_access_enabled": False,
    "daily_limit_enabled": False,
    "daily_limit_max": 30,
    "cloud_backup_enabled": True,
    "demo_duration_mins": 10,
    "demo_max_downloads": 2,
    "demo_year_tier": "all",
    "demo_auto_start": True,
}


def _empty_db():
    return {
        "users": {}, "banned": [], "approved": [], "approved_details": {},
        "settings": DEFAULT_SETTINGS.copy(), "daily_downloads": {}, "demo_sessions": {},
    }


def normalize_db(data):
    base = _empty_db()
    if isinstance(data, dict):
        base.update(data)
    if not isinstance(base.get("settings"), dict):
        base["settings"] = {}
    for k, v in DEFAULT_SETTINGS.items():
        base["settings"].setdefault(k, v)
    for key in ("users", "approved_details", "daily_downloads", "demo_sessions"):
        if not isinstance(base.get(key), dict):
            base[key] = {}
    for key in ("banned", "approved"):
        if not isinstance(base.get(key), list):
            base[key] = []
    base["approved"] = [int(x) for x in base["approved"]]
    base["banned"] = [int(x) for x in base["banned"]]
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
                    data["users"].setdefault(uid, val)
                for uid in env.get("approved", []):
                    if int(uid) not in data["approved"]:
                        data["approved"].append(int(uid))
                for uid, val in env.get("approved_details", {}).items():
                    data["approved_details"].setdefault(uid, val)
                logging.info("Merged paid users from PAID_USERS_BACKUP.")
        except Exception:
            logging.exception("Failed parsing PAID_USERS_BACKUP")
    return normalize_db(data)


db = load_db()

# ---------- cloud persistence (Supabase table: bot_state) ----------

_cloud_ok = False            # True only after we have successfully read the cloud copy
_cloud_save_pending = False


def _cloud_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


async def cloud_load_db():
    """Returns (ok, data). ok=False on any error. data=None if no row exists yet."""
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
            async with s.post(f"{SUPABASE_URL}/rest/v1/bot_state?on_conflict=id",
                              headers=headers,
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
    db["approved_details"][str(ADMIN_ID)] = {
        "tier": "all", "content_tier": "full", "expiry": None, "added_at": "SYSTEM",
        **{k: v for k, v in db["approved_details"].get(str(ADMIN_ID), {}).items()
           if k in ("qbank_id", "qbank_pass", "qb_state", "creds_sent")},
    }


def _merge_local_into(cloud):
    """Cloud is the base; add anything that exists only locally (used on late recovery)."""
    local = db
    for uid in local["approved"]:
        if uid not in cloud["approved"]:
            cloud["approved"].append(uid)
            cloud["approved_details"].setdefault(str(uid), local["approved_details"].get(str(uid), {}))
    for uid in local["banned"]:
        if uid not in cloud["banned"]:
            cloud["banned"].append(uid)
    for uid, u in local["users"].items():
        cloud["users"].setdefault(uid, u)
    for uid, s in local["demo_sessions"].items():
        cloud["demo_sessions"].setdefault(uid, s)
    return cloud


async def restore_db_from_cloud(retries=4, merge_local=False):
    """Load the DB from Supabase. Never overwrites the cloud unless the read succeeded."""
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
    logging.error("Could not reach Supabase cloud DB; running on local data only.")
    return False


ensure_admin()
_write_local(db)

# ============================================================
# HELPERS
# ============================================================


def esc(s):
    return re.sub(r"[*_`\[\]]", "", str(s or ""))


def display_name(uid):
    u = db.get("users", {}).get(str(uid), {})
    return (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username") or f"Candidate {uid}")


def fmt_secs(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


# ============================================================
# Q-BANK & DEMO CREDENTIALS LOGIC
# ============================================================

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _pick(n):
    return "".join(secrets.choice(_ALPHA) for _ in range(n))


def get_or_create_qbank_creds(user_id):
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
        _write_db(db)
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


async def supabase_upsert_student(student_id, passkey, name, active=True, expires_at=None, is_demo=False):
    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    row = {
        "student_id": student_id, "student_name": name, "passkey": passkey,
        "is_demo": is_demo, "active": active, "expires_at": expires_at,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(f"{SUPABASE_URL}/rest/v1/students?on_conflict=student_id",
                          headers=headers, data=json.dumps(row)) as r:
            if r.status >= 300:
                raise RuntimeError(f"Supabase {r.status}: {(await r.text())[:200]}")


# ============================================================
# CLIENTS
# ============================================================

user_client = TelegramClient(StringSession(SESSION_STRING) if SESSION_STRING else "session",
                             API_ID, API_HASH)
active_bots = {}
manager_bot_client = None
START_TIME = time.time()

TOPIC_CACHE = {}
TOPIC_LOCKS = {}
TOPIC_CACHE_TTL = 600
ADMIN_STATES = {}


async def send_via_any(chat_id, text, buttons=None, pref=None):
    """Send a DM through whichever student bot can reach this user."""
    if pref is None:
        pref = db.get("users", {}).get(str(chat_id), {}).get("bot_used")
    bots = [active_bots[pref]] if pref in active_bots else []
    bots += [b for k, b in active_bots.items() if k != pref]
    for bot in bots:
        try:
            await bot.send_message(chat_id, text, buttons=buttons)
            return True
        except Exception:
            continue
    return False


async def send_login_card(chat_id, user_id, title="🎉 **Your CBT Q-Bank login is ready!**"):
    qid, pw = get_or_create_qbank_creds(user_id)
    text = (
        f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the interactive CBT app (auto-login).\n"
        "Send /mylogin any time to see this again."
    )
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))]]
    return await send_via_any(chat_id, text, buttons)


# ============================================================
# Q-BANK RECONCILE (keeps Supabase students table in sync)
# ============================================================

_reconcile_lock = None
_reconcile_pending = False


async def reconcile_now():
    """Make Supabase match the bot: Full plan -> login ON; anything else -> OFF."""
    global _reconcile_lock, _reconcile_pending
    _reconcile_pending = False
    if _reconcile_lock is None:
        _reconcile_lock = asyncio.Lock()
    async with _reconcile_lock:
        changed = False
        for s, det in list(db.get("approved_details", {}).items()):
            uid = int(s)
            if uid == ADMIN_ID:
                continue
            full = has_qbank(uid)
            if full and not det.get("qbank_id"):
                get_or_create_qbank_creds(uid)
            if not det.get("qbank_id"):
                continue
            if "creds_sent" not in det:
                det["creds_sent"] = True

            expiry = det.get("expiry")
            expired = False
            if expiry and db["settings"].get("expiry_enabled"):
                try:
                    expired = datetime.now().date() > datetime.strptime(expiry, "%Y-%m-%d").date()
                except Exception:
                    pass

            want = f"on:{expiry}" if (full and not expired) else "off"
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

    async def _go():
        try:
            await reconcile_now()
        except Exception:
            logging.exception("Reconcile failed")

    loop.call_later(1.0, lambda: loop.create_task(_go()))


# ============================================================
# DEMO SESSION ENGINE
# ============================================================


def get_demo_topics():
    tier = db["settings"].get("demo_year_tier", "all")
    return BOT_SUBJECTS_MAP.get(tier, TOPICS_ALL)


def get_or_start_demo_session(user_id):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    if not session:
        session = {
            "start_time": time.time(),
            "duration_mins": db["settings"].get("demo_duration_mins", 10),
            "max_downloads": db["settings"].get("demo_max_downloads", 2),
            "downloads_used": 0,
            "cbt_id": "DEMO-" + _pick(4),
            "cbt_pass": _pick(6),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cbt_synced": False,
        }
        db["demo_sessions"][s_uid] = session
        _write_db(db)
    return session


def check_demo_status(user_id):
    """Returns (status, remaining_secs, downloads_used, downloads_max)."""
    session = db["demo_sessions"].get(str(user_id))
    if not session:
        return "new", 0, 0, 0
    elapsed = time.time() - session["start_time"]
    total = session.get("duration_mins", 10) * 60
    dl_used = session.get("downloads_used", 0)
    dl_max = session.get("max_downloads", 2)
    if elapsed > total:
        return "expired", 0, dl_used, dl_max
    remaining = int(max(0, total - elapsed))
    if dl_used >= dl_max:
        return "download_limit_reached", remaining, dl_used, dl_max
    return "active", remaining, dl_used, dl_max


def record_demo_download(user_id):
    session = db["demo_sessions"].get(str(user_id))
    if session:
        session["downloads_used"] = session.get("downloads_used", 0) + 1
        _write_db(db)


async def ensure_demo_cbt_synced(user_id, name="Demo Student"):
    session = db["demo_sessions"].get(str(user_id))
    if not session or session.get("cbt_synced"):
        return
    try:
        exp = (datetime.utcnow() + timedelta(minutes=session.get("duration_mins", 10) + 60)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")
        await supabase_upsert_student(
            session["cbt_id"], session["cbt_pass"], f"Demo: {name}",
            active=True, expires_at=exp, is_demo=True)
        session["cbt_synced"] = True
        _write_db(db)
    except Exception as e:
        logging.warning("Could not sync demo CBT user %s: %s", user_id, e)


# ============================================================
# USER TRACKING & ACCESS CONTROL
# ============================================================


def track_user(user, bot_type):
    if not user:
        return
    uid = str(user.id)
    new = {
        "first_name": getattr(user, "first_name", "") or "",
        "last_name": getattr(user, "last_name", "") or "",
        "username": getattr(user, "username", "") or "",
        "bot_used": bot_type,
    }
    cur = db["users"].get(uid)
    if cur is None:
        new["joined_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db["users"][uid] = new
        save_db(db)
    elif any(cur.get(k) != v for k, v in new.items()):
        cur.update(new)
        save_db(db)


def is_banned(user_id):
    return int(user_id) in db.get("banned", [])


def check_access(user_id, bot_type):
    """Approvals are NEVER removed here; expiry only blocks access (record is kept)."""
    uid = int(user_id)
    if uid == ADMIN_ID:
        return True, "admin"
    if uid not in db.get("approved", []):
        return False, "not_approved"
    details = db.get("approved_details", {}).get(str(uid), {})

    if db["settings"].get("expiry_enabled", False):
        expiry_str = details.get("expiry")
        if expiry_str:
            try:
                if datetime.now().date() > datetime.strptime(expiry_str, "%Y-%m-%d").date():
                    return False, "expired"
            except Exception:
                pass

    if db["settings"].get("tier_access_enabled", False):
        user_tier = details.get("tier", "all")
        if user_tier != "all" and user_tier != bot_type and bot_type != "demo":
            return False, f"tier_mismatch:{user_tier}"
    return True, "allowed"


def check_daily_limit(user_id):
    uid = int(user_id)
    if uid == ADMIN_ID:
        return True, 0, 9999
    if not db["settings"].get("daily_limit_enabled", False):
        return True, 0, 0
    today = datetime.now().strftime("%Y-%m-%d")
    count = db["daily_downloads"].setdefault(today, {}).get(str(uid), 0)
    max_limit = db["settings"].get("daily_limit_max", 30)
    return (count < max_limit), count, max_limit


def record_download(user_id):
    if int(user_id) == ADMIN_ID:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    for day in [d for d in db["daily_downloads"] if d < cutoff]:
        db["daily_downloads"].pop(day, None)
    day_map = db["daily_downloads"].setdefault(today, {})
    day_map[str(user_id)] = day_map.get(str(user_id), 0) + 1
    _write_db(db)


def approve_user(uid, tier="all", content_tier="full", days=0):
    uid = int(uid)
    if uid not in db["approved"]:
        db["approved"].append(uid)
    if uid in db["banned"]:
        db["banned"].remove(uid)
    det = db["approved_details"].setdefault(str(uid), {})
    det["tier"] = tier
    det["content_tier"] = content_tier
    det["expiry"] = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d") if days else None
    det["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if content_tier == "full":
        get_or_create_qbank_creds(uid)
    save_db(db)
    return det


LOCKED_MESSAGE = (
    "🔒 **Access Restricted**\n\n"
    "This is a verified educational bot. Limited users have access to these resources.\n"
    f"To enroll or activate your subscription, contact {OWNER_CONTACT}\n\n"
    "Send your **User ID** to get verified:\n`{user_id}`"
)

# ============================================================
# LECTURE LISTING (via user account) + DELIVERY (via bots)
# ============================================================


def lecture_title(msg):
    t = (msg.message or "").strip().split("\n")[0].strip()
    if not t and msg.file and msg.file.name:
        t = msg.file.name
    return (t or f"Lecture {msg.id}")[:60]


async def get_topic_items(topic_id, force=False):
    c = TOPIC_CACHE.get(topic_id)
    if c and not force and time.time() - c[0] < TOPIC_CACHE_TTL:
        return c[1]
    lock = TOPIC_LOCKS.setdefault(topic_id, asyncio.Lock())
    async with lock:
        c = TOPIC_CACHE.get(topic_id)
        if c and not force and time.time() - c[0] < TOPIC_CACHE_TTL:
            return c[1]
        try:
            items = []
            async for m in user_client.iter_messages(GROUP_ID, reply_to=topic_id, reverse=True, limit=2000):
                if m.document:
                    items.append({"id": m.id, "title": lecture_title(m)})
            TOPIC_CACHE[topic_id] = (time.time(), items)
            return items
        except Exception:
            logging.exception("Listing topic %s failed", topic_id)
            if c:
                return c[1]
            raise


# ============================================================
# STUDENT BOT HANDLERS
# ============================================================

PAGE_SIZE = 8


def register_student_handlers(bot, bot_type):
    is_demo = bot_type == "demo"

    def topics_for():
        return get_demo_topics() if is_demo else BOT_SUBJECTS_MAP.get(bot_type, TOPICS_ALL)

    async def reply(event, text, buttons=None):
        if isinstance(event, events.CallbackQuery.Event):
            try:
                await event.edit(text, buttons=buttons)
            except MessageNotModifiedError:
                pass
            except Exception:
                await bot.send_message(event.sender_id, text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)

    async def gate(event):
        uid = event.sender_id
        if uid != ADMIN_ID:
            try:
                track_user(await event.get_sender(), bot_type)
            except Exception:
                pass
        if is_banned(uid):
            await reply(event, f"🚫 **You are banned from this bot.**\nContact {OWNER_CONTACT}.")
            return False
        if is_demo or uid == ADMIN_ID:
            return True
        ok, reason = check_access(uid, bot_type)
        if ok:
            return True
        if reason == "expired":
            await reply(event, f"⏰ **Your subscription has expired.**\nContact {OWNER_CONTACT} to renew.\n\nYour ID: `{uid}`")
        elif reason.startswith("tier_mismatch:"):
            tier = reason.split(":", 1)[1]
            await reply(event, f"⚠️ Your plan is **{TIER_LABELS.get(tier, tier)}**. "
                               "Please use the bot for your own year.")
        else:
            await reply(event, LOCKED_MESSAGE.format(user_id=uid))
        return False

    def demo_header(uid):
        st, rem, used, mx = check_demo_status(uid)
        return f"⏱ **{fmt_secs(rem)}** left  |  📥 Downloads **{used}/{mx}**"

    async def home_view(uid):
        name = esc(display_name(uid))
        buttons = [[Button.inline("📚 Browse Lectures", b"lib")]]
        if is_demo and uid != ADMIN_ID:
            session = get_or_start_demo_session(uid)
            await ensure_demo_cbt_synced(uid, name)
            text = (f"👋 Welcome, **{name}**!\n📖 **{BOT_TITLES_MAP['demo']}**\n\n"
                    f"{demo_header(uid)}\n\n"
                    "Try our lectures and CBT Q-Bank for a few minutes.")
            buttons.append([Button.url("🌐 Try CBT Q-Bank (Demo)",
                                       generate_demo_webapp_url(session["cbt_id"], session["cbt_pass"]))])
        else:
            det = db["approved_details"].get(str(uid), {})
            exp = det.get("expiry")
            text = (f"👋 Welcome, **{name}**!\n📖 **{BOT_TITLES_MAP.get(bot_type, 'MBBS Library')}**\n\n"
                    f"💎 Plan: **{TIER_LABELS.get(det.get('tier', 'all'), 'All Years')}** · "
                    f"{CONTENT_LABELS.get(det.get('content_tier', 'full'), 'Lectures only')}\n"
                    f"📅 Valid till: **{exp or 'Lifetime'}**")
            if uid == ADMIN_ID or has_qbank(uid):
                buttons.append([Button.url("🌐 Open CBT Q-Bank", generate_webapp_launch_url(uid))])
        return text, buttons

    async def show_home(event):
        uid = event.sender_id
        if is_demo and uid != ADMIN_ID:
            st = check_demo_status(uid)[0]
            if st == "new" and not db["settings"].get("demo_auto_start", True):
                m = db["settings"].get("demo_duration_mins", 10)
                n = db["settings"].get("demo_max_downloads", 2)
                await reply(event, f"🧪 **Free Demo**\n\n⏱ {m} minutes · 📥 {n} lecture downloads\n\n"
                                   "Tap below to start. The timer begins immediately.",
                            [[Button.inline("▶️ Start Free Demo", b"demo:start")]])
                return
            if st == "expired":
                await reply(event, f"⏰ **Your demo has ended.**\n\nGet full access: {OWNER_CONTACT}\n"
                                   f"Your ID: `{uid}`")
                return
        text, buttons = await home_view(uid)
        await reply(event, text, buttons)

    async def show_subjects(event):
        uid = event.sender_id
        if is_demo and uid != ADMIN_ID and check_demo_status(uid)[0] == "expired":
            return await show_home(event)
        items = list(topics_for().items())
        rows = []
        for i in range(0, len(items), 2):
            rows.append([Button.inline(f"📘 {n}", f"t:{tid}:0") for n, tid in items[i:i + 2]])
        rows.append([Button.inline("🏠 Home", b"home")])
        head = "📚 **Select a subject:**"
        if is_demo and uid != ADMIN_ID:
            head += f"\n\n{demo_header(uid)}"
        await reply(event, head, rows)

    async def show_lectures(event, tid, page):
        uid = event.sender_id
        if tid not in topics_for().values():
            return
        if is_demo and uid != ADMIN_ID and check_demo_status(uid)[0] == "expired":
            return await show_home(event)
        try:
            items = await get_topic_items(tid)
        except Exception:
            await reply(event, "⚠️ Could not load lectures right now. Please try again shortly.",
                        [[Button.inline("⬅️ Back", b"lib")]])
            return
        subject = next((n for n, t in topics_for().items() if t == tid), "Subject")
        if not items:
            await reply(event, f"📘 **{subject}**\n\nNo lectures uploaded yet.", [[Button.inline("⬅️ Back", b"lib")]])
            return
        pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(0, min(page, pages - 1))
        chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        rows = [[Button.inline(f"🎬 {it['title'][:45]}", f"d:{tid}:{it['id']}")] for it in chunk]
        nav = []
        if page > 0:
            nav.append(Button.inline("⬅️ Prev", f"t:{tid}:{page - 1}"))
        nav.append(Button.inline(f"{page + 1}/{pages}", b"noop"))
        if page < pages - 1:
            nav.append(Button.inline("Next ➡️", f"t:{tid}:{page + 1}"))
        rows.append(nav)
        rows.append([Button.inline("⬅️ Subjects", b"lib"), Button.inline("🏠 Home", b"home")])
        head = f"📘 **{esc(subject)}** — {len(items)} lectures"
        if is_demo and uid != ADMIN_ID:
            head += f"\n{demo_header(uid)}"
        await reply(event, head, rows)

    async def send_lecture(event, tid, mid):
        uid = event.sender_id
        if tid not in topics_for().values():
            return
        # limits
        if is_demo and uid != ADMIN_ID:
            st, rem, used, mx = check_demo_status(uid)
            if st == "expired":
                return await show_home(event)
            if st == "download_limit_reached":
                await bot.send_message(uid, f"📥 Demo download limit reached ({used}/{mx}).\n"
                                            f"Get full access: {OWNER_CONTACT}")
                return
        elif uid != ADMIN_ID:
            ok, count, mx = check_daily_limit(uid)
            if not ok:
                await bot.send_message(uid, f"📥 Daily limit reached ({count}/{mx}). Try again tomorrow.")
                return
        # only allow messages that are really in this subject's topic
        try:
            items = await get_topic_items(tid)
        except Exception:
            await bot.send_message(uid, "⚠️ Could not load that lecture. Try again.")
            return
        entry = next((i for i in items if i["id"] == mid), None)
        if not entry:
            await bot.send_message(uid, "⚠️ Lecture not found (list may have updated). Reopen the subject.")
            return

        wait = await bot.send_message(uid, "📤 Sending your lecture…")
        sent = False
        try:
            msg = await bot.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                await bot.send_file(uid, msg.media, caption=f"🎬 {esc(entry['title'])}")
                sent = True
        except FloodWaitError as e:
            await asyncio.sleep(min(e.seconds, 30) + 1)
        except Exception:
            logging.warning("send_file failed for %s, trying forward", mid)
        if not sent:
            try:
                await bot.forward_messages(uid, mid, GROUP_ID)
                sent = True
            except Exception:
                logging.exception("Forward failed for %s", mid)
        try:
            await wait.delete()
        except Exception:
            pass
        if not sent:
            await bot.send_message(uid, "⚠️ Could not send this lecture. Please contact " + OWNER_CONTACT)
            return
        if is_demo and uid != ADMIN_ID:
            record_demo_download(uid)
            await bot.send_message(uid, f"✅ Sent!  {demo_header(uid)}")
        else:
            record_download(uid)

    # ---------------- message handlers ----------------

    @bot.on(events.NewMessage(pattern=r"^/start", incoming=True, func=lambda e: e.is_private))
    async def on_start(event):
        if not await gate(event):
            return
        if is_demo and event.sender_id != ADMIN_ID and db["settings"].get("demo_auto_start", True):
            get_or_start_demo_session(event.sender_id)
        await show_home(event)

    @bot.on(events.NewMessage(pattern=r"^/(help|menu)", incoming=True, func=lambda e: e.is_private))
    async def on_help(event):
        if not await gate(event):
            return
        await event.respond("**Commands**\n/start – home\n/mylogin – CBT Q-Bank login\n"
                            "/status – your plan\n/myid – your Telegram ID\n\n"
                            f"Support: {OWNER_CONTACT}")

    @bot.on(events.NewMessage(pattern=r"^/myid", incoming=True, func=lambda e: e.is_private))
    async def on_myid(event):
        await event.respond(f"🆔 Your Telegram ID: `{event.sender_id}`")

    @bot.on(events.NewMessage(pattern=r"^/status", incoming=True, func=lambda e: e.is_private))
    async def on_status(event):
        if not await gate(event):
            return
        uid = event.sender_id
        if is_demo and uid != ADMIN_ID:
            st = check_demo_status(uid)[0]
            await event.respond(f"🧪 Demo status: **{st}**\n{demo_header(uid)}")
            return
        det = db["approved_details"].get(str(uid), {})
        await event.respond(
            f"💎 **Your plan**\nYear: **{TIER_LABELS.get(det.get('tier', 'all'), 'All Years')}**\n"
            f"Content: **{CONTENT_LABELS.get(det.get('content_tier', 'full'), 'Lectures only')}**\n"
            f"Valid till: **{det.get('expiry') or 'Lifetime'}**")

    @bot.on(events.NewMessage(pattern=r"^/mylogin", incoming=True, func=lambda e: e.is_private))
    async def on_mylogin(event):
        if not await gate(event):
            return
        uid = event.sender_id
        if is_demo and uid != ADMIN_ID:
            s = get_or_start_demo_session(uid)
            await ensure_demo_cbt_synced(uid, esc(display_name(uid)))
            await event.respond(
                f"🧪 **Demo CBT login**\n🆔 `{s['cbt_id']}`\n🔑 `{s['cbt_pass']}`",
                buttons=[[Button.url("🌐 Open Demo CBT", generate_demo_webapp_url(s['cbt_id'], s['cbt_pass']))]])
        elif uid == ADMIN_ID:
            await event.respond("Admin link:", buttons=[[Button.url("🌐 Open CBT", CBT_WEBAPP_BASE_URL)]])
        elif has_qbank(uid):
            await send_login_card(uid, uid)
        else:
            await event.respond(f"Your plan is **lectures only**. For the CBT Q-Bank contact {OWNER_CONTACT}.")

    @bot.on(events.CallbackQuery)
    async def on_cb(event):
        data = event.data.decode(errors="ignore")
        uid = event.sender_id
        try:
            await event.answer()
        except Exception:
            pass
        if data == "noop":
            return
        if not await gate(event):
            return
        if data == "demo:start" and is_demo:
            get_or_start_demo_session(uid)
            return await show_home(event)
        if data == "home":
            return await show_home(event)
        if data == "lib":
            return await show_subjects(event)
        m = re.match(r"^t:(\d+):(\d+)$", data)
        if m:
            return await show_lectures(event, int(m.group(1)), int(m.group(2)))
        m = re.match(r"^d:(\d+):(\d+)$", data)
        if m:
            return await send_lecture(event, int(m.group(1)), int(m.group(2)))


# ============================================================
# BROADCAST HELPERS
# ============================================================

BROADCAST_TARGETS = [
    ("everyone", "👥 Everyone"), ("paid", "💎 All Paid"),
    ("year_1", "1️⃣ 1st Year"), ("year_2", "2️⃣ 2nd Year"),
    ("year_3", "3️⃣ 3rd Year"), ("final_year", "🎓 Final Year"),
    ("demo", "🧪 Demo Users"),
]


def get_broadcast_audience(target):
    ids = set()
    if target == "everyone":
        ids = {int(u) for u in db["users"]}
    elif target == "paid":
        ids = {int(u) for u in db["approved"]}
    elif target == "demo":
        ids = {int(u) for u in db["demo_sessions"]}
    else:  # a specific year: paid users on that year (or on 'all') + users of that year's bot
        for uid in db["approved"]:
            tier = db["approved_details"].get(str(uid), {}).get("tier", "all")
            if tier in (target, "all"):
                ids.add(int(uid))
        for u, info in db["users"].items():
            if info.get("bot_used") == target:
                ids.add(int(u))
    ids -= set(db["banned"])
    ids.discard(ADMIN_ID)
    return sorted(ids)


async def send_broadcast_one(uid, text, entities, media_bytes, media_name):
    pref = db["users"].get(str(uid), {}).get("bot_used")
    bots = [active_bots[pref]] if pref in active_bots else []
    bots += [b for k, b in active_bots.items() if k != pref]
    for bot in bots:
        for _ in range(2):
            try:
                if media_bytes:
                    f = io.BytesIO(media_bytes)
                    f.name = media_name or "file"
                    await bot.send_file(uid, f, caption=text or None, formatting_entities=entities or None)
                else:
                    await bot.send_message(uid, text, formatting_entities=entities or None)
                return True
            except FloodWaitError as e:
                await asyncio.sleep(min(e.seconds, 60) + 1)
            except Exception:
                break
    return False


async def do_broadcast(target, text, entities, media_bytes, media_name):
    audience = get_broadcast_audience(target)
    sent = failed = 0
    for uid in audience:
        if await send_broadcast_one(uid, text, entities, media_bytes, media_name):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.06)
    label = dict(BROADCAST_TARGETS).get(target, target)
    try:
        await manager_bot_client.send_message(
            ADMIN_ID, f"📢 **Broadcast finished** ({label})\n✅ Sent: {sent}\n❌ Failed: {failed}\n"
                      f"(Failed = user blocked the bot or never started it)")
    except Exception:
        pass


# ============================================================
# MANAGER (ADMIN) BOT
# ============================================================


def panel_buttons():
    return [
        [Button.inline("➕ Approve", b"m:approve"), Button.inline("➖ Remove", b"m:remove")],
        [Button.inline("🚫 Ban", b"m:ban"), Button.inline("✅ Unban", b"m:unban")],
        [Button.inline("📋 Paid Users", b"m:paid"), Button.inline("📊 Stats", b"m:stats")],
        [Button.inline("📢 Broadcast", b"m:bc"), Button.inline("⚙️ Settings", b"m:set")],
        [Button.inline("🧪 Demo Settings", b"m:demo"), Button.inline("☁️ Backup Now", b"m:backup")],
    ]


PANEL_TEXT = ("🛠 **Admin Panel**\n\n"
              "Shortcuts:\n`/approve <id> <tier> <full|lectures> <days>`\n"
              "`/remove <id>` · `/ban <id>` · `/unban <id>`\n"
              "`/extend <id> <days>` · `/user <id>`\n"
              "tier = all, year_1, year_2, year_3, final_year (days 0 = lifetime)\n"
              "To restore: send a backup .json with caption `/restore`")


def settings_view():
    s = db["settings"]
    toggles = [("expiry_enabled", "Expiry check"), ("tier_access_enabled", "Year-wise bot access"),
               ("daily_limit_enabled", "Daily download limit"), ("cloud_backup_enabled", "Telegram auto-backup")]
    rows = [[Button.inline(f"{lbl}: {'✅ ON' if s.get(k) else '❌ OFF'}", f"tg:{k}")] for k, lbl in toggles]
    cur = s.get("daily_limit_max", 30)
    rows.append([Button.inline(("• " if cur == n else "") + f"{n}/day", f"lim:{n}") for n in (10, 20, 30, 50)])
    rows.append([Button.inline("⬅️ Panel", b"m:home")])
    return "⚙️ **Settings**\n(Daily limit applies only when enabled)", rows


def demo_view():
    s = db["settings"]
    rows = [
        [Button.inline(("• " if s["demo_duration_mins"] == n else "") + f"{n} min", f"dd:{n}") for n in (5, 7, 10)],
        [Button.inline(("• " if s["demo_max_downloads"] == n else "") + f"{n} downloads", f"dm:{n}") for n in (1, 2, 3)],
        [Button.inline(("• " if s["demo_year_tier"] == t else "") + TIER_LABELS[t], f"dy:{t}")
         for t in ("all", "year_1", "year_2")],
        [Button.inline(("• " if s["demo_year_tier"] == t else "") + TIER_LABELS[t], f"dy:{t}")
         for t in ("year_3", "final_year")],
        [Button.inline(f"Auto-start: {'✅ ON' if s.get('demo_auto_start') else '❌ OFF'}", b"tg:demo_auto_start")],
        [Button.inline("⬅️ Panel", b"m:home")],
    ]
    return ("🧪 **Demo Settings**\n"
            f"Duration: {s['demo_duration_mins']} min · Downloads: {s['demo_max_downloads']} · "
            f"Library: {TIER_LABELS[s['demo_year_tier']]}\n(Applies to new demo sessions)"), rows


def user_info_text(uid):
    uid = int(uid)
    det = db["approved_details"].get(str(uid), {})
    status = "💎 Approved" if uid in db["approved"] else "⛔ Not approved"
    if uid in db["banned"]:
        status = "🚫 Banned"
    t = (f"👤 **{esc(display_name(uid))}** (`{uid}`)\n{status}\n"
         f"Year: {TIER_LABELS.get(det.get('tier', ''), '-')} · "
         f"Content: {CONTENT_LABELS.get(det.get('content_tier', ''), '-')}\n"
         f"Expiry: {det.get('expiry') or 'Lifetime'}\nAdded: {det.get('added_at', '-')}")
    if det.get("qbank_id"):
        t += f"\nQ-Bank: `{det['qbank_id']}` / `{det.get('qbank_pass')}` ({det.get('qb_state')})"
    return t


def register_manager_handlers(bot):
    def tier_buttons():
        rows = [[Button.inline(TIER_LABELS[t], f"ap_t:{t}")] for t in TIER_LABELS]
        return rows

    async def finish_approve(uid, tier, content, days):
        approve_user(uid, tier, content, days)
        note = (f"✅ **Subscription activated!**\nYear: **{TIER_LABELS.get(tier)}** · "
                f"**{CONTENT_LABELS.get(content)}**\nValid: **{'Lifetime' if not days else f'{days} days'}**\n"
                "Send /start to begin.")
        delivered = await send_via_any(uid, note)
        extra = "" if delivered else "\n⚠️ Could not DM the user (they must /start a bot first)."
        if content == "full":
            extra += "\n🔑 Q-Bank login will be sent automatically."
        return (f"✅ Approved `{uid}` — {TIER_LABELS.get(tier)} · {CONTENT_LABELS.get(content)} · "
                f"{'Lifetime' if not days else f'{days} days'}{extra}")

    @bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_msg(event):
        uid = event.sender_id
        if uid != ADMIN_ID:
            await event.respond("🔒 This is the private manager bot.")
            return
        text = (event.raw_text or "").strip()

        # ----- restore from backup file -----
        if event.document and (event.raw_text or "").strip().lower().startswith("/restore"):
            try:
                raw = await event.download_media(file=bytes)
                new = normalize_db(json.loads(raw.decode("utf-8")))
                db.clear()
                db.update(new)
                ensure_admin()
                _write_db(db)
                schedule_reconcile()
                await event.respond(f"✅ Restored: {len(db['users'])} users, {len(db['approved'])} paid.")
            except Exception as e:
                await event.respond(f"❌ Restore failed: {e}")
            return

        # ----- commands -----
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower().split("@")[0]
            ADMIN_STATES.pop(ADMIN_ID, None)
            if cmd in ("/start", "/panel", "/menu"):
                return await event.respond(PANEL_TEXT, buttons=panel_buttons())
            try:
                if cmd == "/approve":
                    target = int(parts[1])
                    tier = parts[2] if len(parts) > 2 else "all"
                    content = "lectures_only" if (len(parts) > 3 and parts[3].lower().startswith("l")) else "full"
                    days = int(parts[4]) if len(parts) > 4 else 0
                    if tier not in TIER_LABELS:
                        return await event.respond("Tier must be: " + ", ".join(TIER_LABELS))
                    return await event.respond(await finish_approve(target, tier, content, days))
                if cmd == "/remove":
                    target = int(parts[1])
                    if target in db["approved"] and target != ADMIN_ID:
                        db["approved"].remove(target)
                        save_db(db)
                        return await event.respond(f"➖ Removed `{target}` (record kept, can re-approve).")
                    return await event.respond("User is not approved.")
                if cmd == "/ban":
                    target = int(parts[1])
                    if target != ADMIN_ID and target not in db["banned"]:
                        db["banned"].append(target)
                        save_db(db)
                    return await event.respond(f"🚫 Banned `{target}`")
                if cmd == "/unban":
                    target = int(parts[1])
                    if target in db["banned"]:
                        db["banned"].remove(target)
                        save_db(db)
                    return await event.respond(f"✅ Unbanned `{target}`")
                if cmd == "/extend":
                    target, days = int(parts[1]), int(parts[2])
                    det = db["approved_details"].setdefault(str(target), {})
                    base = datetime.now().date()
                    if det.get("expiry"):
                        try:
                            base = max(base, datetime.strptime(det["expiry"], "%Y-%m-%d").date())
                        except Exception:
                            pass
                    det["expiry"] = (base + timedelta(days=days)).strftime("%Y-%m-%d")
                    if target not in db["approved"]:
                        db["approved"].append(target)
                    save_db(db)
                    return await event.respond(f"📅 `{target}` now valid till **{det['expiry']}**")
                if cmd == "/user":
                    return await event.respond(user_info_text(int(parts[1])))
                if cmd == "/backup":
                    await trigger_cloud_backup(force=True)
                    return
            except (IndexError, ValueError):
                return await event.respond("⚠️ Wrong format. Send /start to see the examples.")
            return await event.respond("Unknown command. Send /start.")

        # ----- state-driven input -----
        st = ADMIN_STATES.get(ADMIN_ID)
        if not st:
            return await event.respond(PANEL_TEXT, buttons=panel_buttons())
        step = st["step"]

        if step in ("ap_id", "remove", "ban", "unban"):
            m = re.search(r"\d{5,}", text)
            if not m:
                return await event.respond("Please send a valid numeric Telegram ID.")
            target = int(m.group())
            if step == "ap_id":
                st.update(step="ap_tier", uid=target)
                return await event.respond(f"Approve `{target}` — choose the **year**:", buttons=tier_buttons())
            ADMIN_STATES.pop(ADMIN_ID, None)
            if step == "remove":
                if target in db["approved"] and target != ADMIN_ID:
                    db["approved"].remove(target)
                    save_db(db)
                    return await event.respond(f"➖ Removed `{target}`", buttons=panel_buttons())
                return await event.respond("User is not approved.", buttons=panel_buttons())
            if step == "ban":
                if target != ADMIN_ID and target not in db["banned"]:
                    db["banned"].append(target)
                    save_db(db)
                return await event.respond(f"🚫 Banned `{target}`", buttons=panel_buttons())
            if target in db["banned"]:
                db["banned"].remove(target)
                save_db(db)
            return await event.respond(f"✅ Unbanned `{target}`", buttons=panel_buttons())

        if step == "bc_msg":
            media_bytes, media_name = None, None
            if event.media:
                if event.file and event.file.size and event.file.size > 20 * 1024 * 1024:
                    return await event.respond("⚠️ Media too large (max 20 MB). Send text or a smaller file.")
                media_bytes = await event.download_media(file=bytes)
                media_name = (event.file.name if event.file and event.file.name else
                              ("photo.jpg" if event.photo else "file"))
            if not text and not media_bytes:
                return await event.respond("Send the text (or photo/file with caption) to broadcast.")
            st.update(step="bc_confirm", text=text, entities=event.message.entities,
                      media=media_bytes, media_name=media_name)
            count = len(get_broadcast_audience(st["target"]))
            label = dict(BROADCAST_TARGETS)[st["target"]]
            return await event.respond(
                f"📢 **Confirm broadcast**\nAudience: **{label}** — **{count}** users\n\n"
                "Send it?", buttons=[[Button.inline("✅ Send now", b"bc_go"), Button.inline("❌ Cancel", b"bc_no")]])

    @bot.on(events.CallbackQuery)
    async def on_cb(event):
        if event.sender_id != ADMIN_ID:
            return await event.answer("Not allowed", alert=True)
        data = event.data.decode(errors="ignore")
        try:
            await event.answer()
        except Exception:
            pass

        async def show(text, buttons=None):
            try:
                await event.edit(text, buttons=buttons)
            except MessageNotModifiedError:
                pass

        if data == "m:home":
            ADMIN_STATES.pop(ADMIN_ID, None)
            return await show(PANEL_TEXT, panel_buttons())
        if data in ("m:approve", "m:remove", "m:ban", "m:unban"):
            step = {"m:approve": "ap_id", "m:remove": "remove", "m:ban": "ban", "m:unban": "unban"}[data]
            ADMIN_STATES[ADMIN_ID] = {"step": step}
            return await show("Send the user's **Telegram ID** (numeric):", [[Button.inline("⬅️ Cancel", b"m:home")]])

        if data.startswith("ap_t:"):
            st = ADMIN_STATES.get(ADMIN_ID)
            if not st or "uid" not in st:
                return
            st["tier"] = data.split(":", 1)[1]
            return await show(f"`{st['uid']}` · {TIER_LABELS[st['tier']]}\nChoose **content**:", [
                [Button.inline("📚 Lectures + CBT Q-Bank", b"ap_c:full")],
                [Button.inline("🎬 Lectures only", b"ap_c:lectures_only")]])
        if data.startswith("ap_c:"):
            st = ADMIN_STATES.get(ADMIN_ID)
            if not st or "tier" not in st:
                return
            st["content"] = data.split(":", 1)[1]
            return await show("Choose **duration**:", [
                [Button.inline("30 days", b"ap_d:30"), Button.inline("90 days", b"ap_d:90")],
                [Button.inline("180 days", b"ap_d:180"), Button.inline("365 days", b"ap_d:365")],
                [Button.inline("♾ Lifetime", b"ap_d:0")]])
        if data.startswith("ap_d:"):
            st = ADMIN_STATES.pop(ADMIN_ID, None)
            if not st or "content" not in st:
                return
            msg = await finish_approve(st["uid"], st["tier"], st["content"], int(data.split(":", 1)[1]))
            return await show(msg, panel_buttons())

        if data == "m:paid":
            lines = []
            for uid in db["approved"]:
                if uid == ADMIN_ID:
                    continue
                d = db["approved_details"].get(str(uid), {})
                lines.append(f"{uid} | {esc(display_name(uid))} | {d.get('tier', '-')} | "
                             f"{'full' if d.get('content_tier') == 'full' else 'lec'} | {d.get('expiry') or 'life'}")
            if not lines:
                return await show("No paid users yet.", [[Button.inline("⬅️ Panel", b"m:home")]])
            await show(f"📋 **Paid users: {len(lines)}** (id | name | year | plan | expiry)",
                       [[Button.inline("⬅️ Panel", b"m:home")]])
            chunk = ""
            for ln in lines:
                if len(chunk) + len(ln) > 3500:
                    await bot.send_message(ADMIN_ID, chunk, parse_mode=None)
                    chunk = ""
                chunk += ln + "\n"
            if chunk:
                await bot.send_message(ADMIN_ID, chunk, parse_mode=None)
            return

        if data == "m:stats":
            tiers = {}
            for uid in db["approved"]:
                if uid != ADMIN_ID:
                    t = db["approved_details"].get(str(uid), {}).get("tier", "all")
                    tiers[t] = tiers.get(t, 0) + 1
            today = datetime.now().strftime("%Y-%m-%d")
            dl = sum(db["daily_downloads"].get(today, {}).values())
            tier_txt = "\n".join(f"  • {TIER_LABELS.get(k, k)}: {v}" for k, v in tiers.items()) or "  –"
            up = int(time.time() - START_TIME)
            return await show(
                f"📊 **Stats**\n👥 Users: {len(db['users'])}\n💎 Paid: {max(0, len(db['approved']) - 1)}\n{tier_txt}\n"
                f"🚫 Banned: {len(db['banned'])}\n🧪 Demo trials: {len(db['demo_sessions'])}\n"
                f"📥 Downloads today: {dl}\n☁️ Cloud DB: {'✅ connected' if _cloud_ok else '❌ not connected'}\n"
                f"⏱ Uptime: {up // 3600}h {(up % 3600) // 60}m",
                [[Button.inline("⬅️ Panel", b"m:home")]])

        if data == "m:set":
            return await show(*settings_view())
        if data.startswith("tg:"):
            key = data.split(":", 1)[1]
            if key in DEFAULT_SETTINGS and isinstance(DEFAULT_SETTINGS[key], bool):
                db["settings"][key] = not db["settings"].get(key, False)
                save_db(db)
            return await show(*(demo_view() if key == "demo_auto_start" else settings_view()))
        if data.startswith("lim:"):
            db["settings"]["daily_limit_max"] = int(data.split(":", 1)[1])
            save_db(db)
            return await show(*settings_view())

        if data == "m:demo":
            return await show(*demo_view())
        if data.startswith("dd:"):
            db["settings"]["demo_duration_mins"] = int(data.split(":", 1)[1])
            save_db(db)
            return await show(*demo_view())
        if data.startswith("dm:"):
            db["settings"]["demo_max_downloads"] = int(data.split(":", 1)[1])
            save_db(db)
            return await show(*demo_view())
        if data.startswith("dy:"):
            t = data.split(":", 1)[1]
            if t in TIER_LABELS:
                db["settings"]["demo_year_tier"] = t
                save_db(db)
            return await show(*demo_view())

        if data == "m:backup":
            await trigger_cloud_backup(force=True)
            return

        if data == "m:bc":
            rows = []
            for i in range(0, len(BROADCAST_TARGETS), 2):
                rows.append([Button.inline(f"{lbl} ({len(get_broadcast_audience(k))})", f"bc_t:{k}")
                             for k, lbl in BROADCAST_TARGETS[i:i + 2]])
            rows.append([Button.inline("⬅️ Panel", b"m:home")])
            return await show("📢 **Broadcast** — choose the audience:", rows)
        if data.startswith("bc_t:"):
            target = data.split(":", 1)[1]
            ADMIN_STATES[ADMIN_ID] = {"step": "bc_msg", "target": target}
            return await show(f"Audience: **{dict(BROADCAST_TARGETS).get(target, target)}**\n\n"
                              "Now send the message (text, or a photo/file with caption).",
                              [[Button.inline("⬅️ Cancel", b"m:home")]])
        if data == "bc_no":
            ADMIN_STATES.pop(ADMIN_ID, None)
            return await show("Broadcast cancelled.", panel_buttons())
        if data == "bc_go":
            st = ADMIN_STATES.pop(ADMIN_ID, None)
            if not st or st.get("step") != "bc_confirm":
                return
            asyncio.create_task(do_broadcast(st["target"], st["text"], st["entities"], st["media"], st["media_name"]))
            return await show("📤 Broadcast started. You'll get a report when it finishes.", panel_buttons())


# ============================================================
# TELEGRAM BACKUP (extra safety copy sent to admin)
# ============================================================


async def trigger_cloud_backup(force=False):
    if not manager_bot_client or not (force or db["settings"].get("cloud_backup_enabled", True)):
        return
    try:
        _write_local(db)
        if os.path.exists(DB_FILE):
            await manager_bot_client.send_file(
                ADMIN_ID, DB_FILE,
                caption=("☁️ **Backup**\n"
                         f"📅 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                         f"👥 Registered: `{len(db.get('users', {}))}` | 💎 Paid: `{len(db.get('approved', []))}`\n"
                         f"🧪 Demo: `{len(db.get('demo_sessions', {}))}`\n"
                         "To restore: send this file back with caption `/restore`"))
    except Exception:
        logging.exception("Backup failed")


# ============================================================
# BACKGROUND TASKS & WEB SERVER
# ============================================================


async def sync_loop():
    while True:
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
        try:
            if SUPABASE_SERVICE_KEY and not _cloud_ok:
                await restore_db_from_cloud(retries=1, merge_local=True)
            await reconcile_now()
            if _cloud_ok:
                await cloud_save_db()
        except Exception:
            logging.exception("Sync loop error")


async def backup_loop():
    while True:
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
        await trigger_cloud_backup()


async def start_web():
    app = web.Application()

    async def health(_):
        return web.json_response({"status": "ok", "uptime": int(time.time() - START_TIME),
                                  "cloud_db": _cloud_ok})

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Web server on port %s", PORT)


# ============================================================
# MAIN
# ============================================================


async def main():
    global manager_bot_client
    await start_web()

    if SUPABASE_SERVICE_KEY:
        await restore_db_from_cloud()
    else:
        logging.warning("SUPABASE_SERVICE_KEY not set: approvals will NOT survive a restart!")
    ensure_admin()

    await user_client.connect()
    if not await user_client.is_user_authorized():
        raise SystemExit("User account not logged in. Set SESSION_STRING (see gen_session.py).")

    clients = [user_client]
    for name, token in BOT_TOKENS.items():
        if not token:
            continue
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        await c.start(bot_token=token)
        if name == "manager":
            manager_bot_client = c
            register_manager_handlers(c)
        else:
            active_bots[name] = c
            register_student_handlers(c, name)
        clients.append(c)
        logging.info("Bot '%s' started", name)

    if manager_bot_client:
        try:
            if not SUPABASE_SERVICE_KEY:
                await manager_bot_client.send_message(
                    ADMIN_ID, "⚠️ SUPABASE_SERVICE_KEY is not set — approvals will be lost on restart.")
            elif not _cloud_ok:
                await manager_bot_client.send_message(
                    ADMIN_ID, "⚠️ Could not reach the Supabase bot_state table. Running on local data; "
                              "will retry automatically.")
            else:
                await manager_bot_client.send_message(
                    ADMIN_ID, f"✅ Bot online. Cloud DB connected — {max(0, len(db['approved']) - 1)} paid users loaded.")
        except Exception:
            pass

    asyncio.create_task(sync_loop())
    asyncio.create_task(backup_loop())
    schedule_reconcile()
    await asyncio.gather(*[c.run_until_disconnected() for c in clients])


if __name__ == "__main__":
    asyncio.run(main())
