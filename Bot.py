
import asyncio
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

# ============================================================
# CONFIGURATION (Set these as Render/Host environment variables)
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

# CBT student portal (GitHub Pages) and Supabase database integration
CBT_WEBAPP_BASE_URL = os.getenv("CBT_WEBAPP_BASE_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/index.html")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://iafqcssktvejitssqawi.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_I6SvDlS24OOid9g9DiA9qQ_jquGYE4C")

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
# SUBJECTS & CURRICULUM TOPICS PER YEAR
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
    "demo": TOPICS_ALL,  # Default demo topics (customizable via Manager)
}

BOT_TITLES_MAP = {
    "all": "MBBS Full Library (All Subjects)",
    "year_1": "MBBS 1st Year Library",
    "year_2": "MBBS 2nd Year Library",
    "year_3": "MBBS 3rd Year Library",
    "final_year": "MBBS 4th / Final Year Library",
    "demo": "MBBS Demo Trial Experience",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)

# ============================================================
# DATABASE & SETTINGS STORAGE
# ============================================================

DB_FILE = "bot_database.json"
DEFAULT_SETTINGS = {
    "expiry_enabled": False,
    "tier_access_enabled": False,
    "daily_limit_enabled": False,
    "daily_limit_max": 30,
    "cloud_backup_enabled": True,
    # Demo bot specific management settings
    "demo_duration_mins": 10,        # 5 to 10 mins trial duration
    "demo_max_downloads": 2,         # Strict 2 lecture downloads restriction
    "demo_year_tier": "all",         # Year library visible in demo: all, year_1, year_2, year_3, final_year
    "demo_auto_start": True,         # Instantly starts countdown when student opens /start
}

def load_db():
    data = {
        "users": {},
        "banned": [],
        "approved": [],
        "approved_details": {},
        "settings": DEFAULT_SETTINGS.copy(),
        "daily_downloads": {},
        "demo_sessions": {},          # Tracks demo user sessions and lecture quotas
    }

    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            logging.exception("Failed to read database file")

    if PAID_USERS_JSON_RAW:
        try:
            env = json.loads(PAID_USERS_JSON_RAW)
            if isinstance(env, dict):
                for uid, val in env.get("users", {}).items():
                    data["users"].setdefault(uid, val)
                for uid in env.get("approved", []):
                    if uid not in data["approved"]:
                        data["approved"].append(uid)
                for uid, val in env.get("approved_details", {}).items():
                    data["approved_details"].setdefault(uid, val)
                logging.info("Merged paid users from PAID_USERS_BACKUP.")
        except Exception:
            logging.exception("Failed parsing PAID_USERS_BACKUP")

    for k, v in DEFAULT_SETTINGS.items():
        data["settings"].setdefault(k, v)

    for key in ("users", "approved_details", "daily_downloads", "demo_sessions"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    for key in ("banned", "approved"):
        if not isinstance(data.get(key), list):
            data[key] = []

    for uid in data["approved"]:
        data["approved_details"].setdefault(str(uid), {
            "tier": "all", "content_tier": "full", "expiry": None,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return data

def _write_db(data):
    try:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DB_FILE)
    except Exception:
        logging.exception("Failed to write database file")


def save_db(data):
    _write_db(data)
    schedule_reconcile()


db = load_db()

if ADMIN_ID not in db["approved"]:
    db["approved"].append(ADMIN_ID)
    db["approved_details"][str(ADMIN_ID)] = {
        "tier": "all", "content_tier": "full", "expiry": None, "added_at": "SYSTEM"
    }
    _write_db(db)

# ============================================================
# Q-BANK & DEMO CREDENTIALS LOGIC
# ============================================================

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # Avoid confusing characters (0/O/1/I)


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


def display_name(uid):
    u = db.get("users", {}).get(str(uid), {})
    return (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username") or f"Candidate {uid}")

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
        "is_demo": is_demo, "active": active, "expires_at": expires_at
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(f"{SUPABASE_URL}/rest/v1/students?on_conflict=student_id",
                          headers=headers, data=json.dumps(row)) as r:
            if r.status >= 300:
                raise RuntimeError(f"Supabase {r.status}: {(await r.text())[:200]}")


_reconcile_lock = None
_reconcile_pending = False

async def send_login_card(chat_id, user_id, title="🎉 **Your CBT Q-Bank login is ready!**"):
    qid, pw = get_or_create_qbank_creds(user_id)
    text = (
        f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the interactive CBT app (auto-login).\n"
        "Send /mylogin any time to see this again."
    )
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))]]
    pref = db.get("users", {}).get(str(user_id), {}).get("bot_used")
    bots = [active_bots[pref]] if pref in active_bots else []
    bots += [b for k, b in active_bots.items() if k != pref]
    for bot in bots:
        try:
            await bot.send_message(chat_id, text, buttons=buttons)
            return True
        except Exception:
            continue
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
# DEMO SESSION ENGINE (5-10 MINS LIMIT & 2 DOWNLOADS RESTRICTION)
# ============================================================

def get_demo_topics():
    tier = db["settings"].get("demo_year_tier", "all")
    if tier in BOT_SUBJECTS_MAP:
        return BOT_SUBJECTS_MAP[tier]
    return TOPICS_ALL


def get_or_start_demo_session(user_id, user_name="Demo Candidate"):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    duration_mins = db["settings"].get("demo_duration_mins", 10)
    max_dl = db["settings"].get("demo_max_downloads", 2)
    now = time.time()

    if not session:
        cbt_id = "DEMO-" + _pick(4)
        cbt_pass = _pick(6)
        session = {
            "start_time": now,
            "duration_mins": duration_mins,
            "max_downloads": max_dl,
            "downloads_used": 0,
            "cbt_id": cbt_id,
            "cbt_pass": cbt_pass,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cbt_synced": False,
        }
        db["demo_sessions"][s_uid] = session
        _write_db(db)

    return session

def check_demo_status(user_id):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    if not session:
        return "new", 0, 0, 0

    now = time.time()
    elapsed = now - session["start_time"]
    total_allowed = session.get("duration_mins", 10) * 60
    remaining_secs = max(0, total_allowed - elapsed)
    dl_used = session.get("downloads_used", 0)
    dl_max = session.get("max_downloads", 2)

    if elapsed > total_allowed:
        return "expired", 0, dl_used, dl_max

    if dl_used >= dl_max:
        return "download_limit_reached", int(remaining_secs), dl_used, dl_max

    return "active", int(remaining_secs), dl_used, dl_max


def record_demo_download(user_id):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    if session:
        session["downloads_used"] = session.get("downloads_used", 0) + 1
        _write_db(db)

async def ensure_demo_cbt_synced(user_id, name="Demo Student"):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    if not session or session.get("cbt_synced"):
        return
    try:
        exp = (datetime.utcnow() + timedelta(minutes=session.get("duration_mins", 10) + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        await supabase_upsert_student(
            session["cbt_id"], session["cbt_pass"], f"Demo: {name}",
            active=True, expires_at=exp, is_demo=True
        )
        session["cbt_synced"] = True
        _write_db(db)
    except Exception as e:
        logging.warning("Could not sync demo CBT user %s: %s", user_id, e)

# ============================================================
# USER TRACKING & GLOBAL ACCESS CONTROL
# ============================================================

def track_user(user, bot_type):
    if not user:
        return
    uid = str(user.id)
    new = {
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
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
                    db["approved"].remove(uid)
                    save_db(db)
                    return False, "expired"
            except Exception:
                pass

    if db["settings"].get("tier_access_enabled", False):
        user_tier = details.get("tier", "all")
        if user_tier != "all" and user_tier != bot_type:
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
    for day in [d for d in db["daily_downloads"] if d < (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]:
        db["daily_downloads"].pop(day, None)
    day_map = db["daily_downloads"].setdefault(today, {})
    day_map[str(user_id)] = day_map.get(str(user_id), 0) + 1
    _write_db(db)


LOCKED_MESSAGE = (
    "🔒 **Access Restricted**\n\n"
    "This is a verified educational bot. Limited users have access to these resources.\n"
    f"To enroll or activate your subscription, contact {OWNER_CONTACT}\n\n"
    "Send your **User ID** to get verified:\n`{user_id}`"
)

# ============================================================
# CLIENT INSTANCES & APPLICATION RUNTIME
# ============================================================

user_client = TelegramClient("session", API_ID, API_HASH)
active_bots = {}
manager_bot_client = None
USER_CLIENT_ID = None
START_TIME = time.time()

user_subjects = {}
user_units = {}
TOPIC_CACHE = {}
TOPIC_CACHE_TTL = 600

relay_lock = asyncio.Lock()
active_relay_future = None
ADMIN_STATES = {}

# ============================================================
# CLOUD BACKUP & ADMIN NOTIFICATIONS
# ============================================================

async def trigger_cloud_backup(force=False):
    if not manager_bot_client or not (force or db["settings"].get("cloud_backup_enabled", True)):
        return
    try:
        if os.path.exists(DB_FILE):
            await manager_bot_client.send_file(
                ADMIN_ID, DB_FILE,
                caption=("☁️ **Auto-Sync Cloud Backup**\n"
                         f"📅 Date: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                         f"👥 Registered: `{len(db.get('users', {}))}` | 💎 Paid: `{len(db.get('approved', []))}`\n"
                         f"🧪 Demo Trials: `{len(db.get('demo_sessions', {}))}`"))
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
                                 or (msg.text and "Auto-Sync Cloud Backup" in msg.text)):
                    await msg.download_media(file=DB_FILE)
                    db = load_db()
                    logging.info("Restored database from chat backup.")
                    await manager_bot_client.send_message(
                        ADMIN_ID, "🔄 **Cloud Database Auto-Restored Successfully from Chat!**")
                    break
    except Exception:
        logging.exception("Auto-restore from Telegram failed")

async def notify_manager_new_request(user, bot_type):
    if not manager_bot_client:
        return
    try:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Student"
        username = f"@{user.username}" if user.username else "No username"
        text = (f"🔔 **New Student Access Request!**\n\n👤 **Student:** {name} ({username})\n"
                f"🆔 **User ID:** `{user.id}`\n🤖 **Bot Selected:** `{bot_type}`\n"
                f"🕒 **Time:** `{datetime.now().strftime('%H:%M:%S')}`")
        buttons = [
            [Button.inline("⚡ Full (Lec + Notes + Q-Bank)", data=f"adm_app_full:{user.id}".encode()),
             Button.inline("📚 Lectures Only", data=f"adm_app_lec:{user.id}".encode())],
            [Button.inline("🧪 Reset / Grant Demo", data=f"adm_demo_grant:{user.id}".encode()),
             Button.inline("⛔ Ban", data=f"adm_ban:{user.id}".encode())],
        ]
        await manager_bot_client.send_message(ADMIN_ID, text, buttons=buttons)
    except Exception:
        logging.exception("Failed to dispatch manager alert")


async def background_loop():
    """Periodic Supabase sync + cloud backup."""
    last_backup = time.time()
    while True:
        try:
            await reconcile_now()
            if time.time() - last_backup >= BACKUP_INTERVAL_SECONDS:
                last_backup = time.time()
                await trigger_cloud_backup()
        except Exception:
            logging.exception("Background loop error")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)

# ============================================================
# WEB SERVER FOR HOST HEALTH CHECKS
# ============================================================

async def health_check(request):
    return web.Response(text="MBBS Multi-Bot & Demo Engine is Online 24/7.")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Health-check web server listening on port %s", PORT)

# ============================================================
# UI MENUS GENERATOR
# ============================================================

async def edit(event, text, buttons=None):
    try:
        await event.edit(text, buttons=buttons)
    except MessageNotModifiedError:
        pass


def make_main_menu(topics, user_id=None, is_demo=False):
    subjects = list(topics.keys())
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(subjects[i], data=f"sub:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(subjects[i + 1], data=f"sub:{i + 1}".encode()))
        buttons.append(row)

    if is_demo:
        session = db["demo_sessions"].get(str(user_id), {})
        cbt_id = session.get("cbt_id")
        cbt_pw = session.get("cbt_pass")
        if cbt_id and cbt_pw:
            url = generate_demo_webapp_url(cbt_id, cbt_pw)
            buttons.append([Button.url("🧪 Test CBT Q-Bank App (Demo)", url)])
        buttons.append([Button.url("💎 Enroll Now / Get Full Plan", f"https://t.me/{OWNER_CONTACT.lstrip('@')}")])
    elif user_id is not None and has_qbank(user_id):
        buttons.append([Button.inline("🔑 My CBT Q-Bank Login", data=b"mylogin")])
    return buttons


def make_subject_menu():
    return [
        [Button.inline("📚 Video Lectures", data=b"lectures"), Button.inline("📝 Notes & PDFs", data=b"notes")],
        [Button.inline("🎯 High-Yield MCQ Hub", data=b"mcq_hub")],
        [Button.inline("⬅️ All Subjects", data=b"home")],
    ]

def make_mcq_hub_menu(user_id, is_demo=False):
    if is_demo:
        session = db["demo_sessions"].get(str(user_id), {})
        cbt_btn = Button.url(
            "🧪 Launch Demo CBT Q-Bank",
            generate_demo_webapp_url(session.get("cbt_id", ""), session.get("cbt_pass", ""))
        )
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
    text = (message.text or "").strip()
    if text:
        clean = re.sub(r"#\w+", "", text.splitlines()[0]).strip()
        if clean:
            return clean
    return f"Lecture {number}"

# ============================================================
# TOPIC FETCHER & RELAY ENGINE
# ============================================================

async def get_topic_messages(topic_id):
    messages = []
    try:
        async for message in user_client.iter_messages(GROUP_ID, reply_to=topic_id):
            messages.append(message)
        messages.reverse()
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception:
        logging.exception("Error while reading topic messages")
    return messages


async def get_topic_units(topic_id):
    now = time.time()
    cached = TOPIC_CACHE.get(topic_id)
    if cached and now - cached[0] < TOPIC_CACHE_TTL:
        return cached[1]

    units, current = {}, None
    for message in await get_topic_messages(topic_id):
        tag = extract_hashtag(message.text or "")
        if tag:
            current = tag
            units.setdefault(current, [])
        if current is not None and message.media:
            units[current].append(message)

    if units:
        TOPIC_CACHE[topic_id] = (now, units)
    return units

async def deliver_lecture(bot_client, bot_entity, chat_id, message, status_msg=None):
    global active_relay_future

    async with relay_lock:
        future = asyncio.get_running_loop().create_future()
        active_relay_future = future
        relayed = None
        try:
            await user_client.forward_messages(bot_entity, message)
            relayed = await asyncio.wait_for(future, timeout=10.0)
            try:
                await bot_client.send_file(
                    entity=chat_id, file=relayed.media,
                    caption=message.text or "", supports_streaming=True
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
            logging.warning("Relay fallback triggered.")
        finally:
            active_relay_future = None
            if relayed:
                try:
                    await relayed.delete()
                except Exception:
                    pass

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
                    caption=message.text or "", supports_streaming=True
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
# STUDENT BOTS (REGULAR ENROLLED USERS)
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    entity_box = {}

    async def guard(event, check_limit=False):
        uid = event.sender_id
        if is_banned(uid):
            await event.answer("⛔ You are restricted from using this service.", alert=True)
            return False
        allowed, _ = check_access(uid, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return False
        if check_limit and not check_daily_limit(uid)[0]:
            await event.answer("⚠️ Daily download limit reached!", alert=True)
            return False
        return True

    @bot_client.on(events.NewMessage)
    async def relay_listener(event):
        if event.is_private and event.sender_id == USER_CLIENT_ID:
            if active_relay_future and not active_relay_future.done():
                active_relay_future.set_result(event.message)

    @bot_client.on(events.NewMessage(pattern=r"^/start(?:\s.*)?$"))
    async def start_handler(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)
        uid = event.sender_id

        if is_banned(uid):
            await event.respond("⛔ You are restricted from using this service.")
            return

        allowed, reason = check_access(uid, bot_key)
        if not allowed:
            if reason.startswith("tier_mismatch"):
                user_tier = reason.split(":")[1]
                label = BOT_TITLES_MAP.get(user_tier, user_tier.replace("_", " ").title())
                await event.respond(
                    f"⚠️ **Year Access Restricted**\n\nYour subscription is activated for **{label}**, "
                    f"but this is the **{bot_title}**.\n\nTo upgrade or switch years, contact {OWNER_CONTACT}."
                )
            elif reason == "expired":
                await event.respond(
                    f"⚠️ **Subscription Expired!**\n\nYour access period has ended. "
                    f"Contact {OWNER_CONTACT} to renew your enrollment."
                )
            else:
                await event.respond(LOCKED_MESSAGE.format(user_id=uid))
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
            buttons=make_main_menu(bot_topics, uid)
        )

    @bot_client.on(events.NewMessage(pattern=r"^/mylogin$"))
    async def mylogin_cmd(event):
        uid = event.sender_id
        if uid == ADMIN_ID:
            await event.respond("ℹ️ Admin accounts do not use a student Q-Bank login.")
        elif is_banned(uid) or not has_qbank(uid):
            await event.respond(
                f"🔒 The CBT Q-Bank login is included in the **Full plan** (Lectures + Notes + MCQ).\n"
                f"To upgrade, contact {OWNER_CONTACT}."
            )
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
        await edit(
            event, f"🎓 **{bot_title}**\n\nSelect a subject below:",
            make_main_menu(bot_topics, event.sender_id)
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def cb_sub(event):
        if not await guard(event):
            return
        idx = int(event.pattern_match.group(1))
        subjects = list(bot_topics.keys())
        if 0 <= idx < len(subjects):
            user_subjects[event.sender_id] = subjects[idx]
            await edit(event, f"📚 **{subjects[idx]}**\n\nChoose an option below:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"sub_back"))
    async def cb_sub_back(event):
        if not await guard(event):
            return
        subj = user_subjects.get(event.sender_id, next(iter(bot_topics)))
        await edit(event, f"📚 **{subj}**\n\nChoose an option below:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"lectures"))
    async def cb_lectures(event):
        if not await guard(event):
            return
        uid = event.sender_id
        subj = user_subjects.get(uid)
        if not subj or subj not in bot_topics:
            await event.answer("Select subject again.")
            return
        await event.answer("Loading lectures...")
        units = await get_topic_units(bot_topics[subj])
        if not units:
            await edit(event, f"📚 **{subj}**\n\nNo lecture units found.",
                       [[Button.inline("⬅️ Back", data=b"sub_back")]])
            return
        names = list(units.keys())
        user_units[uid] = {"subject": subj, "units": units, "unit_names": names}
        buttons = [[Button.inline(f"📂 #{u} ({len(units[u])})", data=f"unit:{i}".encode())]
                   for i, u in enumerate(names)]
        buttons.append([Button.inline("⬅️ Back to Subject", data=b"sub_back")])
        await edit(event, f"📚 **{subj} Lectures**\n\nSelect a unit:", buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
    async def cb_unit(event):
        if not await guard(event):
            return
        data = user_units.get(event.sender_id)
        if not data:
            await event.answer("Reopen the subject.")
            return
        idx = int(event.pattern_match.group(1))
        if 0 <= idx < len(data["unit_names"]):
            name = data["unit_names"][idx]
            lectures = data["units"].get(name, [])
            buttons = []
            for i, lec in enumerate(lectures):
                fname = get_filename(lec, i + 1)
                if len(fname) > 42:
                    fname = fname[:39] + "..."
                buttons.append([Button.inline(f"📄 {fname}", data=f"file:{lec.id}".encode())])
            buttons.append([Button.inline("⬅️ Units", data=b"lectures")])
            await edit(event, f"📂 **#{name}** ({len(lectures)} lectures):\n\nSelect a lecture:", buttons)

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
                if await deliver_lecture(bot_client, entity_box.get("entity"), event.chat_id, msg, status):
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
        subj = user_subjects.get(uid)
        if not subj:
            await event.answer("Select subject again.")
            return
        await event.answer()
        status = await bot_client.send_message(event.chat_id, f"🔍 Searching notes for **{subj}**...")
        try:
            notes = await get_topic_messages(bot_topics.get("Notes", 33))
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
                if await deliver_lecture(bot_client, entity_box.get("entity"), event.chat_id, m, None):
                    sent += 1
            if sent:
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
        subj = user_subjects.get(uid, next(iter(bot_topics)))
        await edit(
            event,
            f"🎯 **{subj} MCQ & Question Bank Hub**\n\nSelect your practice material:\n\n"
            "• 🌐 **Interactive CBT App**: browser exam simulator with timers & rationales.\n"
            "• 📂 **Topic-Wise Q-Bank**: unit-wise question papers & PDFs.\n"
            "• 🏛️ **Previous Year Questions (PYQs)**: past recalls.\n"
            "• 🎲 **Random / Mock Test MCQs**: mixed subject questions.",
            make_mcq_hub_menu(uid)
        )

    @bot_client.on(events.CallbackQuery(data=b"mcq_upgrade_info"))
    async def cb_upgrade_info(event):
        await event.answer("🔒 Q-Bank Access Required", alert=True)
        await event.respond(
            "🔒 **Interactive Q-Bank Not Included in Your Current Plan**\n\n"
            "Your account currently has access to **Lectures & Notes Only**.\n\n"
            f"To unlock the CBT test simulator with scorecards and option shuffling, "
            f"contact {OWNER_CONTACT} to upgrade your plan."
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^mcq_p:(.+)$"))
    async def cb_mcq_paper(event):
        if not await guard(event):
            return
        cat = event.pattern_match.group(1).decode()
        subj = user_subjects.get(event.sender_id, next(iter(bot_topics)))
        titles = {
            "topic_wise": "📂 Topic-Wise Q-Bank PDFs",
            "pyqs": "🏛️ Previous Year Questions (PYQs)",
            "random": "🎲 Random / Mock Test MCQs"
        }
        await edit(
            event,
            f"📑 **{subj} — {titles.get(cat, 'MCQs')}**\n\nThis section is being updated. "
            "Use the CBT Q-Bank app for practice meanwhile.",
            [[Button.inline("⬅️ Back to MCQ Hub", data=b"mcq_hub")]]
        )

    return entity_box

# ============================================================
# DEMO BOT ENGINE (@Demoprep_bot)
# Strict 5-10 Mins Window + 2 Lecture Downloads Max + Demo CBT Login
# ============================================================

def setup_demo_bot_handlers(bot_client):
    entity_box = {}

    def format_countdown(seconds):
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs:02d}s"

    async def demo_guard(event, check_download=False):
        uid = event.sender_id
        if is_banned(uid):
            await event.answer("⛔ Access Restricted.", alert=True)
            return False

        status, remaining, dl_used, dl_max = check_demo_status(uid)

        if status == "expired":
            await event.answer("⏳ Demo Trial Expired!", alert=True)
            await event.respond(
                "⏳ **Your Demo Trial Period Has Ended!**\n\n"
                f"You have completed your preview session.\n"
                f"To unlock unlimited high-speed lectures, notes, and the full CBT Q-Bank, "
                f"contact {OWNER_CONTACT} for enrollment.",
                buttons=[[Button.url("💎 Enroll / Contact Owner", f"https://t.me/{OWNER_CONTACT.lstrip('@')}")]]
            )
            return False

        if check_download and dl_used >= dl_max:
            await event.answer("⚠️ Demo Download Limit Reached (Max 2 lectures)!", alert=True)
            await event.respond(
                f"⚠️ **Demo Quota Exceeded ({dl_used}/{dl_max} downloads used)**\n\n"
                "In demo mode, you can download up to **2 sample lectures** to test streaming and quality.\n\n"
                f"To get complete unrestricted access to all 19 subjects, contact {OWNER_CONTACT}.",
                buttons=[[Button.url("💎 Get Full Plan", f"https://t.me/{OWNER_CONTACT.lstrip('@')}")]]
            )
            return False

        return True

    @bot_client.on(events.NewMessage)
    async def demo_relay_listener(event):
        if event.is_private and event.sender_id == USER_CLIENT_ID:
            if active_relay_future and not active_relay_future.done():
                active_relay_future.set_result(event.message)

    @bot_client.on(events.NewMessage(pattern=r"^/start(?:\s.*)?$"))
    async def demo_start(event):
        sender = await event.get_sender()
        uid = event.sender_id
        track_user(sender, "demo")

        if is_banned(uid):
            await event.respond("⛔ You are restricted from using this service.")
            return

        session = get_or_start_demo_session(uid, sender.first_name or "Doctor")
        await ensure_demo_cbt_synced(uid, sender.first_name or "Doctor")

        status, remaining, dl_used, dl_max = check_demo_status(uid)

        if status == "expired":
            await event.respond(
                "⏳ **Demo Trial Expired**\n\n"
                f"You have already utilized your preview session.\n"
                f"Contact {OWNER_CONTACT} to activate your full MBBS subscription.",
                buttons=[[Button.url("💎 Upgrade to Full Plan", f"https://t.me/{OWNER_CONTACT.lstrip('@')}")]]
            )
            return

        demo_topics = get_demo_topics()
        tier_name = db["settings"].get("demo_year_tier", "all")
        tier_label = BOT_TITLES_MAP.get(tier_name, tier_name.replace("_", " ").title())

        demo_cbt_url = generate_demo_webapp_url(session["cbt_id"], session["cbt_pass"])

        welcome_text = (
            "🧪 **Welcome to MBBS Demo Trial Hub!**\n\n"
            "This trial is configured so you can verify our lecture quality and test our interactive CBT simulator.\n\n"
            f"⏱️ **Trial Time Remaining:** `{format_countdown(remaining)}`\n"
            f"📥 **Lecture Downloads Allowed:** `{dl_used}/{dl_max}` used\n"
            f"📚 **Visible Curriculum:** `{tier_label}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🩺 **YOUR TRIAL CBT Q-BANK LOGIN:**\n"
            f"🆔 **Demo ID:** `{session['cbt_id']}`\n"
            f"🔑 **Password:** `{session['cbt_pass']}`\n"
            "*(Auto logs in when you tap the CBT button)*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose a subject below to test sample lectures:"
        )

        await event.respond(welcome_text, buttons=make_main_menu(demo_topics, uid, is_demo=True))

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def demo_cb_home(event):
        if not await demo_guard(event):
            return
        uid = event.sender_id
        status, remaining, dl_used, dl_max = check_demo_status(uid)
        demo_topics = get_demo_topics()
        text = (
            "🧪 **MBBS Demo Trial Menu**\n\n"
            f"⏱️ **Time Left:** `{format_countdown(remaining)}` | 📥 **Downloads:** `{dl_used}/{dl_max}`\n\n"
            "Select a subject below:"
        )
        await edit(event, text, make_main_menu(demo_topics, uid, is_demo=True))

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def demo_cb_sub(event):
        if not await demo_guard(event):
            return
        idx = int(event.pattern_match.group(1))
        demo_topics = get_demo_topics()
        subjects = list(demo_topics.keys())
        if 0 <= idx < len(subjects):
            user_subjects[event.sender_id] = subjects[idx]
            await edit(event, f"📚 **{subjects[idx]} (Trial Mode)**\n\nSelect an option to test:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"sub_back"))
    async def demo_cb_sub_back(event):
        if not await demo_guard(event):
            return
        demo_topics = get_demo_topics()
        subj = user_subjects.get(event.sender_id, next(iter(demo_topics)))
        await edit(event, f"📚 **{subj} (Trial Mode)**\n\nSelect an option to test:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"lectures"))
    async def demo_cb_lectures(event):
        if not await demo_guard(event):
            return
        uid = event.sender_id
        demo_topics = get_demo_topics()
        subj = user_subjects.get(uid)
        if not subj or subj not in demo_topics:
            await event.answer("Select subject again.")
            return
        await event.answer("Loading sample units...")
        units = await get_topic_units(demo_topics[subj])
        if not units:
            await edit(event, f"📚 **{subj}**\n\nNo lecture units found.",
                       [[Button.inline("⬅️ Back", data=b"sub_back")]])
            return
        names = list(units.keys())
        user_units[uid] = {"subject": subj, "units": units, "unit_names": names}
        buttons = [[Button.inline(f"📂 #{u} ({len(units[u])})", data=f"unit:{i}".encode())]
                   for i, u in enumerate(names)]
        buttons.append([Button.inline("⬅️ Back to Subject", data=b"sub_back")])
        await edit(event, f"📚 **{subj} Lectures (Trial Mode)**\n\nSelect a unit to inspect:", buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
    async def demo_cb_unit(event):
        if not await demo_guard(event):
            return
        data = user_units.get(event.sender_id)
        if not data:
            await event.answer("Reopen the subject.")
            return
        idx = int(event.pattern_match.group(1))
        if 0 <= idx < len(data["unit_names"]):
            name = data["unit_names"][idx]
            lectures = data["units"].get(name, [])
            buttons = []
            for i, lec in enumerate(lectures[:6]):  # Show up to 6 sample lectures
                fname = get_filename(lec, i + 1)
                if len(fname) > 38:
                    fname = fname[:35] + "..."
                buttons.append([Button.inline(f"📄 {fname}", data=f"file:{lec.id}".encode())])
            buttons.append([Button.inline("⬅️ Units", data=b"lectures")])
            await edit(event, f"📂 **#{name}** (Demo Preview):\n\nChoose a sample lecture (Max 2 downloads):", buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^file:(\d+)$"))
    async def demo_cb_file(event):
        if not await demo_guard(event, check_download=True):
            return
        uid = event.sender_id
        mid = int(event.pattern_match.group(1))
        await event.answer("⚡ Sending sample lecture...")
        status = await bot_client.send_message(event.chat_id, "⚡ **Streaming demo lecture...**")
        try:
            msg = await user_client.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                if await deliver_lecture(bot_client, entity_box.get("entity"), event.chat_id, msg, status):
                    record_demo_download(uid)
                    status_type, remaining, dl_used, dl_max = check_demo_status(uid)
                    await bot_client.send_message(
                        event.chat_id,
                        f"✅ **Sample Delivered!**\n\n"
                        f"📥 Downloads remaining: `{max(0, dl_max - dl_used)}/{dl_max}`\n"
                        f"⏱️ Time left: `{format_countdown(remaining)}`\n\n"
                        f"💬 To get unlimited access without limits, contact {OWNER_CONTACT}",
                        buttons=[[Button.url("💎 Enroll in Full Plan", f"https://t.me/{OWNER_CONTACT.lstrip('@')}")]]
                    )
            else:
                await status.edit("❌ Lecture file not found.")
        except Exception:
            logging.exception("Demo file deliver error")
            await status.edit("❌ Delivery failed.")

    @bot_client.on(events.CallbackQuery(data=b"notes"))
    async def demo_cb_notes(event):
        if not await demo_guard(event, check_download=True):
            return
        uid = event.sender_id
        demo_topics = get_demo_topics()
        subj = user_subjects.get(uid)
        if not subj:
            await event.answer("Select subject again.")
            return
        await event.answer()
        status = await bot_client.send_message(event.chat_id, f"🔍 Searching sample notes for **{subj}**...")
        try:
            notes = await get_topic_messages(demo_topics.get("Notes", 33))
            key = re.sub(r"[^a-zA-Z0-9]", "", subj).lower()
            found = [m for m in notes if m.media and (
                key in re.sub(r"[^a-zA-Z0-9]", "", (m.text or "")).lower()
                or key in re.sub(r"[^a-zA-Z0-9]", "", get_filename(m)).lower())]
            if not found:
                await status.edit(f"❌ No demo notes found for **{subj}**.")
                return
            await status.edit("⚡ Delivering sample note PDF...")
            if await deliver_lecture(bot_client, entity_box.get("entity"), event.chat_id, found[0], None):
                record_demo_download(uid)
            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            logging.exception("Demo notes deliver error")
            await status.edit("❌ Could not deliver notes.")

    @bot_client.on(events.CallbackQuery(data=b"mcq_hub"))
    async def demo_cb_mcq_hub(event):
        if not await demo_guard(event):
            return
        uid = event.sender_id
        demo_topics = get_demo_topics()
        subj = user_subjects.get(uid, next(iter(demo_topics)))
        await edit(
            event,
            f"🎯 **{subj} Demo MCQ & CBT Simulator**\n\n"
            "You have trial access to test our CBT Web Application with interactive timers and explanations.\n\n"
            "Tap below to test the CBT app:",
            make_mcq_hub_menu(uid, is_demo=True)
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^mcq_p:(.+)$"))
    async def demo_cb_mcq_paper(event):
        if not await demo_guard(event):
            return
        await edit(
            event,
            "📑 **Demo Question Bank**\n\n"
            "Full unit MCQ question papers & recall banks are reserved for verified subscribers.\n\n"
            f"Please test the interactive CBT app or contact {OWNER_CONTACT} to unlock all PDFs.",
            [[Button.inline("⬅️ Back to MCQ Hub", data=b"mcq_hub")]]
        )

    return entity_box

# ============================================================
# BROADCAST DISPATCHER
# ============================================================

async def execute_broadcast(payload, is_raw_event=False):
    sent = failed = 0
    text_body = None if (is_raw_event and payload.media) else (payload.text if is_raw_event else str(payload))

    for uid_str, udata in list(db.get("users", {}).items()):
        if is_banned(uid_str):
            continue
        target = int(uid_str)
        client = (active_bots.get(udata.get("bot_used")) or manager_bot_client
                  or (next(iter(active_bots.values())) if active_bots else None))
        if not client:
            failed += 1
            continue

        async def send():
            if text_body is None:
                await client.send_file(target, file=payload.media, caption=payload.text or "")
            else:
                await client.send_message(target, f"📢 **MBBS Announcement:**\n\n{text_body}")

        try:
            await send()
            sent += 1
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            try:
                await send()
                sent += 1
            except Exception:
                failed += 1
        except Exception as err:
            logging.warning("Broadcast skipped for %s: %s", target, err)
            failed += 1
        await asyncio.sleep(0.08)
    return sent, failed

# ============================================================
# MANAGER BOT (ADMIN CONTROL CENTER & DEMO CONFIGURATOR)
# ============================================================

def paid_counts():
    paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
    qb = sum(1 for u in paid if db["approved_details"].get(str(u), {}).get("content_tier") == "full")
    return len(paid), qb, len(paid) - qb

def dashboard_text():
    paid, qb, lec = paid_counts()
    demo_count = len(db.get("demo_sessions", {}))
    return ("🎛️ **MBBS Management Control Center**\n\n"
            f"🤖 **Managed Bots Online:** `{len(active_bots)}` bots\n"
            f"👥 **Total Registered Students:** `{len(db.get('users', {}))}`\n"
            f"💎 **Verified Paid Members:** `{paid}`\n"
            f"  └ 🩺 Full (Lectures + Notes + Q-Bank): `{qb}`\n"
            f"  └ 📚 Lectures Only: `{lec}`\n"
            f"🧪 **Demo Trial Sessions:** `{demo_count}` candidates\n"
            f"🚫 **Blocked Users:** `{len(db.get('banned', []))}`\n\n"
            "Select an administrative action below:")


def make_manager_menu():
    return [
        [Button.inline("📊 System Stats", data=b"mgmt_stats"), Button.inline("⚙️ Feature Toggles", data=b"mgmt_toggles")],
        [Button.inline("🧪 Demo Bot Controls", data=b"mgmt_demo_menu"), Button.inline("⏳ Pending Requests", data=b"mgmt_pending")],
        [Button.inline("💎 Verified Members", data=b"mgmt_approved_p:0"), Button.inline("👥 Registered Users", data=b"mgmt_users_p:0")],
        [Button.inline("📢 Broadcast Announcement", data=b"mgmt_announce"), Button.inline("☁️ Cloud Backup Now", data=b"mgmt_do_backup")],
        [Button.inline("🟢 Alert: Server Online", data=b"mgmt_alert_online"), Button.inline("🔴 Alert: Server Down", data=b"mgmt_alert_down")],
        [Button.inline("🔄 Refresh Dashboard", data=b"mgmt_home")],
    ]


def make_toggles_menu():
    s = db["settings"]
    on = lambda k: "🟢 ON" if s.get(k) else "🔴 OFF"
    limit = f"🟢 ON ({s.get('daily_limit_max', 30)}/d)" if s.get("daily_limit_enabled") else "🔴 OFF"
    return [
        [Button.inline(f"⏳ Subscription Expiry: {on('expiry_enabled')}", data=b"tog:expiry_enabled")],
        [Button.inline(f"🎓 Year-Lock Tier: {on('tier_access_enabled')}", data=b"tog:tier_access_enabled")],
        [Button.inline(f"🛡️ Anti-Leech Limit: {limit}", data=b"tog:daily_limit_enabled")],
        [Button.inline(f"☁️ Cloud Auto-Sync: {on('cloud_backup_enabled')}", data=b"tog:cloud_backup_enabled")],
        [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")],
    ]

def make_demo_control_menu():
    s = db["settings"]
    duration = s.get("demo_duration_mins", 10)
    max_dl = s.get("demo_max_downloads", 2)
    tier = s.get("demo_year_tier", "all")
    tier_label = BOT_TITLES_MAP.get(tier, tier).replace("MBBS ", "").replace(" Library", "")

    return [
        [Button.inline(f"⏱️ Trial Duration: {duration} mins", data=b"demo_tog:duration")],
        [Button.inline(f"📥 Max Downloads: {max_dl} files", data=b"demo_tog:max_dl")],
        [Button.inline(f"📚 Visible Year: {tier_label}", data=b"demo_tog:tier")],
        [Button.inline("👥 View Demo Users", data=b"demo_users_p:0"), Button.inline("🧪 Generate Demo Link", data=b"demo_gen_direct")],
        [Button.inline("⬅️ Back to Dashboard", data=b"mgmt_home")],
    ]


def grant_plan(target_id, tier):
    """Approve a student with a plan: 'full' or 'lectures_only'."""
    t = str(target_id)
    if target_id not in db["approved"]:
        db["approved"].append(target_id)
    if target_id in db["banned"]:
        db["banned"].remove(target_id)
    det = db["approved_details"].setdefault(t, {})
    det.update({"content_tier": tier, "tier": det.get("tier", "all"), "expiry": det.get("expiry")})
    det.setdefault("added_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if tier == "full":
        get_or_create_qbank_creds(target_id)
    save_db(db)

def setup_manager_bot_handlers(client):
    back_menu = [[Button.inline("⬅️ Menu", data=b"mgmt_home")]]

    def admin_only(event):
        return event.sender_id == ADMIN_ID

    @client.on(events.NewMessage(pattern=r"^/start$"))
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

    # ==========================
    # DEMO BOT MANAGEMENT PANELS
    # ==========================
    @client.on(events.CallbackQuery(data=b"mgmt_demo_menu"))
    async def cb_demo_menu(event):
        if not admin_only(event):
            return
        s = db["settings"]
        active_trials = 0
        now = time.time()
        for session in db.get("demo_sessions", {}).values():
            if now - session.get("start_time", 0) < session.get("duration_mins", 10) * 60:
                active_trials += 1

        text = (
            "🧪 **Demo Bot Control Center (@Demoprep_bot)**\n\n"
            "Configure real-time demo limits, visible subjects, and download restrictions.\n\n"
            f"⏱️ **Current Trial Duration:** `{s.get('demo_duration_mins', 10)} minutes`\n"
            f"📥 **Lecture Download Restriction:** `{s.get('demo_max_downloads', 2)} lectures max`\n"
            f"📚 **Active Curriculum Shown:** `{s.get('demo_year_tier', 'all')}`\n"
            f"🟢 **Active Demo Candidates Now:** `{active_trials}` online\n\n"
            "Tap any setting below to switch values:"
        )
        await edit(event, text, make_demo_control_menu())

    @client.on(events.CallbackQuery(data=b"demo_tog:duration"))
    async def cb_toggle_demo_duration(event):
        if not admin_only(event):
            return
        cur = db["settings"].get("demo_duration_mins", 10)
        # Cycle through 5 -> 10 -> 15 -> 30 -> 5
        durations = [5, 10, 15, 30]
        idx = durations.index(cur) if cur in durations else 0
        new_val = durations[(idx + 1) % len(durations)]
        db["settings"]["demo_duration_mins"] = new_val
        save_db(db)
        await event.answer(f"Demo duration set to {new_val} minutes!", alert=True)
        await cb_demo_menu(event)

    @client.on(events.CallbackQuery(data=b"demo_tog:max_dl"))
    async def cb_toggle_demo_dl(event):
        if not admin_only(event):
            return
        cur = db["settings"].get("demo_max_downloads", 2)
        # Cycle through 1 -> 2 -> 3 -> 5 -> 1
        dls = [1, 2, 3, 5]
        idx = dls.index(cur) if cur in dls else 0
        new_val = dls[(idx + 1) % len(dls)]
        db["settings"]["demo_max_downloads"] = new_val
        save_db(db)
        await event.answer(f"Demo download quota set to {new_val} lectures!", alert=True)
        await cb_demo_menu(event)

    @client.on(events.CallbackQuery(data=b"demo_tog:tier"))
    async def cb_toggle_demo_tier(event):
        if not admin_only(event):
            return
        tiers = ["all", "year_1", "year_2", "year_3", "final_year"]
        cur = db["settings"].get("demo_year_tier", "all")
        idx = tiers.index(cur) if cur in tiers else 0
        new_tier = tiers[(idx + 1) % len(tiers)]
        db["settings"]["demo_year_tier"] = new_tier
        save_db(db)
        await event.answer(f"Demo year library switched to {new_tier.upper()}!", alert=True)
        await cb_demo_menu(event)

    @client.on(events.CallbackQuery(pattern=rb"^demo_users_p:(\d+)$"))
    async def cb_demo_users_page(event):
        if not admin_only(event):
            return
        demos = list(db.get("demo_sessions", {}).items())
        if not demos:
            await edit(event, "ℹ️ **No demo candidate sessions recorded yet.**",
                       [[Button.inline("⬅️ Demo Menu", data=b"mgmt_demo_menu")]])
            return

        per = 5
        pages = max(1, (len(demos) + per - 1) // per)
        page = max(0, min(int(event.pattern_match.group(1)), pages - 1))
        msg = f"🧪 **Demo Candidates ({len(demos)}) — Page {page + 1}/{pages}:**\n\n"
        buttons = []

        now = time.time()
        for uid_str, sess in demos[page * per:(page + 1) * per]:
            u = db.get("users", {}).get(uid_str, {})
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or f"Candidate {uid_str}"
            elapsed = now - sess.get("start_time", 0)
            total = sess.get("duration_mins", 10) * 60
            expired = elapsed > total
            rem = max(0, total - elapsed)
            rem_str = f"{int(rem // 60)}m {int(rem % 60)}s left" if not expired else "EXPIRED"

            msg += (
                f"• **{name}** (`{uid_str}`)\n"
                f"  └ ⏱️ {rem_str} | 📥 {sess.get('downloads_used', 0)}/{sess.get('max_downloads', 2)} DLs\n"
                f"  └ CBT ID: `{sess.get('cbt_id')}` | Pass: `{sess.get('cbt_pass')}`\n\n"
            )
            buttons.append([
                Button.inline(f"🔄 Reset Trial {name[:10]}", data=f"adm_demo_grant:{uid_str}".encode()),
                Button.inline("⚡ Grant Full", data=f"adm_app_full:{uid_str}".encode())
            ])

        nav = []
        if page > 0:
            nav.append(Button.inline("◀ Prev", data=f"demo_users_p:{page - 1}".encode()))
        if page < pages - 1:
            nav.append(Button.inline("Next ▶", data=f"demo_users_p:{page + 1}".encode()))
        if nav:
            buttons.append(nav)
        buttons.append([Button.inline("⬅️ Demo Menu", data=b"mgmt_demo_menu")])
        await edit(event, msg, buttons)

    @client.on(events.CallbackQuery(data=b"demo_gen_direct"))
    async def cb_gen_direct_demo(event):
        if not admin_only(event):
            return
        qid = "DEMO-" + _pick(4)
        pw = _pick(6)
        exp = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            await supabase_upsert_student(qid, pw, "Direct Trial Lead", True, exp, is_demo=True)
            url = f"{CBT_WEBAPP_BASE_URL}?uid={quote(qid)}&key={quote(pw)}"
            text = (
                "🧪 **Direct Demo Access Card Generated**\n\n"
                f"🤖 **Demo Telegram Bot:** @Demoprep_bot\n"
                f"🆔 **Demo CBT ID:** `{qid}`\n"
                f"🔑 **Password:** `{pw}`\n\n"
                f"🌐 **Direct One-Click Portal Link:**\n{url}\n\n"
                "*(Share this directly with prospective students who ask for proof)*"
            )
            await edit(event, text, [[Button.inline("⬅️ Demo Menu", data=b"mgmt_demo_menu")]])
        except Exception as e:
            await event.answer(f"Failed to sync demo: {e}", alert=True)

    @client.on(events.CallbackQuery(pattern=rb"^adm_demo_grant:(\d+)$"))
    async def cb_adm_demo_grant(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        s_uid = str(uid)
        db["demo_sessions"].pop(s_uid, None)
        sess = get_or_start_demo_session(uid)
        await ensure_demo_cbt_synced(uid)
        await event.answer("✅ Demo trial reset/granted for candidate!", alert=True)
        await edit(
            event,
            f"✅ **Demo Session Reset for User `{uid}`**\n\n"
            f"⏱️ Duration: `{sess.get('duration_mins')} mins`\n"
            f"📥 Allowed Downloads: `{sess.get('max_downloads')}`\n"
            f"🆔 Demo CBT ID: `{sess.get('cbt_id')}`\n"
            f"🔑 Demo Password: `{sess.get('cbt_pass')}`\n\n"
            "The candidate can now use @Demoprep_bot with a fresh quota.",
            [[Button.inline("⬅️ Demo Menu", data=b"mgmt_demo_menu")]]
        )

    # ---------- Broadcast Listeners ----------
    @client.on(events.CallbackQuery(data=b"mgmt_announce"))
    async def cb_announce(event):
        if not admin_only(event):
            return
        ADMIN_STATES[ADMIN_ID] = "WAITING_BROADCAST_MESSAGE"
        await edit(
            event,
            "📢 **Broadcast Mode Activated**\n\nSend the message (text, photo, file or forward) "
            "you want to broadcast to **ALL registered students**.",
            [[Button.inline("❌ Cancel Broadcast", data=b"mgmt_cancel_broadcast")]]
        )

    @client.on(events.CallbackQuery(data=b"mgmt_cancel_broadcast"))
    async def cb_cancel_broadcast(event):
        if not admin_only(event):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await event.answer("Broadcast canceled.", alert=True)
        await edit(event, dashboard_text(), make_manager_menu())

    @client.on(events.NewMessage)
    async def broadcast_capture(event):
        if not admin_only(event) or not event.is_private:
            return
        if ADMIN_STATES.get(ADMIN_ID) != "WAITING_BROADCAST_MESSAGE":
            return
        if event.text and event.text.startswith("/"):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        total = len(db.get("users", {}))
        status = await event.respond(f"⏳ **Broadcasting to {total} students...**")
        sent, failed = await execute_broadcast(event.message, is_raw_event=True)
        await status.edit(
            f"✅ **Broadcast Completed!**\n\n📬 Delivered: `{sent}`\n"
            f"❌ Failed/Blocked: `{failed}`\n👥 Total Target: `{total}`",
            buttons=[[Button.inline("⬅️ Return to Dashboard", data=b"mgmt_home")]]
        )

    @client.on(events.NewMessage(pattern=r"^/broadcast (.+)"))
    async def cmd_broadcast(event):
        if not admin_only(event):
            return
        text = event.pattern_match.group(1).strip()
        status = await event.respond(f"📢 Broadcasting to `{len(db.get('users', {}))}` students...")
        sent, failed = await execute_broadcast(text)
        await status.edit(f"✅ **Broadcast complete!**\n📬 Delivered: `{sent}` | ❌ Failed: `{failed}`")

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
            await edit(event, "⚙️ **System Feature Controls (ON / OFF)**", make_toggles_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_do_backup"))
    async def cb_do_backup(event):
        if not admin_only(event):
            return
        await event.answer("Dispatching cloud backup to chat...")
        await trigger_cloud_backup(force=True)
        await edit(event, "✅ **Cloud backup dispatched!** `bot_database.json` was sent to this chat.", back_menu)

    @client.on(events.CallbackQuery(data=b"mgmt_stats"))
    async def cb_stats(event):
        if not admin_only(event):
            return
        paid, qb, lec = paid_counts()
        up = int(time.time() - START_TIME)
        synced = sum(1 for d in db["approved_details"].values() if str(d.get("qb_state", "")).startswith("on"))
        demos = len(db.get("demo_sessions", {}))
        await edit(
            event,
            "📊 **Live System Analytics**\n\n"
            f"👥 **Total Registered Students:** `{len(db.get('users', {}))}`\n"
            f"💎 **Verified Paid:** `{paid}`\n"
            f"  └ 🩺 Full (Lectures + Notes + Q-Bank): `{qb}`\n"
            f"  └ 📚 Lectures & Notes Only: `{lec}`\n"
            f"🧪 **Demo Trial Sessions Issued:** `{demos}`\n"
            f"🔑 **Q-Bank logins live on portal:** `{synced}`\n"
            f"🚫 **Blocked:** `{len(db.get('banned', []))}`\n"
            f"⏱️ **Server Uptime:** `{up // 3600}h {(up % 3600) // 60}m {up % 60}s`\n\n"
            f"🤖 **Connected Active Bots:** `{len(active_bots)}` online",
            back_menu
        )

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
            msg += f"• **{name}** ({uname})\n  └ ID: `{uid_str}` | Plan: **{badge}** | Bot: `{u.get('bot_used', 'all')}`\n\n"
            if not approved:
                buttons.append([
                    Button.inline(f"⚡ Full {name[:10]}", data=f"adm_app_full:{uid_str}".encode()),
                    Button.inline("🧪 Demo", data=f"adm_demo_grant:{uid_str}".encode())
                ])
            else:
                buttons.append([Button.inline(f"⚙️ Manage {name[:12]}", data=f"adm_tier_opt:{uid_str}".encode())])
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
            msg += (f"• **{name}** ({uname})\n  └ ID: `{uid}` | Plan: **{'🩺 Full' if full else '📚 Lectures Only'}** "
                    f"| Q-ID: `{det.get('qbank_id', '—') if full else '—'}`\n\n")
            buttons.append([Button.inline(f"✏️ Edit {name[:12]}", data=f"adm_tier_opt:{uid}".encode()),
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
        pending = [(u, d) for u, d in db.get("users", {}).items()
                   if not is_banned(u) and int(u) not in db.get("approved", [])]
        if not pending:
            await edit(event, "✅ **No pending access requests!**", back_menu)
            return
        buttons = []
        for uid, u in pending[-6:]:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Student"
            buttons.append([Button.inline(f"⚡ Full {name[:12]}", data=f"adm_app_full:{uid}".encode()),
                            Button.inline("📚 Lec", data=f"adm_app_lec:{uid}".encode())])
        buttons.append([Button.inline("⬅️ Back", data=b"mgmt_home")])
        await edit(event, f"⏳ **Pending Verification Requests ({len(pending)}):**", buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_app_full:(\d+)$"))
    async def cb_app_full(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        grant_plan(target, "full")
        qid, qpass = get_or_create_qbank_creds(target)
        await event.answer("✅ Full Access Granted!", alert=True)
        await edit(
            event,
            f"✅ User `{target}` granted **Full Access (Lectures + Notes + Q-Bank)**!\n\n"
            f"🆔 Student ID: `{qid}`\n🔑 Password: `{qpass}`\n\n"
            "_The login has been dispatched to the candidate and synced to the CBT portal._",
            back_menu
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
        await edit(event, f"✅ User `{target}` enrolled in **Lectures & Notes Only**.", back_menu)
        for bot in active_bots.values():
            try:
                await bot.send_message(
                    target,
                    "🎉 **Access Granted!**\n\nYour account has been enrolled in "
                    "**MBBS Video Lectures & Notes**.\nSend /start to begin studying!"
                )
                break
            except Exception:
                continue
        await reconcile_now()
        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^adm_tier_opt:(\d+)$"))
    async def cb_tier_options(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        cur = db.get("approved_details", {}).get(str(uid), {}).get("content_tier", "none")
        await edit(
            event,
            f"⚙️ **Modify Subscription for User `{uid}`:**\n\n• Current Plan: **{cur.upper()}**\n\n"
            "Select an updated plan below:",
            [[Button.inline("🩺 Full (Lectures + Notes + Q-Bank)", data=f"adm_set_tier:{uid}:full".encode())],
             [Button.inline("📚 Lectures & Notes Only", data=f"adm_set_tier:{uid}:lectures_only".encode())],
             [Button.inline("🧪 Reset Demo Session", data=f"adm_demo_grant:{uid}".encode())],
             [Button.inline("⬅️ Back", data=b"mgmt_approved_p:0")]]
        )

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
        await edit(
            event,
            f"✅ User `{uid}` updated to **{tier.upper()}**!"
            + ("\n_Q-Bank login sent / activated._" if tier == "full" else "\n_Q-Bank login switched off._"),
            [[Button.inline("💎 Back to Verified Members", data=b"mgmt_approved_p:0")]]
        )
        await reconcile_now()
        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^adm_rev:(\d+)$"))
    async def cb_rev(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        if target in db.get("approved", []):
            db["approved"].remove(target)
            save_db(db)
            await reconcile_now()
            await trigger_cloud_backup()
        await event.answer("🔒 Access Revoked!", alert=True)
        await edit(event, f"🔒 Access revoked for `{target}`.", back_menu)

    @client.on(events.CallbackQuery(pattern=rb"^adm_ban:(\d+)$"))
    async def cb_ban(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        if target not in db["banned"]:
            db["banned"].append(target)
        if target in db["approved"]:
            db["approved"].remove(target)
        save_db(db)
        await reconcile_now()
        await trigger_cloud_backup()
        await event.answer("⛔ User Banned!", alert=True)
        await edit(event, f"⛔ User `{target}` banned.", back_menu)

    async def alert_paid(event, notice, label):
        await event.answer("Sending notice...")
        sender = next(iter(active_bots.values())) if active_bots else client
        sent = 0
        for uid in list(db.get("approved", [])):
            if uid == ADMIN_ID:
                continue
            try:
                await sender.send_message(uid, notice)
                sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await edit(event, f"✅ **{label} notice delivered to `{sent}` paid students!**", back_menu)

    @client.on(events.CallbackQuery(data=b"mgmt_alert_online"))
    async def cb_online(event):
        if admin_only(event):
            await alert_paid(
                event,
                "🟢 **MBBS Platform Status: All Systems Operational**\n\nThe lecture streaming "
                "servers, Demo bot, and CBT Q-Bank app are fully online. Happy studying!",
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

    @client.on(events.NewMessage(pattern=r"^/users$"))
    async def cmd_users(event):
        if not admin_only(event):
            return
        users = db.get("users", {})
        if not users:
            await event.respond("ℹ️ No registered users found.")
            return
        msg = f"👥 **Registered Students ({len(users)}) — last 25:**\n\n"
        for uid_str, d in list(users.items())[-25:]:
            name = f"{d.get('first_name', '')} {d.get('last_name', '')}".strip() or "Student"
            uname = f"@{d['username']}" if d.get("username") else "No username"
            approved = int(uid_str) in db.get("approved", [])
            tier = db["approved_details"].get(uid_str, {}).get("content_tier", "none") if approved else "Unverified"
            msg += f"• `{uid_str}`: **{name}** ({uname})\n  └ Plan: `{tier}` | Joined: `{d.get('joined_at', '-')}`\n"
        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/approved$"))
    async def cmd_approved(event):
        if not admin_only(event):
            return
        paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
        if not paid:
            await event.respond("ℹ️ No verified paid members yet.")
            return
        msg = f"💎 **Verified Paid Members ({len(paid)}):**\n\n"
        for uid in paid:
            det = db["approved_details"].get(str(uid), {})
            tier = det.get("content_tier", "lectures_only")
            login = f"ID: `{det.get('qbank_id')}` | Pass: `{det.get('qbank_pass')}`" if tier == "full" else "no Q-Bank login"
            msg += f"👤 **{display_name(uid)}** (`{uid}`)\n  └ Plan: **{tier.upper()}** | {login}\n\n"
        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/reset_demo (\d+)$"))
    async def cmd_reset_demo(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        db["demo_sessions"].pop(str(target), None)
        sess = get_or_start_demo_session(target)
        await ensure_demo_cbt_synced(target)
        await event.respond(
            f"✅ **Demo Session Reset for User `{target}`**\n\n"
            f"⏱️ Duration: `{sess['duration_mins']} mins`\n"
            f"📥 Allowed Downloads: `{sess['max_downloads']}`\n"
            f"🆔 Demo CBT ID: `{sess['cbt_id']}`\n🔑 Pass: `{sess['cbt_pass']}`"
        )

    @client.on(events.NewMessage(pattern=r"^/grant_qbank (\d+)$"))
    async def cmd_grant_qbank(event):
        if not admin_only(event):
            return
        target = int(event.pattern_match.group(1))
        grant_plan(target, "full")
        qid, qpass = get_or_create_qbank_creds(target)
        await event.respond(f"✅ User `{target}` granted **Full Access**!\n🆔 `{qid}` | 🔑 `{qpass}`")
        await reconcile_now()
        await trigger_cloud_backup()

    @client.on(events.NewMessage(pattern=r"^/sync_students$"))
    async def cmd_sync(event):
        if not admin_only(event):
            return
        for det in db["approved_details"].values():
            det["qb_state"] = None
        _write_db(db)
        await reconcile_now()
        live = sum(1 for d in db["approved_details"].values() if str(d.get("qb_state", "")).startswith("on"))
        await event.respond(f"✅ Synced with the portal database. Live Q-Bank logins: `{live}`")

    @client.on(events.NewMessage(pattern=r"^/demo(?:\s+(\d+))?$"))
    async def cmd_demo(event):
        """Create a temporary demo login for the CBT portal: /demo or /demo 5 (days)."""
        if not admin_only(event):
            return
        days = max(1, min(int(event.pattern_match.group(1) or 3), 60))
        qid, pw = "DEMO-" + _pick(4), _pick(6)
        try:
            exp = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            await supabase_upsert_student(qid, pw, "Demo Trial", True, exp, is_demo=True)
        except Exception as e:
            await event.respond(f"❌ Could not create demo login: `{e}`")
            return
        await event.respond(
            f"🧪 **Demo trial login created** ({days} day(s), max 10 questions per test)\n\n"
            f"🆔 `{qid}`\n🔑 `{pw}`\n\n🌐 {CBT_WEBAPP_BASE_URL}?uid={quote(qid)}&key={quote(pw)}"
        )

# ============================================================
# SYSTEM INITIALIZATION & APPLICATION LIFECYCLE
# ============================================================

async def main():
    global USER_CLIENT_ID, manager_bot_client
    os.makedirs("downloads", exist_ok=True)
    await start_web_server()

    logging.info("Starting Telegram user client ('session')...")
    await user_client.start()
    me = await user_client.get_me()
    USER_CLIENT_ID = me.id
    logging.info("User client connected as: %s (ID: %s)", me.first_name, me.id)

    runners = [user_client.run_until_disconnected()]

    for key, token in BOT_TOKENS.items():
        if not token or "..." in token:
            logging.warning("Skipping bot '%s' (token not configured or placeholder).", key)
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

            entity = await user_client.get_entity(bot_me.username)

            if key == "demo":
                box = setup_demo_bot_handlers(client)
                box["entity"] = entity
                active_bots[key] = client
                runners.append(client.run_until_disconnected())
                logging.info("Started [Demo Proof Bot] -> @%s", bot_me.username)
                continue

            box = setup_bot_handlers(client, key, BOT_SUBJECTS_MAP[key], BOT_TITLES_MAP[key])
            box["entity"] = entity
            active_bots[key] = client
            runners.append(client.run_until_disconnected())
            logging.info("Started [%s] -> @%s", BOT_TITLES_MAP[key], bot_me.username)
        except Exception:
            logging.exception("Failed to start bot key: %s", key)

    if manager_bot_client:
        await auto_restore_from_telegram()
        try:
            await manager_bot_client.send_message(
                ADMIN_ID,
                "🟢 **MBBS Multi-Bot & Demo Bot System Online!**\n\n"
                f"• Active Study & Demo Bots: `{len(active_bots)}` online\n"
                f"• User Client Connected: `{me.first_name}`\n"
                f"• Registered Students: `{len(db.get('users', {}))}`\n\n"
                "Demo countdown timers, 2-lecture restrictions, and automated Demo CBT logins are active."
            )
        except Exception:
            pass

    asyncio.create_task(background_loop())
    logging.info("All MBBS bots, Demo Bot, and Management Control Bot are operational.")
    await asyncio.gather(*runners)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("System shutting down gracefully.")
    except Exception:
        logging.exception("Fatal system crash")

