
#!/usr/bin/env python3
# ============================================================
# MBBS Lecture & CBT Q-Bank Bot — Unified Production Engine
#  - Clean Student UI (Subject -> Lectures / Notes / MCQ Hub, #hashtag units + Search)
#  - Year-Wise Demo Bot experience (Works for Demo students, Paid users & Admin testing)
#  - 2nd Year Subjects: Pathology, Pharmacology, Microbiology (Forensic removed from 2nd Year)
#  - Supabase Cloud DB persistence + Telegram Chat Auto-Restore fallback
#  - Fast, 1-Tap Button-Driven Admin Control Center (No clutter, full student & demo management)
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
# CONFIGURATION (Environment Variables with Safe Fallbacks)
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

# CBT student portal (GitHub Pages) and the Supabase project it reads from
CBT_WEBAPP_BASE_URL = os.getenv("CBT_WEBAPP_BASE_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/index.html")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://iafqcssktvejitssqawi.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_I6SvDlS24OOid9g9DiA9qQ_jquGYE4C")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()  # Optional: service_role key for bot_state table

# Optional StringSession for cloud hosts; falls back to "session" file if empty
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
# SUBJECTS PER YEAR (Includes Notes Topic 33 & Clean Mapping)
# ============================================================

TOPICS_ALL = {
    "Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Microbiology": 5, "Notes": 33,
    "Pathology": 49, "Pharmacology": 50, "Forensic Medicine and Toxicology": 51,
    "Community Medicine": 52, "General Medicine": 53, "General Surgery": 54,
    "Obstetrics and Gynecology": 55, "Pediatrics": 56, "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58, "Orthopedics": 59, "Anesthesiology": 60,
    "Radiology": 61, "Dermatology": 62, "Psychiatry": 63,
}
TOPICS_Y1 = {
    "Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Notes": 33,
}
# Forensic Medicine and Toxicology removed from 2nd Year (kept in 3rd Year & All)
TOPICS_Y2 = {
    "Pathology": 49, "Pharmacology": 50, "Microbiology": 5, "Notes": 33,
}
TOPICS_Y3 = {
    "Community Medicine": 52, "Ophthalmology": 57, "Otorhinolaryngology (ENT)": 58,
    "Forensic Medicine and Toxicology": 51, "Notes": 33,
}
TOPICS_FINAL = {
    "General Medicine": 53, "General Surgery": 54, "Obstetrics and Gynecology": 55,
    "Pediatrics": 56, "Orthopedics": 59, "Anesthesiology": 60, "Radiology": 61,
    "Dermatology": 62, "Psychiatry": 63, "Notes": 33,
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
TIER_SHORT = {"all": "All", "year_1": "1st", "year_2": "2nd", "year_3": "3rd", "final_year": "Final"}
CONTENT_LABELS = {"full": "Full (Lec + Notes + Q-Bank)", "lectures_only": "Lectures & Notes Only"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)

# ============================================================
# DATABASE & HYBRID CLOUD STORAGE (Local + Supabase + Telegram)
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
    "default_content": "full",
    "default_days": 0,
}


def _empty_db():
    return {
        "users": {}, "banned": [], "approved": [], "approved_details": {},
        "settings": DEFAULT_SETTINGS.copy(), "daily_downloads": {},
        "demo_sessions": {}, "pending": {},
    }


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
    # Deduplicate and normalize integer IDs
    approved_clean = []
    for x in base["approved"]:
        try:
            val = int(x)
            if val not in approved_clean:
                approved_clean.append(val)
        except Exception:
            pass
    base["approved"] = approved_clean

    banned_clean = []
    for x in base["banned"]:
        try:
            val = int(x)
            if val not in banned_clean:
                banned_clean.append(val)
        except Exception:
            pass
    base["banned"] = banned_clean

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
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


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
    for uid, s in local.get("pending", {}).items():
        cloud["pending"].setdefault(uid, s)
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
# HELPERS & Q-BANK CREDENTIALS LOGIC
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


def fmt_secs(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


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


def get_user_content_tier(user_id):
    uid = int(user_id)
    if uid == ADMIN_ID:
        return "full"
    if uid not in db.get("approved", []):
        return None
    return db.get("approved_details", {}).get(str(uid), {}).get("content_tier", "lectures_only")


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
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set")
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
manager_bot_client = None
USER_CLIENT_ID = None
START_TIME = time.time()

user_subjects = {}
user_units = {}
user_search_state = {}
user_demo_years = {}  # Tracks which MBBS year a user explicitly picked in the Demo Bot
TOPIC_CACHE = {}
TOPIC_LOCKS = {}
TOPIC_CACHE_TTL = 600

relay_lock = asyncio.Lock()
RELAY_FUTURES = {}
ADMIN_STATES = {}

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
    qid, pw = get_or_create_qbank_creds(user_id)
    text = (
        f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the interactive CBT app (auto-login).\n"
        "Send /mylogin any time to see this again."
    )
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))]]
    return await send_via_any(chat_id, text, buttons)


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
# DEMO SESSION ENGINE (Strict Year-Wise Selection & Persistence)
# ============================================================

def get_demo_selected_year(user_id):
    """Returns the user's explicitly chosen Demo year ('year_1', 'year_2', 'year_3', 'final_year', 'all') or None."""
    admin_tier = db["settings"].get("demo_year_tier", "all")
    if admin_tier != "all" and admin_tier in BOT_SUBJECTS_MAP:
        return admin_tier
    if user_id is None:
        return None
    uid = int(user_id)
    if uid in user_demo_years:
        return user_demo_years[uid]
    sess = db["demo_sessions"].get(str(uid), {})
    # Prefer 'selected_year'; only accept legacy 'year_tier' if it was a specific year (not default 'all')
    saved_yr = sess.get("selected_year")
    if not saved_yr:
        legacy = sess.get("year_tier")
        if legacy in ("year_1", "year_2", "year_3", "final_year"):
            saved_yr = legacy
    if saved_yr in BOT_SUBJECTS_MAP:
        user_demo_years[uid] = saved_yr
        return saved_yr
    return None


def get_demo_topics(user_id=None):
    """Returns the dictionary of subjects for the user's selected MBBS year in Demo Bot."""
    yr = get_demo_selected_year(user_id)
    if yr and yr in BOT_SUBJECTS_MAP:
        return BOT_SUBJECTS_MAP[yr]
    return TOPICS_ALL


def get_or_start_demo_session(user_id):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    admin_tier = db["settings"].get("demo_year_tier", "all")
    if not session:
        init_year = admin_tier if admin_tier != "all" else None
        session = {
            "start_time": time.time(),
            "duration_mins": db["settings"].get("demo_duration_mins", 10),
            "max_downloads": db["settings"].get("demo_max_downloads", 2),
            "downloads_used": 0,
            "cbt_id": "DEMO-" + _pick(4),
            "cbt_pass": _pick(6),
            "selected_year": init_year,
            "year_tier": init_year or "all",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cbt_synced": False,
        }
        db["demo_sessions"][s_uid] = session
        _write_db(db)
    return session


def check_demo_status(user_id):
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
        exp = (datetime.now(timezone.utc) + timedelta(minutes=session.get("duration_mins", 10) + 60)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")
        await supabase_upsert_student(
            session["cbt_id"], session["cbt_pass"], f"Demo: {name}",
            active=True, expires_at=exp, is_demo=True)
        session["cbt_synced"] = True
        _write_db(db)
    except Exception as e:
        logging.warning("Could not sync demo CBT user %s: %s", user_id, e)


# ============================================================
# TRACKING & ACCESS CONTROL
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


def is_expired(uid):
    exp = db["approved_details"].get(str(uid), {}).get("expiry")
    if exp and db["settings"].get("expiry_enabled"):
        try:
            return datetime.now().date() > datetime.strptime(exp, "%Y-%m-%d").date()
        except Exception:
            return False
    return False


def check_access(user_id, bot_type):
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
    for day in [d for d in list(db["daily_downloads"].keys()) if d < cutoff]:
        db["daily_downloads"].pop(day, None)
    day_map = db["daily_downloads"].setdefault(today, {})
    day_map[str(user_id)] = day_map.get(str(user_id), 0) + 1
    _write_db(db)


def grant_plan(target_id, content_tier="full", tier=None, days=None):
    """Approve or update a student's plan and auto-generate Q-Bank credentials if Full."""
    uid = int(target_id)
    s_uid = str(uid)
    if uid not in db["approved"]:
        db["approved"].append(uid)
    if uid in db["banned"]:
        db["banned"].remove(uid)
    db["pending"].pop(s_uid, None)

    det = db["approved_details"].setdefault(s_uid, {})
    if tier is None:
        bot_used = db["users"].get(s_uid, {}).get("bot_used", "all")
        tier = det.get("tier") or (bot_used if bot_used in TIER_LABELS else "all")
    det["tier"] = tier
    det["content_tier"] = content_tier
    if days is not None:
        det["expiry"] = (datetime.now() + timedelta(days=int(days))).strftime("%Y-%m-%d") if int(days) > 0 else None
    else:
        det.setdefault("expiry", None)
    det.setdefault("added_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

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
# CLOUD BACKUP & AUTO-RESTORE FROM TELEGRAM
# ============================================================

async def trigger_cloud_backup(force=False):
    if not manager_bot_client or not (force or db["settings"].get("cloud_backup_enabled", True)):
        return
    try:
        _write_local(db)
        if os.path.exists(DB_FILE):
            await manager_bot_client.send_file(
                ADMIN_ID, DB_FILE,
                caption=("☁️ **Auto-Sync Cloud Backup**\n"
                         f"📅 Date: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                         f"👥 Registered: `{len(db.get('users', {}))}` | 💎 Paid: `{len(db.get('approved', []))}`\n"
                         "💡 *Send this file back with caption `/restore` to restore anytime.*"))
    except Exception:
        logging.exception("Cloud backup failed")


async def auto_restore_from_telegram():
    global db
    if not manager_bot_client:
        return
    try:
        if len(db.get("users", {})) <= 1 and len(db.get("approved", [])) <= 1:
            logging.info("Checking Telegram chat for database backup...")
            async for msg in manager_bot_client.iter_messages(ADMIN_ID, limit=30):
                if msg.file and (msg.file.name == "bot_database.json"
                                 or (msg.text and "Cloud Backup" in msg.text)):
                    await msg.download_media(file=DB_FILE)
                    db.clear()
                    db.update(load_db())
                    ensure_admin()
                    _write_db(db)
                    logging.info("Restored database from chat backup.")
                    await manager_bot_client.send_message(
                        ADMIN_ID, "🔄 **Cloud Database Auto-Restored Successfully from Chat!**")
                    break
    except Exception:
        logging.exception("Auto-restore from Telegram failed")


async def notify_manager_new_request(user, bot_type):
    if not manager_bot_client or not user:
        return
    try:
        uid = user.id
        s_uid = str(uid)
        p = db["pending"].get(s_uid)
        if p and time.time() - p.get("last_ping", 0) < 600:
            return
        db["pending"][s_uid] = {
            "requested_at": (p or {}).get("requested_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
            "bot": bot_type,
            "last_ping": time.time(),
        }
        _write_db(db)

        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Student"
        username = f"@{user.username}" if user.username else "No username"
        text = (f"🔔 **New Student Access Request!**\n\n"
                f"👤 **Student:** {esc(name)} ({esc(username)})\n"
                f"🆔 **User ID:** `{uid}`\n"
                f"🤖 **Bot Selected:** `{bot_type}` ({BOT_TITLES_MAP.get(bot_type, bot_type)})\n"
                f"🕒 **Time:** `{datetime.now().strftime('%H:%M:%S')}`")
        buttons = [
            [Button.inline("⚡ Full (Lec + Notes + Q-Bank)", data=f"adm_app_full:{uid}".encode()),
             Button.inline("📚 Lectures Only", data=f"adm_app_lec:{uid}".encode())],
            [Button.inline("✏️ Custom Plan / Expiry", data=f"pc:{uid}".encode()),
             Button.inline("❌ Reject", data=f"rj:{uid}".encode()),
             Button.inline("⛔ Ban", data=f"adm_ban:{uid}".encode())],
        ]
        await manager_bot_client.send_message(ADMIN_ID, text, buttons=buttons)
    except Exception:
        logging.exception("Failed to dispatch manager alert")


# ============================================================
# TOPIC FETCHER, UNIT PARSER & FAST LECTURE DELIVERY
# ============================================================

def extract_hashtag(text):
    if not text:
        return None
    m = re.search(r"(?<!\w)#([A-Za-z0-9_]+)", text)
    return m.group(1) if m else None


def get_filename(message, number=1):
    try:
        if message.document and message.document.attributes:
            for attr in message.document.attributes:
                if getattr(attr, "file_name", None):
                    return attr.file_name
    except Exception:
        pass
    text = (message.text or message.message or "").strip()
    if text:
        clean = re.sub(r"#\w+", "", text.splitlines()[0]).strip()
        if clean:
            return clean
    return f"Lecture {number}"


async def get_topic_messages(topic_id, force=False):
    now = time.time()
    cached = TOPIC_CACHE.get(f"msgs_{topic_id}")
    if cached and not force and now - cached[0] < TOPIC_CACHE_TTL:
        return cached[1]

    lock = TOPIC_LOCKS.setdefault(topic_id, asyncio.Lock())
    async with lock:
        cached = TOPIC_CACHE.get(f"msgs_{topic_id}")
        if cached and not force and time.time() - cached[0] < TOPIC_CACHE_TTL:
            return cached[1]
        messages = []
        try:
            async for message in user_client.iter_messages(GROUP_ID, reply_to=topic_id):
                messages.append(message)
            messages.reverse()
            if messages:
                TOPIC_CACHE[f"msgs_{topic_id}"] = (time.time(), messages)
        except FloodWaitError as e:
            await asyncio.sleep(min(e.seconds, 30) + 1)
        except Exception:
            logging.exception("Error while reading topic messages")
            if cached:
                return cached[1]
        return messages


async def get_topic_units(topic_id, force=False):
    now = time.time()
    cached = TOPIC_CACHE.get(topic_id)
    if cached and not force and now - cached[0] < TOPIC_CACHE_TTL:
        return cached[1]

    units, current = {}, None
    all_media = []
    for message in await get_topic_messages(topic_id, force=force):
        tag = extract_hashtag(message.text or "")
        if tag:
            current = tag
            units.setdefault(current, [])
        if message.media:
            all_media.append(message)
            if current is not None:
                units[current].append(message)

    if not units and all_media:
        units["All_Lectures"] = all_media

    if units:
        TOPIC_CACHE[topic_id] = (now, units)
    return units


async def deliver_lecture(bot_client, bot_key, bot_entity, chat_id, message, status_msg=None):
    caption_text = message.text or ""

    # 1) Fast Path: If the student bot itself is in the group, send directly without relay!
    try:
        direct_msg = await bot_client.get_messages(GROUP_ID, ids=message.id)
        if direct_msg and direct_msg.media:
            await bot_client.send_file(
                entity=chat_id, file=direct_msg.media,
                caption=caption_text, supports_streaming=True
            )
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
    except FloodWaitError as e:
        await asyncio.sleep(min(e.seconds, 20) + 1)
    except Exception:
        pass

    # 2) Relay Path: User client forwards to the specific bot -> bot sends to student
    async with relay_lock:
        future = asyncio.get_running_loop().create_future()
        RELAY_FUTURES[bot_key] = future
        relayed = None
        try:
            target_entity = bot_entity
            if not target_entity:
                me = await bot_client.get_me()
                target_entity = me.username
            await user_client.forward_messages(target_entity, message)
            relayed = await asyncio.wait_for(future, timeout=15.0)
            try:
                await bot_client.send_file(
                    entity=chat_id, file=relayed.media,
                    caption=caption_text, supports_streaming=True
                )
            except Exception:
                await relayed.forward_to(chat_id)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
        except Exception:
            logging.warning("Relay fallback triggered for bot %s.", bot_key)
        finally:
            RELAY_FUTURES.pop(bot_key, None)
            if relayed:
                try:
                    await relayed.delete()
                except Exception:
                    pass

        # 3) Direct Forward Fallback (if bot has group read permissions)
        try:
            await bot_client.forward_messages(chat_id, message.id, GROUP_ID)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
        except Exception:
            pass

        # 4) Final Fallback Path: Download & Re-upload
        file_path = None
        try:
            if status_msg:
                try:
                    await status_msg.edit("⚡ **Streaming lecture...**")
                except Exception:
                    pass
            file_path = await user_client.download_media(message, file="downloads/")
            if file_path:
                await bot_client.send_file(
                    entity=chat_id, file=file_path,
                    caption=caption_text, supports_streaming=True
                )
                if status_msg:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                return True
        except Exception:
            logging.exception("Delivery failed.")
            if status_msg:
                try:
                    await status_msg.edit("❌ Failed to deliver lecture.")
                except Exception:
                    pass
        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return False


# ============================================================
# STUDENT UI MENUS (Simple & Clean v1 Style + Demo Year Picker)
# ============================================================

async def edit(event, text, buttons=None):
    try:
        await event.edit(text, buttons=buttons)
    except MessageNotModifiedError:
        pass
    except Exception:
        try:
            await event.respond(text, buttons=buttons)
        except Exception:
            pass


def make_demo_year_picker(user_id, is_demo_user=True):
    """Lets any user on the Demo Bot choose which MBBS Year they want to explore."""
    rows = [
        [Button.inline("1️⃣ 1st Year MBBS (3 Subjects)", data=b"demo_yr:year_1")],
        [Button.inline("2️⃣ 2nd Year MBBS (3 Subjects)", data=b"demo_yr:year_2")],
        [Button.inline("3️⃣ 3rd Year MBBS (4 Subjects)", data=b"demo_yr:year_3")],
        [Button.inline("4️⃣ Final Year MBBS (9 Subjects)", data=b"demo_yr:final_year")],
        [Button.inline("📚 View All MBBS Subjects Together", data=b"demo_yr:all")],
    ]
    if is_demo_user:
        sess = get_or_start_demo_session(user_id)
        rows.append([Button.url("🌐 Try CBT Q-Bank (Demo)", generate_demo_webapp_url(sess["cbt_id"], sess["cbt_pass"]))])
        rows.append([Button.inline("📩 Request Full Access", data=b"req_access")])
    elif user_id is not None and (int(user_id) == ADMIN_ID or has_qbank(user_id)):
        rows.append([Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))])
    return rows


def make_main_menu(topics, user_id=None, is_demo_user=False, is_demo_bot=False):
    subjects = [s for s in topics.keys() if s != "Notes"]
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(f"📘 {subjects[i]}", data=f"sub:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(f"📘 {subjects[i + 1]}", data=f"sub:{i + 1}".encode()))
        buttons.append(row)

    # On the Demo Bot, always allow switching years (unless Admin locked a single year)
    if is_demo_bot and db["settings"].get("demo_year_tier", "all") == "all":
        cur_yr = get_demo_selected_year(user_id) or "all"
        buttons.append([Button.inline(f"🎓 Change Year (Current: {TIER_LABELS.get(cur_yr, 'All Years')})", data=b"demo_pick_year")])

    if is_demo_user:
        sess = get_or_start_demo_session(user_id)
        buttons.append([Button.url("🌐 Try CBT Q-Bank (Demo)", generate_demo_webapp_url(sess["cbt_id"], sess["cbt_pass"]))])
        buttons.append([Button.inline("📩 Request Full Access", data=b"req_access")])
    elif user_id is not None and (int(user_id) == ADMIN_ID or has_qbank(user_id)):
        buttons.append([Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))])
        if int(user_id) != ADMIN_ID:
            buttons.append([Button.inline("🔑 My CBT Q-Bank Login", data=b"mylogin")])
    return buttons


def make_subject_menu():
    return [
        [Button.inline("📚 Video Lectures", data=b"lectures"), Button.inline("📝 Notes & PDFs", data=b"notes")],
        [Button.inline("🎯 High-Yield MCQ Hub", data=b"mcq_hub"), Button.inline("🔎 Search Subject", data=b"search_subj")],
        [Button.inline("⬅️ All Subjects", data=b"home")],
    ]


def make_mcq_hub_menu(user_id, is_demo_user=False):
    if is_demo_user:
        sess = get_or_start_demo_session(user_id)
        cbt_btn = Button.url("🌐 Try Demo CBT Q-Bank App", generate_demo_webapp_url(sess["cbt_id"], sess["cbt_pass"]))
    elif get_user_content_tier(user_id) == "full":
        cbt_btn = Button.url("🌐 Launch MBBS CBT Q-Bank App", generate_webapp_launch_url(user_id))
    else:
        cbt_btn = Button.inline("🔒 CBT Q-Bank (Upgrade Required)", data=b"mcq_upgrade_info")
    return [
        [cbt_btn],
        [Button.inline("📂 Topic-Wise Q-Bank PDFs", data=b"mcq_p:topic_wise")],
        [Button.inline("🏛️ Previous Year Questions (PYQs)", data=b"mcq_p:pyqs")],
        [Button.inline("🎲 Random / Mock Test MCQs", data=b"mcq_p:random")],
        [Button.inline("⬅️ Back to Subject", data=b"sub_back")],
    ]


# ============================================================
# STUDENT BOTS HANDLERS
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    entity_box = {}
    is_demo_bot = (bot_key == "demo")

    def is_demo_user(uid):
        return is_demo_bot and int(uid) != ADMIN_ID and int(uid) not in db.get("approved", [])

    def active_topics_for(uid):
        """Returns the exact Year-Wise subject dictionary for this user."""
        if is_demo_bot:
            # Works for Demo Students, Paid Users & Admin testing the Demo Bot!
            return get_demo_topics(uid)
        return bot_topics

    def demo_year_label(uid):
        yr = get_demo_selected_year(uid)
        return TIER_LABELS.get(yr, "Select Year") if yr else "Select Year"

    def demo_banner(uid):
        if is_demo_user(uid):
            st, rem, used, mx = check_demo_status(uid)
            return f"\n🎓 **Year:** `{demo_year_label(uid)}` | ⏱ **Time Left:** `{fmt_secs(rem)}` | 📥 **Files:** `{used}/{mx}`"
        return f"\n🎓 **Selected Year:** `{demo_year_label(uid)}`"

    async def guard(event, check_limit=False):
        uid = event.sender_id
        if is_banned(uid):
            await event.answer("⛔ You are restricted from using this service.", alert=True)
            return False

        if is_demo_user(uid):
            st, rem, used, mx = check_demo_status(uid)
            if st in ("new", "expired"):
                await event.answer("⏰ Your demo session has ended! Request full access.", alert=True)
                await event.respond(
                    f"⏰ **Your free demo has ended.**\n\nTo unlock all subjects, video lectures, notes, and the CBT Q-Bank, contact {OWNER_CONTACT}.",
                    buttons=[[Button.inline("📩 Request Full Access", data=b"req_access")]]
                )
                return False
            if check_limit and st == "download_limit_reached":
                await event.answer(f"📥 Demo limit reached ({used}/{mx} files)!", alert=True)
                await event.respond(
                    f"📥 **Demo Download Limit Reached ({used}/{mx})**\n\nContact {OWNER_CONTACT} to unlock unlimited access!",
                    buttons=[[Button.inline("📩 Request Full Access", data=b"req_access")]]
                )
                return False
            return True

        allowed, _ = check_access(uid, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return False
        if check_limit and not check_daily_limit(uid)[0]:
            await event.answer("⚠️ Daily download limit reached!", alert=True)
            return False
        return True

    @bot_client.on(events.CallbackQuery(data=b"noop"))
    async def cb_noop(event):
        await event.answer()

    @bot_client.on(events.NewMessage)
    async def relay_listener(event):
        if event.is_private and USER_CLIENT_ID and event.sender_id == USER_CLIENT_ID and event.media:
            fut = RELAY_FUTURES.get(bot_key)
            if fut and not fut.done():
                fut.set_result(event.message)

    @bot_client.on(events.NewMessage(pattern=r"^/(start|help|menu)(?:\s.*)?$"))
    async def start_handler(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)
        uid = event.sender_id
        user_search_state.pop(uid, None)

        if is_banned(uid):
            await event.respond("⛔ You are restricted from using this service.")
            return

        # ----------------------------------------------------
        # 1) DEMO BOT EXPERIENCE (Year-Wise Picker First!)
        # ----------------------------------------------------
        if is_demo_bot:
            if is_demo_user(uid):
                st, _, _, _ = check_demo_status(uid)
                if st == "new" and not db["settings"].get("demo_auto_start", True):
                    m = db["settings"].get("demo_duration_mins", 10)
                    n = db["settings"].get("demo_max_downloads", 2)
                    await event.respond(
                        f"🧪 **{bot_title}**\n\n⏱ **{m} minutes** free trial · 📥 **{n} lecture downloads**\n\n"
                        "Tap below to begin your trial immediately:",
                        buttons=[[Button.inline("▶️ Start Free Demo", data=b"demo_start")]]
                    )
                    return
                sess = get_or_start_demo_session(uid)
                await ensure_demo_cbt_synced(uid, display_name(uid))
                st, _, _, _ = check_demo_status(uid)
                if st == "expired":
                    await event.respond(
                        f"⏰ **Your Demo Trial Has Expired!**\n\nTo enroll in the full plan, contact {OWNER_CONTACT}.",
                        buttons=[[Button.inline("📩 Request Full Access", data=b"req_access")]]
                    )
                    return
                cbt_line = f"\n\n🆔 **Demo CBT ID:** `{sess['cbt_id']}` | 🔑 **Pass:** `{sess['cbt_pass']}`"
            else:
                cbt_line = ""

            selected_yr = get_demo_selected_year(uid)
            # If Admin has not locked a single year and user hasn't picked a year yet -> Show Year Picker!
            if not selected_yr:
                await event.respond(
                    f"🎓 **{bot_title}**{demo_banner(uid)}{cbt_line}\n\n"
                    "👇 **Please select your MBBS Year to view its subjects:**",
                    buttons=make_demo_year_picker(uid, is_demo_user=is_demo_user(uid))
                )
                return

            await event.respond(
                f"🎓 **{bot_title} — {TIER_LABELS.get(selected_yr, 'All Years')}**{demo_banner(uid)}{cbt_line}\n\n"
                "Select a subject below to begin:",
                buttons=make_main_menu(active_topics_for(uid), uid, is_demo_user=is_demo_user(uid), is_demo_bot=True)
            )
            return

        # ----------------------------------------------------
        # 2) PAID YEAR-WISE / ALL-SUBJECTS BOTS
        # ----------------------------------------------------
        allowed, reason = check_access(uid, bot_key)
        if not allowed:
            if reason.startswith("tier_mismatch"):
                user_tier = reason.split(":")[1]
                label = BOT_TITLES_MAP.get(user_tier, user_tier.replace("_", " ").title())
                await event.respond(
                    f"⚠️ **Year Access Restricted**\n\nYour subscription is activated for **{label}**, "
                    f"but this is the **{bot_title}**.\n\nTo upgrade or switch years, contact {OWNER_CONTACT}.")
            elif reason == "expired":
                await event.respond(f"⚠️ **Subscription Expired!**\n\nYour access period has ended. "
                                    f"Contact {OWNER_CONTACT} to renew your enrollment.")
            else:
                await event.respond(
                    LOCKED_MESSAGE.format(user_id=uid),
                    buttons=[[Button.inline("🔔 Remind Admin / Request Access", data=b"req_access")]]
                )
                await notify_manager_new_request(sender, bot_key)
            return

        tier = get_user_content_tier(uid)
        banner = ""
        if tier == "full" and uid != ADMIN_ID:
            qid, qpass = get_or_create_qbank_creds(uid)
            banner = ("\n\n━━━━━━━━━━━━━━━━━━━━━━\n🩺 **YOUR CBT Q-BANK LOGIN:**\n"
                      f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{qpass}`\n"
                      "*(The launch button logs you in automatically)*\n━━━━━━━━━━━━━━━━━━━━━━")
        elif tier == "lectures_only":
            banner = ("\n\n━━━━━━━━━━━━━━━━━━━━━━\n📚 **PLAN:** Video Lectures & Notes Only\n"
                      f"💡 *To unlock the CBT Q-Bank app, contact {OWNER_CONTACT}*\n━━━━━━━━━━━━━━━━━━━━━━")

        limit_note = ""
        if db["settings"].get("daily_limit_enabled", False) and uid != ADMIN_ID:
            _, cur, mx = check_daily_limit(uid)
            limit_note = f"\n⚡ Daily Limit: `{cur}/{mx}` downloads used"

        await event.respond(
            f"🎓 **{bot_title}**{limit_note}{banner}\n\nSelect a subject below to begin:",
            buttons=make_main_menu(active_topics_for(uid), uid, is_demo_user=False, is_demo_bot=False)
        )

    @bot_client.on(events.CallbackQuery(data=b"demo_start"))
    async def cb_demo_start(event):
        uid = event.sender_id
        if not is_demo_bot:
            return
        sess = get_or_start_demo_session(uid)
        await ensure_demo_cbt_synced(uid, display_name(uid))
        selected_yr = get_demo_selected_year(uid)
        if not selected_yr:
            await edit(
                event,
                f"🎓 **{bot_title}**{demo_banner(uid)}\n\n"
                f"🆔 **Demo CBT ID:** `{sess['cbt_id']}` | 🔑 **Pass:** `{sess['cbt_pass']}`\n\n"
                "👇 **Select your MBBS Year to explore lectures, notes & MCQs:**",
                make_demo_year_picker(uid, is_demo_user=is_demo_user(uid))
            )
            return
        await edit(
            event,
            f"🎓 **{bot_title} — {TIER_LABELS.get(selected_yr, 'All Years')}**{demo_banner(uid)}\n\n"
            f"🆔 **Demo CBT ID:** `{sess['cbt_id']}` | 🔑 **Pass:** `{sess['cbt_pass']}`\n\n"
            "Select a subject below to begin:",
            make_main_menu(active_topics_for(uid), uid, is_demo_user=is_demo_user(uid), is_demo_bot=True)
        )

    @bot_client.on(events.CallbackQuery(data=b"demo_pick_year"))
    async def cb_demo_pick_year(event):
        if not await guard(event):
            return
        uid = event.sender_id
        cbt_line = ""
        if is_demo_user(uid):
            sess = get_or_start_demo_session(uid)
            cbt_line = f"\n\n🆔 **Demo CBT ID:** `{sess['cbt_id']}` | 🔑 **Pass:** `{sess['cbt_pass']}`"
        await edit(
            event,
            f"🎓 **{bot_title}**{demo_banner(uid)}{cbt_line}\n\n"
            "👇 **Select which MBBS Year you want to explore:**",
            make_demo_year_picker(uid, is_demo_user=is_demo_user(uid))
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^demo_yr:(\w+)$"))
    async def cb_demo_set_year(event):
        if not await guard(event):
            return
        uid = event.sender_id
        yr = event.pattern_match.group(1).decode()
        if yr not in BOT_SUBJECTS_MAP:
            yr = "all"
        user_demo_years[uid] = yr
        user_subjects.pop(uid, None)
        user_units.pop(uid, None)

        cbt_line = ""
        if is_demo_user(uid):
            sess = get_or_start_demo_session(uid)
            sess["selected_year"] = yr
            sess["year_tier"] = yr
            _write_db(db)
            cbt_line = f"\n\n🆔 **Demo CBT ID:** `{sess['cbt_id']}` | 🔑 **Pass:** `{sess['cbt_pass']}`"
        elif str(uid) in db.get("demo_sessions", {}):
            db["demo_sessions"][str(uid)]["selected_year"] = yr
            db["demo_sessions"][str(uid)]["year_tier"] = yr
            _write_db(db)

        await event.answer(f"Switched to {TIER_LABELS.get(yr, 'All Years')}!")
        await edit(
            event,
            f"🎓 **{bot_title} — {TIER_LABELS.get(yr, 'All Years')}**{demo_banner(uid)}{cbt_line}\n\n"
            "Select a subject below to begin:",
            make_main_menu(active_topics_for(uid), uid, is_demo_user=is_demo_user(uid), is_demo_bot=True)
        )

    @bot_client.on(events.CallbackQuery(data=b"req_access"))
    async def cb_req_access(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)
        await notify_manager_new_request(sender, bot_key)
        await event.answer("✅ Request sent to Admin!", alert=True)
        await event.respond(
            f"📨 **Access request sent!**\n\nYour ID `{event.sender_id}` has been forwarded to the admin.\n"
            f"For instant activation, message {OWNER_CONTACT}."
        )

    @bot_client.on(events.NewMessage(pattern=r"^/myid$"))
    async def myid_cmd(event):
        await event.respond(f"🆔 **Your Telegram User ID:** `{event.sender_id}`")

    @bot_client.on(events.NewMessage(pattern=r"^/status$"))
    async def status_cmd(event):
        uid = event.sender_id
        if is_demo_user(uid):
            await event.respond(f"🧪 **Demo Mode Active**{demo_banner(uid)}")
            return
        allowed, _ = check_access(uid, bot_key)
        if not allowed:
            await event.respond(LOCKED_MESSAGE.format(user_id=uid))
            return
        det = db.get("approved_details", {}).get(str(uid), {})
        await event.respond(
            f"💎 **Subscription Status**\n\n"
            f"• **Year Tier:** {TIER_LABELS.get(det.get('tier', 'all'), 'All Years')}\n"
            f"• **Plan:** {CONTENT_LABELS.get(det.get('content_tier', 'full'), 'Full')}\n"
            f"• **Expiry:** `{det.get('expiry') or 'Lifetime'}`"
        )

    @bot_client.on(events.NewMessage(pattern=r"^/mylogin$"))
    async def mylogin_cmd(event):
        uid = event.sender_id
        if uid == ADMIN_ID:
            await event.respond("ℹ️ Admin accounts do not use a student Q-Bank login.")
        elif is_demo_user(uid):
            s = get_or_start_demo_session(uid)
            await ensure_demo_cbt_synced(uid, display_name(uid))
            await event.respond(
                f"🧪 **Demo CBT Login**\n🆔 `{s['cbt_id']}`\n🔑 `{s['cbt_pass']}`",
                buttons=[[Button.url("🌐 Open Demo CBT", generate_demo_webapp_url(s["cbt_id"], s["cbt_pass"]))]]
            )
        elif is_banned(uid) or not has_qbank(uid):
            await event.respond("🔒 The CBT Q-Bank login is included in the **Full plan** "
                                f"(Lectures + Notes + MCQ).\nTo upgrade, contact {OWNER_CONTACT}.")
        elif not check_access(uid, bot_key)[0]:
            await event.respond(f"🔒 Your access is not active. Contact {OWNER_CONTACT}")
        else:
            await send_login_card(event.chat_id, uid, title="🔑 **Your CBT Q-Bank login**")

    @bot_client.on(events.CallbackQuery(data=b"mylogin"))
    async def mylogin_cb(event):
        uid = event.sender_id
        if not await guard(event):
            return
        if not has_qbank(uid):
            await event.answer("🔒 Full plan required.", alert=True)
            return
        await event.answer()
        await send_login_card(event.chat_id, uid, title="🔑 **Your CBT Q-Bank login**")

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def cb_home(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        if is_demo_bot:
            selected_yr = get_demo_selected_year(uid)
            if not selected_yr:
                await cb_demo_pick_year(event)
                return
            title_line = f"🎓 **{bot_title} — {TIER_LABELS.get(selected_yr, 'All Years')}**{demo_banner(uid)}"
        else:
            title_line = f"🎓 **{bot_title}**"
        await edit(
            event,
            f"{title_line}\n\nSelect a subject below:",
            make_main_menu(active_topics_for(uid), uid, is_demo_user=is_demo_user(uid), is_demo_bot=is_demo_bot)
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def cb_sub(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        idx = int(event.pattern_match.group(1))
        topics = active_topics_for(uid)
        subjects = [s for s in topics.keys() if s != "Notes"]
        if 0 <= idx < len(subjects):
            user_subjects[uid] = subjects[idx]
            await edit(event, f"📚 **{subjects[idx]}**\n\nChoose an option below:", make_subject_menu())
        else:
            await event.answer("Please select your year/subject again.")

    @bot_client.on(events.CallbackQuery(data=b"sub_back"))
    async def cb_sub_back(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid)
        if not subj or subj not in topics:
            subj = next((s for s in topics.keys() if s != "Notes"), next(iter(topics)))
            user_subjects[uid] = subj
        await edit(event, f"📚 **{subj}**\n\nChoose an option below:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"lectures"))
    async def cb_lectures(event):
        if not await guard(event):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid)
        if not subj or subj not in topics:
            await event.answer("Select subject again.")
            return
        await event.answer("Loading lectures...")
        units = await get_topic_units(topics[subj])
        if not units:
            await edit(event, f"📚 **{subj}**\n\nNo lecture units found.",
                       [[Button.inline("⬅️ Back", data=b"sub_back")]])
            return
        names = list(units.keys())
        user_units[uid] = {"subject": subj, "units": units, "unit_names": names}
        buttons = []
        for i in range(0, len(names), 2):
            row = [Button.inline(f"📂 #{names[i]} ({len(units[names[i]])})", data=f"unit:{i}".encode())]
            if i + 1 < len(names):
                row.append(Button.inline(f"📂 #{names[i + 1]} ({len(units[names[i + 1]])})", data=f"unit:{i + 1}".encode()))
            buttons.append(row)
        buttons.append([Button.inline("🔎 Search in Subject", data=b"search_subj")])
        buttons.append([Button.inline("⬅️ Back to Subject", data=b"sub_back")])
        await edit(event, f"📚 **{subj} Lectures**\n\nSelect a unit:", buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^unit:(\d+)(?::(\d+))?$"))
    async def cb_unit(event):
        if not await guard(event):
            return
        data = user_units.get(event.sender_id)
        if not data:
            await event.answer("Reopen the subject.")
            return
        idx = int(event.pattern_match.group(1))
        page = int(event.pattern_match.group(2) or 0)
        if 0 <= idx < len(data["unit_names"]):
            name = data["unit_names"][idx]
            lectures = data["units"].get(name, [])
            per_page = 15
            pages = max(1, (len(lectures) + per_page - 1) // per_page)
            page = max(0, min(page, pages - 1))
            chunk = lectures[page * per_page:(page + 1) * per_page]

            buttons = []
            for i, lec in enumerate(chunk, start=page * per_page):
                fname = get_filename(lec, i + 1)
                if len(fname) > 42:
                    fname = fname[:39] + "..."
                buttons.append([Button.inline(f"📄 {fname}", data=f"file:{lec.id}".encode())])

            if pages > 1:
                nav = []
                if page > 0:
                    nav.append(Button.inline("◀ Prev", data=f"unit:{idx}:{page - 1}".encode()))
                nav.append(Button.inline(f"{page + 1}/{pages}", data=b"noop"))
                if page < pages - 1:
                    nav.append(Button.inline("Next ▶", data=f"unit:{idx}:{page + 1}".encode()))
                buttons.append(nav)

            buttons.append([Button.inline("⬅️ Units", data=b"lectures")])
            await edit(event, f"📂 **#{name}** ({len(lectures)} lectures):\n\nSelect a lecture:", buttons)

    @bot_client.on(events.CallbackQuery(data=b"search_subj"))
    async def cb_search_subj(event):
        if not await guard(event):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid)
        if not subj or subj not in topics:
            await event.answer("Select a subject first.")
            return
        user_search_state[uid] = {"subject": subj, "topic_id": topics[subj]}
        await edit(
            event,
            f"🔎 **Search in {subj}**\n\nSend any keyword or topic name (e.g. `neuro`, `blood`, `lecture 3`):",
            [[Button.inline("⬅️ Cancel Search", data=b"sub_back")]]
        )

    @bot_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private and not (e.raw_text or "").startswith("/") and not e.media))
    async def student_search_text(event):
        uid = event.sender_id
        st = user_search_state.pop(uid, None)
        if not st:
            return
        if not await guard(event):
            return
        query = (event.raw_text or "").strip().lower()
        if not query:
            return
        subj = st["subject"]
        tid = st["topic_id"]
        msgs = await get_topic_messages(tid)
        matches = []
        for i, m in enumerate(msgs):
            if m.media:
                fname = get_filename(m, i + 1)
                hay = f"{fname} {m.text or ''}".lower()
                if all(w in hay for w in query.split()):
                    matches.append((m, fname))
        if not matches:
            await event.respond(
                f"😕 No lectures found for **`{esc(query)}`** in **{subj}**.",
                buttons=[[Button.inline("🔎 Search Again", data=b"search_subj"),
                          Button.inline("⬅️ Back to Subject", data=b"sub_back")]]
            )
            return
        buttons = []
        for m, fname in matches[:20]:
            short = fname[:39] + "..." if len(fname) > 42 else fname
            buttons.append([Button.inline(f"📄 {short}", data=f"file:{m.id}".encode())])
        buttons.append([Button.inline("🔎 Search Again", data=b"search_subj"),
                        Button.inline("⬅️ Back to Subject", data=b"sub_back")])
        more = f" (showing top 20 of {len(matches)})" if len(matches) > 20 else ""
        await event.respond(f"🔎 **Found {len(matches)} lecture(s) in {subj}**{more}:", buttons=buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^file:(\d+)$"))
    async def cb_file(event):
        if not await guard(event, check_limit=True):
            return
        uid = event.sender_id
        mid = int(event.pattern_match.group(1))
        await event.answer("⚡ Sending lecture...")
        status = await bot_client.send_message(event.chat_id, "⚡ **Sending lecture directly...**")
        try:
            msg = await user_client.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                if await deliver_lecture(bot_client, bot_key, entity_box.get("entity"), event.chat_id, msg, status):
                    if is_demo_user(uid):
                        record_demo_download(uid)
                    else:
                        record_download(uid)
            else:
                await status.edit("❌ Lecture file not found.")
        except Exception:
            logging.exception("File deliver error")
            await status.edit("❌ Delivery failed.")

    @bot_client.on(events.CallbackQuery(data=b"notes"))
    async def cb_notes(event):
        if not await guard(event, check_limit=True):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid)
        if not subj:
            await event.answer("Select subject again.")
            return
        await event.answer()
        status = await bot_client.send_message(event.chat_id, f"🔍 Searching notes for **{subj}**...")
        try:
            notes = await get_topic_messages(topics.get("Notes", 33))
            key = re.sub(r"[^a-zA-Z0-9]", "", subj).lower()
            found = [m for m in notes if m.media and (
                key in re.sub(r"[^a-zA-Z0-9]", "", (m.text or "")).lower()
                or key in re.sub(r"[^a-zA-Z0-9]", "", get_filename(m)).lower())]
            if not found:
                await status.edit(f"❌ No notes found for **{subj}**.")
                return
            await status.edit(f"⚡ Delivering {len(found)} note(s)...")
            sent = 0
            for m in found:
                if await deliver_lecture(bot_client, bot_key, entity_box.get("entity"), event.chat_id, m, None):
                    sent += 1
            if sent:
                if is_demo_user(uid):
                    record_demo_download(uid)
                else:
                    record_download(uid)
            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            logging.exception("Notes deliver error")
            await status.edit("❌ Could not deliver notes.")

    @bot_client.on(events.CallbackQuery(data=b"mcq_hub"))
    async def cb_mcq_hub(event):
        if not await guard(event):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid, next((s for s in topics.keys() if s != "Notes"), next(iter(topics))))
        await edit(
            event,
            f"🎯 **{subj} MCQ & Question Bank Hub**\n\nSelect your practice material:\n\n"
            "• 🌐 **Interactive CBT App**: browser exam simulator with timers & rationales.\n"
            "• 📂 **Topic-Wise Q-Bank**: unit-wise question papers & PDFs.\n"
            "• 🏛️ **Previous Year Questions (PYQs)**: past recalls.\n"
            "• 🎲 **Random / Mock Test MCQs**: mixed subject questions.",
            make_mcq_hub_menu(uid, is_demo_user=is_demo_user(uid))
        )

    @bot_client.on(events.CallbackQuery(data=b"mcq_upgrade_info"))
    async def cb_upgrade_info(event):
        await event.answer("🔒 Q-Bank Access Required", alert=True)
        await event.respond(
            "🔒 **Interactive Q-Bank Not Included in Your Current Plan**\n\n"
            "Your account currently has access to **Lectures & Notes Only**.\n\n"
            f"To unlock the CBT test simulator with scorecards and option shuffling, "
            f"contact {OWNER_CONTACT} to upgrade your plan.")

    @bot_client.on(events.CallbackQuery(pattern=rb"^mcq_p:(.+)$"))
    async def cb_mcq_paper(event):
        if not await guard(event):
            return
        cat = event.pattern_match.group(1).decode()
        topics = active_topics_for(event.sender_id)
        subj = user_subjects.get(event.sender_id, next((s for s in topics.keys() if s != "Notes"), next(iter(topics))))
        titles = {
            "topic_wise": "📂 Topic-Wise Q-Bank PDFs",
            "pyqs": "🏛️ Previous Year Questions (PYQs)",
            "random": "🎲 Random / Mock Test MCQs",
        }
        await edit(
            event,
            f"📑 **{subj} — {titles.get(cat, 'MCQs')}**\n\nThis section is being updated. "
            "Use the CBT Q-Bank app for practice meanwhile.",
            [[Button.inline("⬅️ Back to MCQ Hub", data=b"mcq_hub")]]
        )

    return entity_box


# ============================================================
# TARGETED & GLOBAL BROADCAST ENGINE
# ============================================================

BROADCAST_TARGETS = [
    ("everyone", "👥 Everyone"),
    ("paid", "💎 All Paid Members"),
    ("year_1", "1️⃣ 1st Year"),
    ("year_2", "2️⃣ 2nd Year"),
    ("year_3", "3️⃣ 3rd Year"),
    ("final_year", "🎓 Final Year"),
    ("demo", "🧪 Demo Users"),
]


def get_broadcast_audience(target):
    ids = set()
    if target == "everyone":
        ids = {int(u) for u in db.get("users", {})}
    elif target == "paid":
        ids = {int(u) for u in db.get("approved", [])}
    elif target == "demo":
        ids = {int(u) for u in db.get("demo_sessions", {})}
    else:
        for uid in db.get("approved", []):
            tier = db.get("approved_details", {}).get(str(uid), {}).get("tier", "all")
            if tier in (target, "all"):
                ids.add(int(uid))
        for u, info in db.get("users", {}).items():
            if info.get("bot_used") == target:
                ids.add(int(u))
    ids -= set(db.get("banned", []))
    ids.discard(ADMIN_ID)
    return sorted(ids)


async def execute_broadcast(payload, target="everyone", is_raw_event=False):
    audience = get_broadcast_audience(target)
    sent = failed = 0
    text_body = None if (is_raw_event and payload.media) else (payload.text if is_raw_event else str(payload))
    media_bytes = None
    media_name = "file"
    if is_raw_event and payload.media:
        try:
            media_bytes = await payload.download_media(file=bytes)
            if payload.file and payload.file.name:
                media_name = payload.file.name
            elif payload.photo:
                media_name = "photo.jpg"
        except Exception:
            logging.exception("Failed downloading broadcast media")

    for target_uid in audience:
        udata = db.get("users", {}).get(str(target_uid), {})
        pref = udata.get("bot_used")
        bots = [active_bots[pref]] if pref in active_bots else []
        bots += [b for k, b in active_bots.items() if k != pref]
        if manager_bot_client:
            bots.append(manager_bot_client)

        delivered = False
        for client in bots:
            try:
                if media_bytes:
                    f = io.BytesIO(media_bytes)
                    f.name = media_name
                    await client.send_file(target_uid, file=f, caption=payload.text or "")
                else:
                    await client.send_message(target_uid, f"📢 **MBBS Announcement:**\n\n{text_body}")
                delivered = True
                break
            except FloodWaitError as e:
                await asyncio.sleep(min(e.seconds, 30) + 1)
            except Exception:
                continue

        if delivered:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.06)
    return sent, failed, len(audience)


# ============================================================
# MANAGER BOT (UNIFIED ADMIN CONTROL PANEL)
# ============================================================

def paid_counts():
    paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
    qb = sum(1 for u in paid if db["approved_details"].get(str(u), {}).get("content_tier") == "full")
    return len(paid), qb, len(paid) - qb


def pending_list():
    res = []
    for u_str, u_data in db.get("users", {}).items():
        uid = int(u_str)
        if uid == ADMIN_ID or is_banned(uid) or uid in db.get("approved", []):
            continue
        p = db.get("pending", {}).get(u_str, {})
        if p.get("rejected"):
            continue
        res.append((u_str, u_data))
    return res


def dashboard_text():
    paid, qb, lec = paid_counts()
    pend_count = len(pending_list())
    cloud_badge = "🟢 Connected" if _cloud_ok else ("🟡 Local + Chat Backup" if not SUPABASE_SERVICE_KEY else "🔴 Offline")
    return (
        "🎛️ **MBBS Management Control Center**\n\n"
        f"🤖 **Managed Bots Online:** `{len(active_bots)}` bots\n"
        f"☁️ **Database Status:** {cloud_badge}\n"
        f"👥 **Total Registered Students:** `{len(db.get('users', {}))}`\n"
        f"⏳ **Pending Access Requests:** `{pend_count}`\n"
        f"💎 **Verified Paid Members:** `{paid}`\n"
        f"  └ 🩺 Full (Lectures + Notes + Q-Bank): `{qb}`\n"
        f"  └ 📚 Lectures & Notes Only: `{lec}`\n"
        f"🧪 **Demo Sessions:** `{len(db.get('demo_sessions', {}))}` | 🚫 **Banned:** `{len(db.get('banned', []))}`\n\n"
        "Select an administrative action below:"
    )


def make_manager_menu():
    pend_count = len(pending_list())
    paid_total, _, _ = paid_counts()
    return [
        [Button.inline(f"⏳ Pending Requests ({pend_count})", data=b"mgmt_pending"),
         Button.inline(f"💎 Verified Members ({paid_total})", data=b"mgmt_approved_p:0")],
        [Button.inline("👥 Registered Users", data=b"mgmt_users_p:0"),
         Button.inline("🔍 Find / Search Student", data=b"mgmt_find")],
        [Button.inline("📊 System Stats", data=b"mgmt_stats"),
         Button.inline("⚙️ Feature Toggles", data=b"mgmt_toggles")],
        [Button.inline("📢 Broadcast Center", data=b"mgmt_announce"),
         Button.inline("🧪 Demo Trial Control", data=b"mgmt_demo")],
        [Button.inline("🟢 Alert: Server Online", data=b"mgmt_alert_online"),
         Button.inline("🔴 Alert: Server Down", data=b"mgmt_alert_down")],
        [Button.inline("☁️ Cloud Backup Now", data=b"mgmt_do_backup"),
         Button.inline("🔄 Refresh Dashboard", data=b"mgmt_home")],
    ]


def make_toggles_menu():
    s = db["settings"]
    on = lambda k: "🟢 ON" if s.get(k) else "🔴 OFF"
    cur_lim = s.get("daily_limit_max", 30)
    limit = f"🟢 ON ({cur_lim}/d)" if s.get("daily_limit_enabled") else "🔴 OFF"
    return [
        [Button.inline(f"⏳ Subscription Expiry: {on('expiry_enabled')}", data=b"tog:expiry_enabled")],
        [Button.inline(f"🎓 Year-Lock Tier: {on('tier_access_enabled')}", data=b"tog:tier_access_enabled")],
        [Button.inline(f"🛡️ Anti-Leech Limit: {limit}", data=b"tog:daily_limit_enabled")],
        [Button.inline(("• " if cur_lim == n else "") + f"{n}/day", data=f"lim:{n}".encode()) for n in (15, 30, 50, 100)],
        [Button.inline(f"☁️ Cloud Auto-Sync: {on('cloud_backup_enabled')}", data=b"tog:cloud_backup_enabled")],
        [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")],
    ]


def make_student_profile_view(uid):
    uid = int(uid)
    s_uid = str(uid)
    u = db.get("users", {}).get(s_uid, {})
    det = db.get("approved_details", {}).get(s_uid, {})
    name = display_name(uid)
    uname = f"@{u['username']}" if u.get("username") else "No username"
    approved = uid in db.get("approved", [])
    banned = is_banned(uid)

    if banned:
        status_str = "⛔ BANNED"
    elif approved:
        status_str = "⏰ EXPIRED" if is_expired(uid) else "💎 VERIFIED PAID"
    else:
        status_str = "⏳ UNVERIFIED / FREE"

    tier = det.get("tier", "all") if approved else "-"
    ctier = det.get("content_tier", "none") if approved else "-"
    expiry = det.get("expiry") or ("Lifetime" if approved else "-")
    qid = det.get("qbank_id", "—") if ctier == "full" else "—"
    qpass = det.get("qbank_pass", "—") if ctier == "full" else "—"

    text = (
        f"👤 **Student Profile — {esc(name)}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **User ID:** `{uid}`\n"
        f"🔗 **Username:** {esc(uname)}\n"
        f"📌 **Status:** **{status_str}**\n"
        f"🤖 **Bot Used:** `{u.get('bot_used', 'all')}`\n"
        f"🎓 **Year Tier:** **{TIER_LABELS.get(tier, tier)}**\n"
        f"📦 **Content Plan:** **{CONTENT_LABELS.get(ctier, ctier)}**\n"
        f"📅 **Valid Till:** `{expiry}`\n"
        f"🔑 **Q-Bank Login:** `{qid}` | Pass: `{qpass}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = [
        [Button.inline("🩺 Set Full (Lec+Notes+QBank)", data=f"adm_set_tier:{uid}:full".encode()),
         Button.inline("📚 Set Lectures Only", data=f"adm_set_tier:{uid}:lectures_only".encode())],
        [Button.inline("🎓 Change Year Tier / Custom Plan", data=f"pc:{uid}".encode())],
        [Button.inline("➕ +30 Days", data=f"ex:{uid}:30".encode()),
         Button.inline("➕ +90 Days", data=f"ex:{uid}:90".encode()),
         Button.inline("➕ +1 Year", data=f"ex:{uid}:365".encode()),
         Button.inline("♾ Lifetime", data=f"ex:{uid}:0".encode())],
    ]
    if ctier == "full":
        buttons.append([Button.inline("🔑 Send Login Card", data=f"adm_send_cred:{uid}".encode()),
                        Button.inline("🔄 Reset Q-Bank Pass", data=f"adm_rst_pass:{uid}".encode())])
    action_row = []
    if approved:
        action_row.append(Button.inline("❌ Revoke Access", data=f"adm_rev:{uid}".encode()))
    if banned:
        action_row.append(Button.inline("✅ Unban User", data=f"adm_unban:{uid}".encode()))
    else:
        action_row.append(Button.inline("⛔ Ban User", data=f"adm_ban:{uid}".encode()))
    if action_row:
        buttons.append(action_row)
    buttons.append([Button.inline("💎 Verified List", data=b"mgmt_approved_p:0"),
                    Button.inline("⬅️ Main Menu", data=b"mgmt_home")])
    return text, buttons


def setup_manager_bot_handlers(client):
    back_menu = [[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]]

    def admin_only(event):
        return event.sender_id == ADMIN_ID

    @client.on(events.CallbackQuery(data=b"noop"))
    async def cb_mgmt_noop(event):
        await event.answer()

    @client.on(events.NewMessage(pattern=r"^/(start|panel|menu)$"))
    async def manager_start(event):
        if not admin_only(event):
            await event.respond("⛔ Access Denied.")
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await event.respond(dashboard_text(), buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_home"))
    async def cb_home(event):
        if not admin_only(event):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await edit(event, dashboard_text(), make_manager_menu())

    # ---------- Broadcast Center (Targeted & Global) ----------
    @client.on(events.CallbackQuery(data=b"mgmt_announce"))
    async def cb_announce(event):
        if not admin_only(event):
            return
        rows = []
        for i in range(0, len(BROADCAST_TARGETS), 2):
            row = []
            for k, lbl in BROADCAST_TARGETS[i:i + 2]:
                cnt = len(get_broadcast_audience(k))
                row.append(Button.inline(f"{lbl} ({cnt})", data=f"bc_target:{k}".encode()))
            rows.append(row)
        rows.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await edit(
            event,
            "📢 **Broadcast Center**\n\nSelect the target audience for your announcement:",
            rows
        )

    @client.on(events.CallbackQuery(pattern=rb"^bc_target:(.+)$"))
    async def cb_bc_target(event):
        if not admin_only(event):
            return
        target = event.pattern_match.group(1).decode()
        ADMIN_STATES[ADMIN_ID] = f"WAITING_BROADCAST:{target}"
        label = dict(BROADCAST_TARGETS).get(target, target)
        cnt = len(get_broadcast_audience(target))
        await edit(
            event,
            f"📢 **Broadcast Mode Activated**\n"
            f"🎯 **Target Audience:** {label} (`{cnt}` students)\n\n"
            "Send the message (text, photo, video, file, or forward) you want to broadcast now:",
            [[Button.inline("❌ Cancel Broadcast", data=b"mgmt_cancel_broadcast")]]
        )

    @client.on(events.CallbackQuery(data=b"mgmt_cancel_broadcast"))
    async def cb_cancel_broadcast(event):
        if not admin_only(event):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await event.answer("Broadcast canceled.", alert=True)
        await edit(event, dashboard_text(), make_manager_menu())

    # ---------- Find Student & State Listener ----------
    @client.on(events.CallbackQuery(data=b"mgmt_find"))
    async def cb_find(event):
        if not admin_only(event):
            return
        ADMIN_STATES[ADMIN_ID] = "WAITING_FIND_QUERY"
        await edit(
            event,
            "🔍 **Find / Search Student**\n\nSend the student's **Telegram ID**, **Name**, or **@username**:",
            [[Button.inline("❌ Cancel", data=b"mgmt_home")]]
        )

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def admin_state_and_restore_listener(event):
        if not admin_only(event):
            return
        text = (event.raw_text or "").strip()

        # Restore database from file upload
        if event.document and text.lower().startswith("/restore"):
            try:
                raw = await event.download_media(file=bytes)
                new_data = normalize_db(json.loads(raw.decode("utf-8")))
                db.clear()
                db.update(new_data)
                ensure_admin()
                save_db(db)
                await event.respond(
                    f"✅ **Database Restored Successfully!**\n"
                    f"👥 Users: `{len(db['users'])}` | 💎 Paid: `{len(db['approved'])}`",
                    buttons=make_manager_menu()
                )
            except Exception as e:
                await event.respond(f"❌ Restore failed: `{e}`")
            return

        if text.startswith("/"):
            return

        state = ADMIN_STATES.get(ADMIN_ID, "")
        if not state:
            return

        if state == "WAITING_FIND_QUERY":
            ADMIN_STATES.pop(ADMIN_ID, None)
            q = text.lstrip("@").lower()
            matches = []
            if q.isdigit() and len(q) >= 5:
                matches.append(int(q))
            for u_str, u_info in db.get("users", {}).items():
                hay = f"{u_info.get('first_name', '')} {u_info.get('last_name', '')} {u_info.get('username', '')} {u_str}".lower()
                if q in hay and int(u_str) not in matches:
                    matches.append(int(u_str))
            if not matches:
                await event.respond(
                    f"😕 No user found matching **`{esc(text)}`**.",
                    buttons=[[Button.inline("🔍 Search Again", data=b"mgmt_find"),
                              Button.inline("⬅️ Menu", data=b"mgmt_home")]]
                )
                return
            if len(matches) == 1:
                prof_text, prof_btns = make_student_profile_view(matches[0])
                await event.respond(prof_text, buttons=prof_btns)
                return
            rows = []
            for uid in matches[:12]:
                rows.append([Button.inline(f"👤 {display_name(uid)[:24]} ({uid})", data=f"adm_tier_opt:{uid}".encode())])
            rows.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
            await event.respond(f"🔍 **Found {len(matches)} matching students:**", buttons=rows)
            return

        if state.startswith("WAITING_BROADCAST:"):
            target = state.split(":", 1)[1]
            ADMIN_STATES.pop(ADMIN_ID, None)
            label = dict(BROADCAST_TARGETS).get(target, target)
            status = await event.respond(f"⏳ **Broadcasting to {label}...**")
            sent, failed, total = await execute_broadcast(event.message, target=target, is_raw_event=True)
            await status.edit(
                f"✅ **Broadcast Completed ({label})!**\n\n"
                f"📬 Delivered: `{sent}`\n"
                f"❌ Failed/Blocked: `{failed}`\n"
                f"👥 Total Target: `{total}`",
                buttons=[[Button.inline("⬅️ Return to Dashboard", data=b"mgmt_home")]]
            )

    # ---------- Feature Toggles / Backup / Stats ----------
    @client.on(events.CallbackQuery(data=b"mgmt_toggles"))
    async def cb_toggles(event):
        if admin_only(event):
            await edit(event, "⚙️ **System Feature Controls (ON / OFF)**", make_toggles_menu())

    @client.on(events.CallbackQuery(pattern=rb"^tog:(.+)$"))
    async def cb_toggle_switch(event):
        if not admin_only(event):
            return
        key = event.pattern_match.group(1).decode()
        if key in db["settings"]:
            db["settings"][key] = not db["settings"][key]
            save_db(db)
            await event.answer(f"{key} is now {'ON' if db['settings'][key] else 'OFF'}!", alert=True)
            if key == "demo_auto_start":
                await cb_demo_panel(event)
            else:
                await edit(event, "⚙️ **System Feature Controls (ON / OFF)**", make_toggles_menu())

    @client.on(events.CallbackQuery(pattern=rb"^lim:(\d+)$"))
    async def cb_set_limit(event):
        if not admin_only(event):
            return
        val = int(event.pattern_match.group(1))
        db["settings"]["daily_limit_max"] = val
        save_db(db)
        await event.answer(f"Daily limit set to {val}/day!", alert=True)
        await edit(event, "⚙️ **System Feature Controls (ON / OFF)**", make_toggles_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_do_backup"))
    async def cb_do_backup(event):
        if not admin_only(event):
            return
        await event.answer("Dispatching cloud backup to chat...")
        await trigger_cloud_backup(force=True)
        if _cloud_ok:
            await cloud_save_db()
        await edit(event, "✅ **Cloud backup dispatched!** `bot_database.json` was sent to this chat.", back_menu)

    @client.on(events.CallbackQuery(data=b"mgmt_stats"))
    async def cb_stats(event):
        if not admin_only(event):
            return
        paid, qb, lec = paid_counts()
        up = int(time.time() - START_TIME)
        synced = sum(1 for d in db["approved_details"].values() if str(d.get("qb_state", "")).startswith("on"))
        today = datetime.now().strftime("%Y-%m-%d")
        dl_today = sum(db.get("daily_downloads", {}).get(today, {}).values())
        await edit(
            event,
            "📊 **Live System Analytics**\n\n"
            f"👥 **Total Registered Students:** `{len(db.get('users', {}))}`\n"
            f"💎 **Verified Paid:** `{paid}`\n"
            f"  └ 🩺 Full (Lectures + Notes + Q-Bank): `{qb}`\n"
            f"  └ 📚 Lectures & Notes Only: `{lec}`\n"
            f"🔑 **Q-Bank Logins Live on Portal:** `{synced}`\n"
            f"🧪 **Demo Sessions Recorded:** `{len(db.get('demo_sessions', {}))}`\n"
            f"📥 **Lectures Downloaded Today:** `{dl_today}`\n"
            f"🚫 **Blocked Users:** `{len(db.get('banned', []))}`\n"
            f"⏱️ **Server Uptime:** `{up // 3600}h {(up % 3600) // 60}m {up % 60}s`\n\n"
            f"🤖 **Connected Active Bots:** `{len(active_bots)}` online",
            back_menu
        )

    @client.on(events.CallbackQuery(data=b"mgmt_demo"))
    async def cb_demo_panel(event):
        if not admin_only(event):
            return
        s = db["settings"]
        dur = s.get("demo_duration_mins", 10)
        dl = s.get("demo_max_downloads", 2)
        yr_tier = s.get("demo_year_tier", "all")
        auto = "🟢 ON" if s.get("demo_auto_start", True) else "🔴 OFF"
        yr_desc = "Student Chooses Year (1st/2nd/3rd/Final)" if yr_tier == "all" else f"Locked to {TIER_LABELS.get(yr_tier, yr_tier)}"
        rows = [
            [Button.inline(("• " if dur == m else "") + f"{m}m", data=f"dm_dur:{m}".encode()) for m in (5, 10, 15, 30)],
            [Button.inline(("• " if dl == n else "") + f"{n} files", data=f"dm_dl:{n}".encode()) for n in (1, 2, 3, 5)],
            [Button.inline(("• " if yr_tier == "all" else "") + "🎓 Student Picks Year", data=b"dm_yr:all")],
            [Button.inline(("• " if yr_tier == t else "") + TIER_LABELS[t], data=f"dm_yr:{t}".encode())
             for t in ("year_1", "year_2")],
            [Button.inline(("• " if yr_tier == t else "") + TIER_LABELS[t], data=f"dm_yr:{t}".encode())
             for t in ("year_3", "final_year")],
            [Button.inline(f"▶️ Auto-Start Demo on /start: {auto}", data=b"tog:demo_auto_start")],
            [Button.inline(f"👥 View Demo Users ({len(db.get('demo_sessions', {}))})", data=b"mgmt_demo_users")],
            [Button.inline("🗑️ Clear Expired Demo Sessions", data=b"mgmt_demo_clear")],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")],
        ]
        await edit(
            event,
            f"🧪 **Demo Bot Configuration**\n\n"
            f"• **Trial Duration:** `{dur} minutes`\n"
            f"• **Max Downloads:** `{dl} files`\n"
            f"• **Demo Year Mode:** `{yr_desc}`\n"
            f"• **Auto-Start:** {auto}\n\n"
            "💡 *Tip: Keep '🎓 Student Picks Year' selected so students choose 1st/2nd/3rd/Final Year first, or tap a specific year to lock the Demo Bot to that year:*",
            rows
        )

    @client.on(events.CallbackQuery(pattern=rb"^dm_dur:(\d+)$"))
    async def cb_dm_dur(event):
        if not admin_only(event):
            return
        db["settings"]["demo_duration_mins"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_demo_panel(event)

    @client.on(events.CallbackQuery(pattern=rb"^dm_dl:(\d+)$"))
    async def cb_dm_dl(event):
        if not admin_only(event):
            return
        db["settings"]["demo_max_downloads"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_demo_panel(event)

    @client.on(events.CallbackQuery(pattern=rb"^dm_yr:(\w+)$"))
    async def cb_dm_yr(event):
        if not admin_only(event):
            return
        yr = event.pattern_match.group(1).decode()
        if yr in TIER_LABELS:
            db["settings"]["demo_year_tier"] = yr
            save_db(db)
            lbl = "Student Picks Year" if yr == "all" else f"Locked to {TIER_LABELS[yr]}"
            await event.answer(f"Demo Year Mode: {lbl}", alert=True)
        await cb_demo_panel(event)

    @client.on(events.CallbackQuery(data=b"mgmt_demo_clear"))
    async def cb_demo_clear(event):
        if not admin_only(event):
            return
        removed = 0
        for u in list(db.get("demo_sessions", {}).keys()):
            if check_demo_status(u)[0] == "expired":
                db["demo_sessions"].pop(u, None)
                user_demo_years.pop(int(u), None)
                removed += 1
        _write_db(db)
        await event.answer(f"Cleared {removed} expired demo sessions!", alert=True)
        await cb_demo_panel(event)

    @client.on(events.CallbackQuery(data=b"mgmt_demo_users"))
    async def cb_demo_users(event):
        if not admin_only(event):
            return
        sessions = list(db.get("demo_sessions", {}).items())
        if not sessions:
            await edit(event, "ℹ️ **No demo sessions recorded yet.**", [[Button.inline("⬅️ Back", data=b"mgmt_demo")]])
            return
        msg = f"🧪 **Recent Demo Users ({len(sessions)}):**\n\n"
        buttons = []
        for uid_str, sess in sessions[-8:]:
            st, rem, used, mx = check_demo_status(uid_str)
            name = display_name(uid_str)
            sel_yr = sess.get("selected_year") or sess.get("year_tier") or "all"
            yr_lbl = TIER_SHORT.get(sel_yr, "All")
            msg += f"• **{esc(name)}** (`{uid_str}`) — `{yr_lbl}` | `{st}` ({fmt_secs(rem)} left, {used}/{mx} dl)\n"
            buttons.append([
                Button.inline(f"🔄 Reset {name[:8]}", data=f"dm_rst:{uid_str}".encode()),
                Button.inline("⏱ +5m", data=f"dm_ext:{uid_str}:t".encode()),
                Button.inline("📥 +1dl", data=f"dm_ext:{uid_str}:d".encode()),
                Button.inline("⚡ Full", data=f"adm_app_full:{uid_str}".encode()),
            ])
        buttons.append([Button.inline("⬅️ Back to Demo Settings", data=b"mgmt_demo")])
        await edit(event, msg, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^dm_ext:(\d+):([td])$"))
    async def cb_dm_ext(event):
        if not admin_only(event):
            return
        uid_str = event.pattern_match.group(1).decode()
        mode = event.pattern_match.group(2).decode()
        sess = db.get("demo_sessions", {}).get(uid_str)
        if sess:
            if mode == "t":
                if check_demo_status(uid_str)[0] == "expired":
                    sess["start_time"] = time.time()
                    sess["duration_mins"] = 5
                else:
                    sess["duration_mins"] = sess.get("duration_mins", 10) + 5
                await event.answer("Added +5 minutes to demo!", alert=True)
            else:
                sess["max_downloads"] = sess.get("max_downloads", 2) + 1
                await event.answer("Added +1 file download to demo!", alert=True)
            _write_db(db)
        await cb_demo_users(event)

    @client.on(events.CallbackQuery(pattern=rb"^dm_rst:(\d+)$"))
    async def cb_dm_rst(event):
        if not admin_only(event):
            return
        uid = event.pattern_match.group(1).decode()
        db["demo_sessions"].pop(uid, None)
        user_demo_years.pop(int(uid), None)
        _write_db(db)
        await send_via_any(int(uid), "🎁 **Your free demo has been reset by the admin!** Send /start to begin again.", pref="demo")
        await event.answer("Demo reset!", alert=True)
        await cb_demo_users(event)

    # ---------- Registered Users / Verified Members / Pending Lists ----------
    @client.on(events.CallbackQuery(pattern=rb"^mgmt_users_p:(\d+)$"))
    async def cb_users_page(event):
        if not admin_only(event):
            return
        users = list(db.get("users", {}).items())
        if not users:
            await edit(event, "ℹ️ **No registered students yet.**", back_menu)
            return
        per = 6
        pages = max(1, (len(users) + per - 1) // per)
        page = max(0, min(int(event.pattern_match.group(1)), pages - 1))
        msg = f"👥 **Registered Students ({len(users)}) — Page {page + 1}/{pages}:**\n\n"
        buttons = []
        for uid_str, u in users[page * per:(page + 1) * per]:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Student"
            uname = f"@{u['username']}" if u.get("username") else "No username"
            approved = int(uid_str) in db.get("approved", [])
            tier = db["approved_details"].get(uid_str, {}).get("content_tier") if approved else None
            badge = "🩺 Full" if tier == "full" else ("📚 Lec" if tier == "lectures_only" else "⏳ Free")
            msg += f"• **{esc(name)}** ({esc(uname)})\n  └ ID: `{uid_str}` | Plan: **{badge}** | Bot: `{u.get('bot_used', 'all')}`\n\n"
            if not approved:
                buttons.append([Button.inline(f"⚡ Full {name[:10]}", data=f"adm_app_full:{uid_str}".encode()),
                                Button.inline("📚 Lec", data=f"adm_app_lec:{uid_str}".encode()),
                                Button.inline("⚙️", data=f"adm_tier_opt:{uid_str}".encode())])
            else:
                buttons.append([Button.inline(f"⚙️ Manage {name[:14]}", data=f"adm_tier_opt:{uid_str}".encode())])
        nav = []
        if page > 0:
            nav.append(Button.inline("◀ Prev", data=f"mgmt_users_p:{page - 1}".encode()))
        if page < pages - 1:
            nav.append(Button.inline("Next ▶", data=f"mgmt_users_p:{page + 1}".encode()))
        if nav:
            buttons.append(nav)
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await edit(event, msg, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^mgmt_approved_p:(\d+)$"))
    async def cb_approved_page(event):
        if not admin_only(event):
            return
        paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
        if not paid:
            await edit(event, "ℹ️ **No verified paid students found yet.**", back_menu)
            return
        per = 6
        pages = max(1, (len(paid) + per - 1) // per)
        page = max(0, min(int(event.pattern_match.group(1)), pages - 1))
        msg = f"💎 **Verified Paid Members ({len(paid)}) — Page {page + 1}/{pages}:**\n\n"
        buttons = []
        for uid in paid[page * per:(page + 1) * per]:
            s = str(uid)
            u = db.get("users", {}).get(s, {})
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or f"User {uid}"
            uname = f"@{u['username']}" if u.get("username") else "No username"
            det = db.get("approved_details", {}).get(s, {})
            full = det.get("content_tier") == "full"
            yr = TIER_SHORT.get(det.get("tier", "all"), "All")
            msg += (f"• **{esc(name)}** ({esc(uname)})\n  └ ID: `{uid}` | **{yr}** | **{'🩺 Full' if full else '📚 Lec Only'}** "
                    f"| Q-ID: `{det.get('qbank_id', '—') if full else '—'}`\n\n")
            buttons.append([Button.inline(f"✏️ Manage {name[:12]}", data=f"adm_tier_opt:{uid}".encode()),
                            Button.inline("❌ Revoke", data=f"adm_rev:{uid}".encode())])
        nav = []
        if page > 0:
            nav.append(Button.inline("◀ Prev", data=f"mgmt_approved_p:{page - 1}".encode()))
        if page < pages - 1:
            nav.append(Button.inline("Next ▶", data=f"mgmt_approved_p:{page + 1}".encode()))
        if nav:
            buttons.append(nav)
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await edit(event, msg, buttons)

    @client.on(events.CallbackQuery(data=b"mgmt_pending"))
    async def cb_pending(event):
        if not admin_only(event):
            return
        pending = pending_list()
        if not pending:
            await edit(event, "✅ **No pending access requests!**", back_menu)
            return
        msg = f"⏳ **Pending Verification Requests ({len(pending)}):**\n\n"
        buttons = []
        for uid, u in pending[-8:]:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Student"
            bot_used = u.get("bot_used", "all")
            msg += f"• **{esc(name)}** (`{uid}`) — Bot: `{bot_used}`\n"
            buttons.append([
                Button.inline(f"⚡ Full {name[:10]}", data=f"adm_app_full:{uid}".encode()),
                Button.inline("📚 Lec", data=f"adm_app_lec:{uid}".encode()),
                Button.inline("✏️", data=f"pc:{uid}".encode()),
                Button.inline("❌", data=f"rj:{uid}".encode()),
            ])
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await edit(event, msg, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_app_full:(\d+)$"))
    async def cb_app_full(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        det = grant_plan(target, "full")
        qid, qpass = get_or_create_qbank_creds(target)
        await event.answer("✅ Full Access Granted!", alert=True)
        await edit(
            event,
            f"✅ User `{target}` (**{esc(display_name(target))}**) granted **Full Access (Lectures + Notes + Q-Bank)**!\n\n"
            f"🎓 Year Tier: **{TIER_LABELS.get(det.get('tier', 'all'))}**\n"
            f"🆔 Student ID: `{qid}`\n🔑 Password: `{qpass}`\n\n"
            "_The login card is being sent to the student and activated on the portal._",
            [[Button.inline("👤 View Profile", data=f"adm_tier_opt:{target}".encode()),
              Button.inline("⬅️ Menu", data=b"mgmt_home")]]
        )
        await send_via_any(
            target,
            "🎉 **Access Activated!**\n\nYour account has been enrolled in **MBBS Full Access (Video Lectures, Notes & CBT Q-Bank)**.\nSend /start to begin!"
        )
        await reconcile_now()
        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^adm_app_lec:(\d+)$"))
    async def cb_app_lec(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        grant_plan(target, "lectures_only")
        await event.answer("✅ Lectures Only Granted!", alert=True)
        await edit(
            event,
            f"✅ User `{target}` (**{esc(display_name(target))}**) enrolled in **Lectures & Notes Only**.\n(No Q-Bank login issued).",
            [[Button.inline("👤 View Profile", data=f"adm_tier_opt:{target}".encode()),
              Button.inline("⬅️ Menu", data=b"mgmt_home")]]
        )
        await send_via_any(
            target,
            "🎉 **Access Granted!**\n\nYour account has been enrolled in **MBBS Video Lectures & Notes**.\nSend /start to begin studying!"
        )
        await reconcile_now()
        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^adm_tier_opt:(\d+)$"))
    async def cb_tier_options(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        text, buttons = make_student_profile_view(uid)
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_set_tier:(\d+):([a-z_]+)$"))
    async def cb_apply_tier(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        tier = event.pattern_match.group(2).decode()
        if tier not in ("full", "lectures_only"):
            return
        grant_plan(uid, tier)
        await event.answer("✅ Plan updated!", alert=True)
        await reconcile_now()
        text, buttons = make_student_profile_view(uid)
        await edit(event, text, buttons)
        await trigger_cloud_backup()

    # Custom 3-Step Plan Wizard (Year -> Content -> Duration)
    @client.on(events.CallbackQuery(pattern=rb"^pc:(\d+)$"))
    async def cb_custom_step1(event):
        if not admin_only(event):
            return
        uid = event.pattern_match.group(1).decode()
        keys = list(TIER_LABELS.keys())
        rows = [[Button.inline(TIER_LABELS[k], data=f"pt:{uid}:{k}".encode()) for k in keys[i:i + 2]]
                for i in range(0, len(keys), 2)]
        rows.append([Button.inline("⬅️ Cancel", data=f"adm_tier_opt:{uid}".encode())])
        await edit(event, f"✏️ **Custom Plan for `{uid}` ({esc(display_name(uid))})**\n\n**Step 1/3:** Choose the **Year Tier**:", rows)

    @client.on(events.CallbackQuery(pattern=rb"^pt:(\d+):(\w+)$"))
    async def cb_custom_step2(event):
        if not admin_only(event):
            return
        uid, yr = event.pattern_match.group(1).decode(), event.pattern_match.group(2).decode()
        rows = [
            [Button.inline("🩺 Full (Lectures + Notes + Q-Bank)", data=f"pk:{uid}:{yr}:f".encode())],
            [Button.inline("📚 Lectures & Notes Only", data=f"pk:{uid}:{yr}:l".encode())],
            [Button.inline("⬅️ Back", data=f"pc:{uid}".encode())],
        ]
        await edit(event, f"✏️ **Step 2/3 — {TIER_LABELS.get(yr, yr)}**\n\nChoose the **Content Plan**:", rows)

    @client.on(events.CallbackQuery(pattern=rb"^pk:(\d+):(\w+):([fl])$"))
    async def cb_custom_step3(event):
        if not admin_only(event):
            return
        uid, yr, c = event.pattern_match.group(1).decode(), event.pattern_match.group(2).decode(), event.pattern_match.group(3).decode()
        b = lambda d, lbl: Button.inline(lbl, data=f"pd:{uid}:{yr}:{c}:{d}".encode())
        rows = [
            [b(30, "30 Days"), b(90, "90 Days")],
            [b(180, "180 Days"), b(365, "1 Year")],
            [b(0, "♾ Lifetime")],
            [Button.inline("⬅️ Back", data=f"pt:{uid}:{yr}".encode())],
        ]
        await edit(event, "✏️ **Step 3/3 — Subscription Duration:**", rows)

    @client.on(events.CallbackQuery(pattern=rb"^pd:(\d+):(\w+):([fl]):(\d+)$"))
    async def cb_custom_finish(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        yr = event.pattern_match.group(2).decode()
        content = "full" if event.pattern_match.group(3).decode() == "f" else "lectures_only"
        days = int(event.pattern_match.group(4))
        grant_plan(uid, content_tier=content, tier=yr, days=days)
        await event.answer("✅ Custom Plan Activated!", alert=True)
        await send_via_any(
            uid,
            f"🎉 **Subscription Activated!**\n\n"
            f"🎓 **Year:** {TIER_LABELS.get(yr, yr)}\n"
            f"📦 **Plan:** {CONTENT_LABELS.get(content)}\n"
            f"📅 **Validity:** {'Lifetime' if days == 0 else f'{days} days'}\n\n"
            "Send /start to open your study library!"
        )
        await reconcile_now()
        text, buttons = make_student_profile_view(uid)
        await edit(event, text, buttons)
        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^ex:(\d+):(\d+)$"))
    async def cb_extend_sub(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        days = int(event.pattern_match.group(2))
        det = db["approved_details"].setdefault(str(uid), {})
        if days == 0:
            det["expiry"] = None
            await event.answer("Set to Lifetime!", alert=True)
        else:
            base = datetime.now().date()
            if det.get("expiry"):
                try:
                    base = max(base, datetime.strptime(det["expiry"], "%Y-%m-%d").date())
                except Exception:
                    pass
            det["expiry"] = (base + timedelta(days=days)).strftime("%Y-%m-%d")
            await event.answer(f"Extended by +{days} days!", alert=True)
        if uid not in db["approved"]:
            db["approved"].append(uid)
        save_db(db)
        await reconcile_now()
        text, buttons = make_student_profile_view(uid)
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_send_cred:(\d+)$"))
    async def cb_send_cred(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        ok = await send_login_card(uid, uid)
        await event.answer("Login card sent!" if ok else "Could not reach user.", alert=True)

    @client.on(events.CallbackQuery(pattern=rb"^adm_rst_pass:(\d+)$"))
    async def cb_rst_pass(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        get_or_create_qbank_creds(uid)
        det = db["approved_details"][str(uid)]
        det["qbank_pass"] = _pick(8)
        det["qb_state"] = None
        det["creds_sent"] = False
        _write_db(db)
        await reconcile_now()
        await event.answer("New Q-Bank password generated and sent!", alert=True)
        text, buttons = make_student_profile_view(uid)
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^rj:(\d+)$"))
    async def cb_reject(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        db["pending"][str(uid)] = {**db["pending"].get(str(uid), {}), "rejected": True}
        save_db(db)
        await send_via_any(uid, f"❌ Your access request could not be approved at this time.\nContact {OWNER_CONTACT} for assistance.")
        await event.answer("Request rejected.", alert=True)
        await edit(event, f"❌ Rejected request from `{uid}`.", back_menu)

    @client.on(events.CallbackQuery(pattern=rb"^adm_rev:(\d+)$"))
    async def cb_rev(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        if target in db.get("approved", []) and target != ADMIN_ID:
            db["approved"].remove(target)
            save_db(db)
            await reconcile_now()
            await trigger_cloud_backup()
        await event.answer("🔒 Access Revoked!", alert=True)
        text, buttons = make_student_profile_view(target)
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_ban:(\d+)$"))
    async def cb_ban(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        if target != ADMIN_ID and target not in db["banned"]:
            db["banned"].append(target)
        if target in db["approved"] and target != ADMIN_ID:
            db["approved"].remove(target)
        db["pending"].pop(str(target), None)
        save_db(db)
        await reconcile_now()
        await trigger_cloud_backup()
        await event.answer("⛔ User Banned!", alert=True)
        text, buttons = make_student_profile_view(target)
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_unban:(\d+)$"))
    async def cb_unban(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        if target in db["banned"]:
            db["banned"].remove(target)
            save_db(db)
        await event.answer("✅ User Unbanned!", alert=True)
        text, buttons = make_student_profile_view(target)
        await edit(event, text, buttons)

    # ---------- Server Status Alerts ----------
    async def alert_paid(event, notice, label):
        await event.answer("Sending notice...")
        sent = 0
        for uid in list(db.get("approved", [])):
            if uid == ADMIN_ID:
                continue
            if await send_via_any(uid, notice):
                sent += 1
            await asyncio.sleep(0.05)
        await edit(event, f"✅ **{label} notice delivered to `{sent}` paid students!**", back_menu)

    @client.on(events.CallbackQuery(data=b"mgmt_alert_online"))
    async def cb_online(event):
        if admin_only(event):
            await alert_paid(
                event,
                "🟢 **MBBS Platform Status: All Systems Operational**\n\nThe lecture streaming "
                "servers and CBT Q-Bank app are fully online. Happy studying!",
                "Server Online"
            )

    @client.on(events.CallbackQuery(data=b"mgmt_alert_down"))
    async def cb_down(event):
        if admin_only(event):
            await alert_paid(
                event,
                "🛠️ **Scheduled Maintenance Notice**\n\nWe are performing quick cloud updates "
                "to improve lecture delivery speeds. Services will be back shortly. Thank you!",
                "Maintenance"
            )


# ============================================================
# BACKGROUND LOOP & WEB SERVER
# ============================================================

async def background_loop():
    last_backup = time.time()
    while True:
        try:
            if SUPABASE_SERVICE_KEY and not _cloud_ok:
                await restore_db_from_cloud(retries=1, merge_local=True)
            await reconcile_now()
            if _cloud_ok:
                await cloud_save_db()
            if time.time() - last_backup >= BACKUP_INTERVAL_SECONDS:
                last_backup = time.time()
                await trigger_cloud_backup()
        except Exception:
            logging.exception("Background loop error")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


async def health_check(request):
    return web.json_response({
        "status": "MBBS Multi-Bot Production Engine is Online 24/7.",
        "uptime": int(time.time() - START_TIME),
        "cloud_db": _cloud_ok,
        "bots_online": len(active_bots),
    })


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Health-check web server listening on port %s", PORT)


# ============================================================
# MAIN STARTUP
# ============================================================

async def main():
    global USER_CLIENT_ID, manager_bot_client
    os.makedirs("downloads", exist_ok=True)
    await start_web_server()

    if SUPABASE_SERVICE_KEY:
        await restore_db_from_cloud()
    ensure_admin()

    logging.info("Starting Telegram user client...")
    await user_client.start()
    me = await user_client.get_me()
    USER_CLIENT_ID = me.id
    logging.info("User client connected as: %s (ID: %s)", me.first_name, me.id)

    runners = [user_client.run_until_disconnected()]

    for key, token in BOT_TOKENS.items():
        if not token:
            continue
        try:
            client = TelegramClient(f"bot_session_{key}", API_ID, API_HASH)
            await client.start(bot_token=token)
            bot_me = await client.get_me()

            if key == "manager":
                manager_bot_client = client
                setup_manager_bot_handlers(client)
                runners.append(client.run_until_disconnected())
                logging.info("Started [Management Bot] -> @%s", bot_me.username)
                continue

            entity = None
            try:
                entity = await user_client.get_entity(bot_me.username)
            except Exception:
                pass
            box = setup_bot_handlers(client, key, BOT_SUBJECTS_MAP[key], BOT_TITLES_MAP[key])
            box["entity"] = entity
            active_bots[key] = client
            runners.append(client.run_until_disconnected())
            logging.info("Started [%s] -> @%s", BOT_TITLES_MAP[key], bot_me.username)
        except Exception:
            logging.exception("Failed to start bot key: %s", key)

    if manager_bot_client:
        if not _cloud_ok:
            await auto_restore_from_telegram()
        try:
            paid, qb, lec = paid_counts()
            await manager_bot_client.send_message(
                ADMIN_ID,
                "🟢 **MBBS Multi-Bot Production System Online!**\n\n"
                f"• **Active Study Bots:** `{len(active_bots)}` online\n"
                f"• **User Client Connected:** `{me.first_name}`\n"
                f"• **Registered Students:** `{len(db.get('users', {}))}`\n"
                f"• **Verified Paid:** `{paid}` (`{qb}` Full | `{lec}` Lec Only)\n\n"
                "Lecture relays, Notes delivery, MCQ Hub, and Q-Bank portal sync are active.",
                buttons=make_manager_menu()
            )
        except Exception:
            pass

    asyncio.create_task(background_loop())
    schedule_reconcile()
    logging.info("All MBBS bots and the Management Control Bot are live.")
    await asyncio.gather(*runners)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("System shutting down.")
    except Exception:
        logging.exception("Fatal crash")
