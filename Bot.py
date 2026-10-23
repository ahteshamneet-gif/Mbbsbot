
#!/usr/bin/env python3
# ============================================================
# MBBS Lecture & CBT Q-Bank Bot — Unified Production Engine
#  - Clean Demo Experience (Timer + Download counter only; no messy raw IDs)
#  - Demo-Exclusive Purchase Funnel (Expiry -> Year/Plan Select -> QR -> Screenshot)
#  - Dual Payment Mode: Auto Dynamic QR OR Admin Custom Uploaded QR
#  - Direct Admin-to-Student Resolution Messaging via Manager Bot
#  - Single-Use Expiring Bot Access Links (Demo -> Purchased Year Bot)
#  - Self-Disappearing Activation Links with "Thanks for purchasing" confirmation
#  - Strict Year-Wise Bot Access (Directs unapproved visitors to Demo Bot)
#  - Multimodal Gemini AI Medical Doubt Solver (Text + Image support)
#  - Supabase Cloud DB persistence + 1-Tap Telegram Restore & File Upload Restore
#  - Fast Button-Driven Manager Bot Control Center
# ============================================================

import asyncio
import base64
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
# CONFIGURATION (Environment Variables)
# ============================================================

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

# Google Gemini API Key for Medical Doubt Solver
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Payment Configuration
UPI_ID = os.getenv("UPI_ID", "").strip()
UPI_NAME = os.getenv("UPI_NAME", "MBBS Lectures").strip()
PAYMENT_QR_PATH = os.getenv("PAYMENT_QR_PATH", "payment_qr.png")
CUSTOM_QR_FILE = "custom_uploaded_qr.jpg"

# CBT student portal (GitHub Pages) & Supabase
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

TOPICS_ALL = {
    "Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Microbiology": 5, "Notes": 33,
    "Pathology": 49, "Pharmacology": 50, "Forensic Medicine and Toxicology": 51,
    "Community Medicine": 52, "General Medicine": 53, "General Surgery": 54,
    "Obstetrics and Gynecology": 55, "Pediatrics": 56, "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58, "Orthopedics": 59, "Anesthesiology": 60,
    "Radiology": 61, "Dermatology": 62, "Psychiatry": 63,
}
TOPICS_Y1 = {"Anatomy": 2, "Physiology": 3, "Biochemistry": 4, "Notes": 33}
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

BOT_SUBJECTS_MAP = {
    "all": TOPICS_ALL,
    "year_1": TOPICS_Y1,
    "year_2": TOPICS_Y2,
    "year_3": TOPICS_Y3,
    "final_year": TOPICS_FINAL,
}
DEMO_YEARS = ("year_1", "year_2", "year_3", "final_year")

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
# DATABASE & STORAGE
# ============================================================

DB_FILE = "bot_database.json"
DEFAULT_SETTINGS = {
    "expiry_enabled": False,
    "tier_access_enabled": True,
    "daily_limit_enabled": False,
    "daily_limit_max": 30,
    "cloud_backup_enabled": True,
    "demo_duration_mins": 10,
    "demo_max_downloads": 2,
    "demo_year_tier": "all",
    "demo_auto_start": True,
    "default_content": "full",
    "default_days": 0,
    "purchase_enabled": True,
    "payment_mode": "auto",  # 'auto' (dynamic generated QR) or 'manual' (admin custom uploaded QR)
    "price_full": 1000,
    "price_lec": 700,
    "ai_enabled": True,
    "demo_ai_limit": 3,
    "daily_ai_limit": 15,
}

def _empty_db():
    return {
        "users": {}, "banned": [], "approved": [], "approved_details": {},
        "settings": DEFAULT_SETTINGS.copy(), "daily_downloads": {},
        "demo_sessions": {}, "pending": {}, "orders": {},
        "coupons": {"SAVE100": 100, "SAVE200": 200},
        "daily_ai_queries": {},
        "activation_tokens": {},
    }

def normalize_db(data):
    base = _empty_db()
    if isinstance(data, dict):
        base.update(data)
    if not isinstance(base.get("settings"), dict):
        base["settings"] = {}
    for k, v in DEFAULT_SETTINGS.items():
        base["settings"].setdefault(k, v)
    for key in ("users", "approved_details", "daily_downloads", "demo_sessions", "pending", "orders", "coupons", "daily_ai_queries", "activation_tokens"):
        if not isinstance(base.get(key), dict):
            base[key] = {}
    for key in ("banned", "approved"):
        if not isinstance(base.get(key), list):
            base[key] = []

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
            logging.exception("Failed reading database file")
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
        except Exception:
            logging.exception("Failed parsing backup")
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
            async with s.get(f"{SUPABASE_URL}/rest/v1/bot_state?id=eq.1&select=data", headers=_cloud_headers()) as r:
                if r.status >= 300:
                    return False, None
                rows = await r.json()
                return True, (rows[0]["data"] if rows else None)
    except Exception:
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
            await s.post(f"{SUPABASE_URL}/rest/v1/bot_state?on_conflict=id", headers=headers, data=json.dumps({"id": 1, "data": db}))
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
        logging.exception("Failed local write")

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

async def restore_db_from_cloud(retries=4, merge_local=False):
    global _cloud_ok
    if not SUPABASE_SERVICE_KEY:
        return False
    for i in range(retries):
        ok, cloud = await cloud_load_db()
        if ok:
            if cloud:
                cloud = normalize_db(cloud)
                db.clear()
                db.update(cloud)
            ensure_admin()
            _cloud_ok = True
            _write_local(db)
            await cloud_save_db()
            return True
        await asyncio.sleep(2 * (i + 1))
    return False

ensure_admin()
_write_local(db)

# ============================================================
# HELPERS & GLOBALS
# ============================================================

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

def _pick(n):
    return "".join(secrets.choice(_ALPHA) for _ in range(n))

def esc(s):
    return re.sub(r"[*_`\[\]]", "", str(s or ""))

def display_name(uid):
    u = db.get("users", {}).get(str(uid), {})
    return (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or u.get("username") or f"Candidate {uid}")

def student_link_html(uid):
    u = db.get("users", {}).get(str(uid), {})
    if u.get("username"):
        return f"@{u['username']}"
    return f"tg://user?id={uid}"

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
        save_db(db)
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
# GEMINI AI MEDICAL DOUBT SOLVER ENGINE
# ============================================================

SYSTEM_PROMPT = (
    "You are an expert MBBS clinical instructor and medical professor. Provide concise, high-yield, "
    "exam-oriented explanations relevant to Indian university MBBS exams and NEET-PG/NEXT. "
    "Explain pathophysiological mechanisms, clinical features, diagnostic criteria, and management clearly. "
    "Keep answers strictly under 300 words with bullet points and bold keywords.\n\n"
    "Conclude your response strictly with this exact line:\n"
    "⚠️ Note: For academic prep only. Confirm all clinical decisions with standard textbooks or attending physicians."
)

async def ask_gemini_ai(prompt_text, image_bytes=None, mime_type="image/jpeg"):
    if not GEMINI_API_KEY:
        return "⚠️ AI Doubt Solver is currently offline (API key not configured by admin)."
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    parts = []
    if prompt_text:
        parts.append({"text": prompt_text})
    if image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8")
            }
        })
        
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return "❌ Could not process doubt. Please try again in a few moments."
                result = await resp.json()
                return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        logging.exception("AI Doubt query failed")
        return "❌ An error occurred while communicating with the AI. Please try again."

def check_ai_limit(uid, is_demo):
    if int(uid) == ADMIN_ID:
        return True, 0, 9999
    if not db["settings"].get("ai_enabled", True):
        return False, 0, 0
    if is_demo:
        session = db["demo_sessions"].get(str(uid), {})
        used = session.get("ai_queries_used", 0)
        max_q = db["settings"].get("demo_ai_limit", 3)
        return (used < max_q), used, max_q
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        used = db["daily_ai_queries"].setdefault(today, {}).get(str(uid), 0)
        max_q = db["settings"].get("daily_ai_limit", 15)
        return (used < max_q), used, max_q

def record_ai_query(uid, is_demo):
    if int(uid) == ADMIN_ID:
        return
    if is_demo:
        session = db["demo_sessions"].get(str(uid))
        if session:
            session["ai_queries_used"] = session.get("ai_queries_used", 0) + 1
            _write_db(db)
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        for d in [k for k in list(db["daily_ai_queries"].keys()) if k < cutoff]:
            db["daily_ai_queries"].pop(d, None)
        day_map = db["daily_ai_queries"].setdefault(today, {})
        day_map[str(uid)] = day_map.get(str(uid), 0) + 1
        _write_db(db)

# ============================================================
# SUPABASE STUDENT SYNC & CLIENTS
# ============================================================

async def supabase_upsert_student(student_id, passkey, name, active=True, expires_at=None, is_demo=False):
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    if not SUPABASE_URL or not key:
        return
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    row = {
        "student_id": student_id, "student_name": name, "passkey": passkey,
        "is_demo": is_demo, "active": active, "expires_at": expires_at,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        await s.post(f"{SUPABASE_URL}/rest/v1/students?on_conflict=student_id", headers=headers, data=json.dumps(row))

def _make_user_client():
    if not SESSION_STRING:
        return TelegramClient("session", API_ID, API_HASH)
    try:
        return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    except Exception:
        return TelegramClient("session", API_ID, API_HASH)

user_client = _make_user_client()
active_bots = {}
BOT_USERNAMES = {}
manager_bot_client = None
USER_CLIENT_ID = None
START_TIME = time.time()

user_subjects = {}
user_units = {}
user_search_state = {}
user_demo_years = {}
user_pay_state = {}
user_ai_state = {}
user_coupon_state = {}

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
        except Exception:
            continue
    return False

async def send_login_card(chat_id, user_id, title="🎉 **Your CBT Q-Bank login is ready!**", pref=None):
    qid, pw = get_or_create_qbank_creds(user_id)
    text = (
        f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{pw}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap below to open the interactive CBT app (auto-login).\n"
        "Send /mylogin any time to see this again."
    )
    buttons = [[Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))]]
    return await send_via_any(chat_id, text, buttons, pref=pref)

async def reconcile_now():
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
            except Exception:
                continue
            det["qb_state"] = want
            changed = True
            if want != "off" and not det.get("creds_sent"):
                user_bot = db.get("users", {}).get(str(uid), {}).get("bot_used")
                if await send_login_card(uid, uid, pref=user_bot):
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
            pass

    loop.call_later(1.0, lambda: loop.create_task(_go()))

# ============================================================
# DEMO SESSION ENGINE
# ============================================================

def get_demo_year(user_id=None):
    lock = db["settings"].get("demo_year_tier", "all")
    if lock in DEMO_YEARS:
        return lock
    if user_id is None:
        return None
    uid = int(user_id)
    chosen = (user_demo_years.get(uid)
              or db["users"].get(str(uid), {}).get("demo_year")
              or db["demo_sessions"].get(str(uid), {}).get("year_tier"))
    return chosen if chosen in DEMO_YEARS else None

def get_demo_topics(user_id=None):
    yr = get_demo_year(user_id)
    return BOT_SUBJECTS_MAP[yr] if yr else None

def set_demo_year(user_id, yr):
    uid = int(user_id)
    user_demo_years[uid] = yr
    db["users"].setdefault(str(uid), {})["demo_year"] = yr
    sess = db["demo_sessions"].get(str(uid))
    if sess is not None:
        sess["year_tier"] = yr
    _write_db(db)

def get_or_start_demo_session(user_id):
    s_uid = str(user_id)
    session = db["demo_sessions"].get(s_uid)
    if not session:
        session = {
            "start_time": time.time(),
            "duration_mins": db["settings"].get("demo_duration_mins", 10),
            "max_downloads": db["settings"].get("demo_max_downloads", 2),
            "downloads_used": 0,
            "ai_queries_used": 0,
            "cbt_id": "DEMO-" + _pick(4),
            "cbt_pass": _pick(6),
            "year_tier": None,
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
        exp = (datetime.now(timezone.utc) + timedelta(minutes=session.get("duration_mins", 10) + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        await supabase_upsert_student(
            session["cbt_id"], session["cbt_pass"], f"Demo: {name}",
            active=True, expires_at=exp, is_demo=True)
        session["cbt_synced"] = True
        _write_db(db)
    except Exception:
        pass

# ============================================================
# ACCESS & PURCHASE LOGIC
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

def check_access(user_id, bot_key):
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
    if db["settings"].get("tier_access_enabled", True):
        user_tier = details.get("tier", "all")
        if user_tier != "all" and user_tier != bot_key and bot_key != "demo":
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
    day_map = db["daily_downloads"].setdefault(today, {})
    day_map[str(user_id)] = day_map.get(str(user_id), 0) + 1
    _write_db(db)

def grant_plan(target_id, content_tier="full", tier=None, days=None):
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
        det["expiry"] = None
    det.setdefault("added_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if content_tier == "full":
        get_or_create_qbank_creds(uid)
    save_db(db)
    return det

def plan_price(content):
    s = db["settings"]
    return int(s.get("price_full", 1000)) if content == "full" else int(s.get("price_lec", 700))

def create_order(uid, year, content, bot_key, coupon=None):
    oid = "ORD-" + _pick(6)
    while oid in db["orders"]:
        oid = "ORD-" + _pick(6)
    
    base_amount = plan_price(content)
    discount = 0
    if coupon and coupon in db.get("coupons", {}):
        discount = db["coupons"][coupon]
    
    final_amount = max(0, base_amount - discount)

    order = {
        "id": oid, "uid": int(uid), "year": year, "content": content,
        "amount": final_amount, "base_amount": base_amount,
        "discount": discount, "coupon": coupon,
        "status": "awaiting_payment", "bot": bot_key,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    db["orders"][oid] = order
    _write_db(db)
    return order

async def build_upi_qr(order):
    if not UPI_ID:
        return None
    link = f"upi://pay?pa={quote(UPI_ID)}&pn={quote(UPI_NAME)}&am={order['amount']}&cu=INR&tn={quote(order['id'])}"
    try:
        import qrcode
        img = qrcode.make(link)
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        bio.name = "upi_qr.png"
        return bio
    except Exception:
        pass

    try:
        qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=450x450&data={quote(link)}"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(qr_api_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    bio = io.BytesIO(data)
                    bio.seek(0)
                    bio.name = "upi_qr.png"
                    return bio
    except Exception:
        pass
    return None

async def send_payment_qr(bot_client, chat_id, order):
    oid = order["id"]
    disc_text = f" (-₹{order['discount']} with code `{order['coupon']}`)" if order.get("discount") else ""
    caption = (
        f"💳 **Order Summary: `{oid}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎓 **Year:** {TIER_LABELS.get(order['year'])}\n"
        f"📦 **Plan:** {CONTENT_LABELS.get(order['content'])}\n"
        f"💰 **Total Payable: ₹{order['amount']}**{disc_text} (One-Time Lifetime)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ QR scan karke pay karein (**exactly ₹{order['amount']}**)\n"
        f"2️⃣ Niche diye gaye button par tap karke **Payment Screenshot** bhejein\n"
        f"3️⃣ Admin approve karte hi aapko aapke **{TIER_LABELS.get(order['year'])} Bot** ka one-time link mil jayega!"
        + (f"\n\n🏦 **UPI ID:** `{UPI_ID}`" if UPI_ID else "")
    )
    buttons = [
        [Button.inline("✅ I've Paid — Send Screenshot", data=f"buy_paid:{oid}".encode())],
        [Button.inline("🏷️ Apply Discount Coupon", data=f"buy_cpn:{oid}".encode())],
        [Button.inline("❌ Cancel Order", data=f"buy_cancel:{oid}".encode())]
    ]
    
    pay_mode = db["settings"].get("payment_mode", "auto")
    qr = None

    if pay_mode == "manual":
        # Prefer admin uploaded custom QR image
        if os.path.exists(CUSTOM_QR_FILE):
            qr = CUSTOM_QR_FILE
        elif os.path.exists(PAYMENT_QR_PATH):
            qr = PAYMENT_QR_PATH
        else:
            qr = await build_upi_qr(order)
    else:
        # Auto dynamic QR
        qr = await build_upi_qr(order)
        if qr is None and os.path.exists(CUSTOM_QR_FILE):
            qr = CUSTOM_QR_FILE
        elif qr is None and os.path.exists(PAYMENT_QR_PATH):
            qr = PAYMENT_QR_PATH

    if qr is not None:
        await bot_client.send_file(chat_id, qr, caption=caption, buttons=buttons)
    else:
        await bot_client.send_message(
            chat_id, caption + f"\n\n⚠️ QR not configured. Please contact {OWNER_CONTACT} for UPI payment details.",
            buttons=buttons)

def order_summary(o):
    disc = f" (Coupon: `{o['coupon']}`)" if o.get("coupon") else ""
    return (f"🧾 **Order `{o['id']}`**\n"
            f"👤 {esc(display_name(o['uid']))} (`{o['uid']}`)\n"
            f"🎓 {TIER_LABELS.get(o['year'])} | 📦 {CONTENT_LABELS.get(o['content'])}\n"
            f"💰 ₹{o['amount']}{disc} | 📌 `{o['status']}`")

def pending_orders():
    return [o for o in db.get("orders", {}).values() if o.get("status") == "pending_review"]

# ============================================================
# CLOUD BACKUP & TELEGRAM RESTORE SYSTEM
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
                         "💡 *Reply to this file with `/restore` or tap Restore in the panel anytime.*"))
    except Exception:
        logging.exception("Cloud backup failed")

async def execute_restore_from_file_bytes(raw_bytes):
    global db
    try:
        new_data = json.loads(raw_bytes.decode("utf-8"))
        norm = normalize_db(new_data)
        db.clear()
        db.update(norm)
        ensure_admin()
        _write_local(db)
        await cloud_save_db()
        await reconcile_now()
        return True, len(db.get("users", {})), len(db.get("approved", []))
    except Exception as e:
        return False, 0, str(e)

async def auto_restore_from_telegram():
    global db
    if not manager_bot_client:
        return False
    try:
        async for msg in manager_bot_client.iter_messages(ADMIN_ID, limit=50):
            if msg.file and (msg.file.name == "bot_database.json" or (msg.text and "Cloud Backup" in msg.text)):
                raw = await msg.download_media(file=bytes)
                if raw:
                    ok, u_cnt, a_cnt = await execute_restore_from_file_bytes(raw)
                    if ok:
                        return True, u_cnt, a_cnt
    except Exception:
        pass
    return False, 0, 0

# ============================================================
# TOPIC FETCHER & FAST LECTURE DELIVERY
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
        except Exception:
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
    try:
        direct_msg = await bot_client.get_messages(GROUP_ID, ids=message.id)
        if direct_msg and direct_msg.media:
            await bot_client.send_file(entity=chat_id, file=direct_msg.media, caption=caption_text, supports_streaming=True)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
    except Exception:
        pass

    async with relay_lock:
        future = asyncio.get_running_loop().create_future()
        RELAY_FUTURES[bot_key] = future
        relayed = None
        try:
            target_entity = bot_entity or (await bot_client.get_me()).username
            await user_client.forward_messages(target_entity, message)
            relayed = await asyncio.wait_for(future, timeout=15.0)
            try:
                await bot_client.send_file(entity=chat_id, file=relayed.media, caption=caption_text, supports_streaming=True)
            except Exception:
                await relayed.forward_to(chat_id)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
        except Exception:
            pass
        finally:
            RELAY_FUTURES.pop(bot_key, None)
            if relayed:
                try:
                    await relayed.delete()
                except Exception:
                    pass

    return False

# ============================================================
# STUDENT UI MENUS
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

def make_demo_year_picker(user_id, demo_user=True):
    rows = [
        [Button.inline("1️⃣ 1st Year MBBS", data=b"demo_yr:year_1"),
         Button.inline("2️⃣ 2nd Year MBBS", data=b"demo_yr:year_2")],
        [Button.inline("3️⃣ 3rd Year MBBS", data=b"demo_yr:year_3"),
         Button.inline("4️⃣ Final Year MBBS", data=b"demo_yr:final_year")],
    ]
    if demo_user:
        sess = get_or_start_demo_session(user_id)
        rows.append([Button.url("🌐 Try CBT Q-Bank (Demo)", generate_demo_webapp_url(sess["cbt_id"], sess["cbt_pass"]))])
        rows.append([Button.inline("🛒 Buy Full Access", data=b"req_access")])
    return rows

def make_main_menu(topics, user_id=None, is_demo_user=False, year_switch=False):
    subjects = [s for s in (topics or {}).keys() if s != "Notes"]
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(f"📘 {subjects[i]}", data=f"sub:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(f"📘 {subjects[i + 1]}", data=f"sub:{i + 1}".encode()))
        buttons.append(row)

    if year_switch:
        buttons.append([Button.inline("🎓 Switch MBBS Year", data=b"demo_pick_year")])

    if is_demo_user:
        sess = get_or_start_demo_session(user_id)
        buttons.append([Button.url("🌐 Try CBT Q-Bank (Demo)", generate_demo_webapp_url(sess["cbt_id"], sess["cbt_pass"]))])
        buttons.append([Button.inline("🛒 Buy Full Access", data=b"req_access")])
    elif user_id is not None and (int(user_id) == ADMIN_ID or has_qbank(user_id)):
        buttons.append([Button.url("🌐 Launch MBBS CBT Q-Bank", generate_webapp_launch_url(user_id))])
        if int(user_id) != ADMIN_ID:
            buttons.append([Button.inline("🔑 My CBT Q-Bank Login", data=b"mylogin")])
    return buttons

def make_subject_menu():
    return [
        [Button.inline("📚 Video Lectures", data=b"lectures"), Button.inline("📝 Notes & PDFs", data=b"notes")],
        [Button.inline("🎯 High-Yield MCQ Hub", data=b"mcq_hub"), Button.inline("🤖 Ask AI Tutor", data=b"ask_ai_init")],
        [Button.inline("🔎 Search Subject", data=b"search_subj"), Button.inline("⬅️ All Subjects", data=b"home")],
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
# STUDENT BOTS EVENT HANDLERS
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    entity_box = {}
    is_demo_bot = (bot_key == "demo")

    def is_demo_user(uid):
        return is_demo_bot and int(uid) != ADMIN_ID and int(uid) not in db.get("approved", [])

    def active_topics_for(uid):
        if is_demo_bot:
            return get_demo_topics(uid)
        return bot_topics

    def year_switch_allowed():
        return is_demo_bot and db["settings"].get("demo_year_tier", "all") not in DEMO_YEARS

    def menu_for(uid):
        return make_main_menu(active_topics_for(uid), uid, is_demo_user=is_demo_user(uid),
                              year_switch=year_switch_allowed())

    def demo_year_label(uid):
        return TIER_LABELS.get(get_demo_year(uid), "Not selected")

    def demo_banner(uid):
        st, rem, used, mx = check_demo_status(uid)
        return f"\n🎓 **Year:** `{demo_year_label(uid)}` | ⏱ **Time Left:** `{fmt_secs(rem)}` | 📥 **Files Left:** `{max(0, mx - used)}/{mx}`"

    async def say(event, text, alert=True):
        try:
            await event.answer(text, alert=alert)
        except AttributeError:
            await event.respond(text)

    def buy_year_buttons():
        return [
            [Button.inline("1️⃣ 1st Year MBBS", data=b"buy_y:year_1"), Button.inline("2️⃣ 2nd Year MBBS", data=b"buy_y:year_2")],
            [Button.inline("3️⃣ 3rd Year MBBS", data=b"buy_y:year_3"), Button.inline("4️⃣ Final Year MBBS", data=b"buy_y:final_year")],
            [Button.inline("🔔 Notify Admin Directly", data=b"req_notify")],
        ]

    def buy_intro():
        s = db["settings"]
        return (
            "⏰ **Demo ended. Full access lena hai?**\n\n"
            "Apni MBBS study ko seamless banayein with lifetime access to video lectures, notes, PYQs, aur CBT Q-Bank!\n\n"
            "✅ **One-Time Purchase** — No monthly renewal fees\n"
            "✅ **Lifetime Validity** — Access never expires\n\n"
            f"🩺 **Lecture + Notes + MCQ Hub**: ₹{s.get('price_full', 1000)}\n"
            f"📚 **Lecture + Notes Only**: ₹{s.get('price_lec', 700)}\n\n"
            "👇 **Neeche apna MBBS Year chunein:**"
        )

    async def guard(event, check_limit=False, need_year=True):
        uid = event.sender_id
        if is_banned(uid):
            await say(event, "⛔ You are restricted from using this service.")
            return False

        if is_demo_bot:
            if is_demo_user(uid):
                st, rem, used, mx = check_demo_status(uid)
                if st in ("new", "expired"):
                    await say(event, "⏰ Demo ended. Full access lena hai?")
                    await event.respond(buy_intro(), buttons=buy_year_buttons())
                    return False
                if check_limit and st == "download_limit_reached":
                    await say(event, f"📥 Demo limit reached ({used}/{mx} files)!")
                    await event.respond(buy_intro(), buttons=buy_year_buttons())
                    return False
            if need_year and get_demo_topics(uid) is None:
                await event.respond("🎓 **Select your MBBS Year to see its subjects:**",
                                    buttons=make_demo_year_picker(uid, is_demo_user(uid)))
                return False
        else:
            # Year-wise bots: MUST BE VERIFIED / PURCHASED
            allowed, reason = check_access(uid, bot_key)
            if not allowed:
                demo_user = BOT_USERNAMES.get("demo", "")
                demo_link = f"https://t.me/{demo_user}" if demo_user else "the Demo Bot"
                await say(event, "🔒 Paid access only.")
                await event.respond(
                    f"🔒 **Access Restricted — {bot_title}**\n\n"
                    "This bot is exclusively for verified enrolled students.\n\n"
                    "👉 **Please use our Demo Bot to try the trial and purchase your access:**",
                    buttons=[[Button.url("🧪 Open MBBS Demo Bot", demo_link)]] if demo_user else None
                )
                return False
            if check_limit and not check_daily_limit(uid)[0]:
                await say(event, "⚠️ Daily download limit reached!")
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

    @bot_client.on(events.NewMessage(pattern=r"^/(start|help|menu)(?:\s+(.*))?$"))
    async def start_handler(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)
        uid = event.sender_id
        user_search_state.pop(uid, None)
        user_ai_state.pop(uid, None)
        user_coupon_state.pop(uid, None)

        start_arg = (event.pattern_match.group(2) or "").strip()

        # Check for 1-Time Activation Link on Year Bots
        if not is_demo_bot and start_arg:
            token = start_arg
            token_data = db.get("activation_tokens", {}).get(token)
            if token_data:
                if token_data.get("used"):
                    await event.respond("❌ **This activation link has already been used and expired.**")
                    return
                if int(token_data.get("uid", 0)) != uid:
                    await event.respond("❌ **This one-time access link belongs to another student account.**")
                    return

                # Mark token used immediately so it self-destructs
                token_data["used"] = True
                token_data["used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Activate in database
                grant_plan(uid, content_tier=token_data.get("content", "full"), tier=bot_key, days=0)
                _write_db(db)

                # Edit message in Demo Bot: make the link disappear & show confirmation
                demo_msg_id = token_data.get("demo_msg_id")
                demo_bot = active_bots.get("demo")
                if demo_bot and demo_msg_id:
                    try:
                        await demo_bot.edit_message(
                            uid, demo_msg_id,
                            f"✅ **Thanks for purchasing the bot!**\n\n"
                            f"You have successfully logged into your **{BOT_TITLES_MAP.get(bot_key, bot_key)}**.\n"
                            "Happy studying! 🩺",
                            buttons=None
                        )
                    except Exception:
                        pass

                await event.respond(
                    f"🎉 **Welcome to {bot_title}!**\n\n"
                    "Thank you for purchasing the bot! Your lifetime enrollment is confirmed and activated.\n\n"
                    "Select a subject below to begin studying:",
                    buttons=menu_for(uid)
                )
                await reconcile_now()
                return

        if is_banned(uid):
            await event.respond("⛔ You are restricted from using this service.")
            return

        # DEMO BOT EXPERIENCE (Clean — No internal database IDs displayed to students)
        if is_demo_bot:
            if is_demo_user(uid):
                st, _, _, _ = check_demo_status(uid)
                sess = get_or_start_demo_session(uid)
                await ensure_demo_cbt_synced(uid, display_name(uid))
                if st == "expired":
                    await event.respond(buy_intro(), buttons=buy_year_buttons())
                    return

                if get_demo_topics(uid) is None:
                    await event.respond(
                        f"🎓 **{bot_title}**{demo_banner(uid)}\n\n"
                        "👇 **Select your MBBS Year to explore lectures, notes & MCQs:**",
                        buttons=make_demo_year_picker(uid, True)
                    )
                    return

                await event.respond(
                    f"🎓 **{bot_title}**{demo_banner(uid)}\n\n"
                    "Select a subject below to begin:",
                    buttons=menu_for(uid)
                )
                return

            if get_demo_topics(uid) is None:
                await event.respond(
                    f"🎓 **{bot_title}**\n\n👇 **Select your MBBS Year to see its subjects:**",
                    buttons=make_demo_year_picker(uid, False)
                )
                return

            await event.respond(
                f"🎓 **{bot_title}**\n\nSelect a subject below to begin studying:",
                buttons=menu_for(uid)
            )
            return

        # YEAR BOTS ACCESS (Paid / Enrolled Only)
        allowed, reason = check_access(uid, bot_key)
        if not allowed:
            demo_user = BOT_USERNAMES.get("demo", "")
            demo_link = f"https://t.me/{demo_user}" if demo_user else "the Demo Bot"
            await event.respond(
                f"🔒 **Access Restricted — {bot_title}**\n\n"
                "This bot is only for verified enrolled students.\n\n"
                "👉 **Start our Demo Bot to try the free demo and purchase your access:**",
                buttons=[[Button.url("🧪 Open MBBS Demo Bot", demo_link)]] if demo_user else None
            )
            return

        tier = get_user_content_tier(uid)
        banner = ""
        if tier == "full" and uid != ADMIN_ID:
            qid, qpass = get_or_create_qbank_creds(uid)
            banner = ("\n\n━━━━━━━━━━━━━━━━━━━━━━\n🩺 **YOUR CBT Q-BANK LOGIN:**\n"
                      f"🆔 **Student ID:** `{qid}`\n🔑 **Password:** `{qpass}`\n━━━━━━━━━━━━━━━━━━━━━━")

        await event.respond(
            f"🎓 **{bot_title}**{banner}\n\nSelect a subject below to begin studying:",
            buttons=menu_for(uid)
        )

    # PURCHASE FLOW (ONLY ON DEMO BOT)
    if is_demo_bot:
        @bot_client.on(events.CallbackQuery(data=b"req_access"))
        async def cb_req_access(event):
            sender = await event.get_sender()
            track_user(sender, bot_key)
            if is_banned(event.sender_id):
                await event.answer("⛔ Restricted.", alert=True)
                return
            await event.answer()
            await event.respond(buy_intro(), buttons=buy_year_buttons())

        @bot_client.on(events.CallbackQuery(data=b"req_notify"))
        async def cb_req_notify(event):
            sender = await event.get_sender()
            track_user(sender, bot_key)
            if manager_bot_client:
                await manager_bot_client.send_message(
                    ADMIN_ID,
                    f"🔔 Student {display_name(event.sender_id)} (`{event.sender_id}`) requested assistance for purchasing.",
                    buttons=[[Button.inline("💬 Message Student", data=f"adm_msg:{event.sender_id}".encode())]]
                )
            await event.answer("✅ Request forwarded to Admin!", alert=True)
            await event.respond(f"📨 **Access request sent!** For instant activation, message {OWNER_CONTACT}.")

        @bot_client.on(events.CallbackQuery(data=b"buy_back"))
        async def cb_buy_back(event):
            await edit(event, buy_intro(), buy_year_buttons())

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_y:(\w+)$"))
        async def cb_buy_year(event):
            yr = event.pattern_match.group(1).decode()
            s = db["settings"]
            rows = [
                [Button.inline(f"🩺 Lecture + Notes + MCQ — ₹{s.get('price_full', 1000)}", data=f"buy_p:{yr}:f".encode())],
                [Button.inline(f"📚 Lecture + Notes Only — ₹{s.get('price_lec', 700)}", data=f"buy_p:{yr}:l".encode())],
                [Button.inline("⬅️ Back", data=b"buy_back")],
            ]
            await edit(event, f"🎓 **{TIER_LABELS[yr]} Plan Selection**\n\nChoose your study package (One-Time Lifetime Access):", rows)

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_p:(\w+):([fl])$"))
        async def cb_buy_plan(event):
            uid = event.sender_id
            yr = event.pattern_match.group(1).decode()
            content = "full" if event.pattern_match.group(2).decode() == "f" else "lectures_only"
            
            for o in db["orders"].values():
                if o["uid"] == uid and o["status"] == "awaiting_payment":
                    o["status"] = "cancelled"
                    
            order = create_order(uid, yr, content, bot_key)
            await event.answer()
            await edit(event, f"🧾 Order `{order['id']}` created. Loading payment details...")
            await send_payment_qr(bot_client, event.chat_id, order)

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_paid:([A-Z0-9\-]+)$"))
        async def cb_buy_paid(event):
            uid = event.sender_id
            oid = event.pattern_match.group(1).decode()
            o = db["orders"].get(oid)
            if not o or o["uid"] != uid or o["status"] != "awaiting_payment":
                await event.answer("Order is no longer active.", alert=True)
                return
            user_pay_state[uid] = oid
            await event.answer()
            await event.respond(
                f"📤 **Send your Payment Screenshot now** (Order: `{oid}`, Amount: ₹{o['amount']}).\n"
                "Make sure the UTR / Transaction ID is clearly visible.",
                buttons=[[Button.inline("❌ Cancel Order", data=f"buy_cancel:{oid}".encode())]]
            )

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_cpn:([A-Z0-9\-]+)$"))
        async def cb_buy_coupon(event):
            uid = event.sender_id
            oid = event.pattern_match.group(1).decode()
            user_coupon_state[uid] = oid
            await event.answer()
            await event.respond(
                "🏷️ **Enter Discount Coupon Code:**\n\nSend the promo/coupon code as a text message:",
                buttons=[[Button.inline("❌ Cancel", data=f"buy_cpn_cancel:{oid}".encode())]]
            )

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_cpn_cancel:([A-Z0-9\-]+)$"))
        async def cb_buy_cpn_cancel(event):
            uid = event.sender_id
            user_coupon_state.pop(uid, None)
            oid = event.pattern_match.group(1).decode()
            o = db["orders"].get(oid)
            if o:
                await send_payment_qr(bot_client, event.chat_id, o)

        @bot_client.on(events.CallbackQuery(pattern=rb"^buy_cancel:([A-Z0-9\-]+)$"))
        async def cb_buy_cancel(event):
            uid = event.sender_id
            oid = event.pattern_match.group(1).decode()
            o = db["orders"].get(oid)
            if o and o["uid"] == uid and o["status"] == "awaiting_payment":
                o["status"] = "cancelled"
                _write_db(db)
            user_pay_state.pop(uid, None)
            user_coupon_state.pop(uid, None)
            await event.answer("Order cancelled.")
            await edit(event, f"❌ Order `{oid}` cancelled. Send /start to begin again.")

        @bot_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private and bool(e.media)))
        async def payment_proof_listener(event):
            uid = event.sender_id
            if uid in user_ai_state and not user_pay_state.get(uid):
                return
                
            oid = user_pay_state.get(uid)
            if not oid:
                return
            o = db["orders"].get(oid)
            if not o or o["uid"] != uid or o["status"] != "awaiting_payment":
                user_pay_state.pop(uid, None)
                return

            is_image = bool(event.photo) or (event.document and (event.document.mime_type or "").startswith("image/"))
            if not is_image:
                await event.respond("⚠️ Please send the payment **screenshot** as an image.")
                return

            if not manager_bot_client:
                await event.respond(f"⚠️ Payment desk is offline. Contact {OWNER_CONTACT}.")
                return

            try:
                raw = await event.download_media(file=bytes)
                f = io.BytesIO(raw)
                f.name = "proof.jpg"
                cap = (
                    "💳 **New Payment Proof Submission**\n\n"
                    + order_summary(o)
                    + f"\n🔗 Student Contact: {student_link_html(uid)}"
                )
                await manager_bot_client.send_file(
                    ADMIN_ID, f, caption=cap,
                    buttons=[
                        [Button.inline("✅ Approve & Send Access", data=f"ord_ok:{oid}".encode()),
                         Button.inline("❌ Reject", data=f"ord_no:{oid}".encode())],
                        [Button.inline("💬 Message Student", data=f"ord_msg:{oid}".encode()),
                         Button.inline("👤 View Student", data=f"adm_tier_opt:{uid}".encode())]
                    ]
                )
                o["status"] = "pending_review"
                user_pay_state.pop(uid, None)
                _write_db(db)
                await event.respond("✅ **Screenshot submitted!** Admin verify karte hi aapko aapke bot ka exclusive link mil jayega.")
            except Exception:
                await event.respond(f"❌ Failed to submit screenshot. Please message {OWNER_CONTACT}.")

    # Text router (Coupons, Search, AI doubts, Student Responses)
    @bot_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private and not (e.raw_text or "").startswith("/") and not e.media))
    async def student_text_router(event):
        uid = event.sender_id
        text = (event.raw_text or "").strip()

        # 1. Coupon code check
        if is_demo_bot and uid in user_coupon_state:
            oid = user_coupon_state.pop(uid)
            o = db["orders"].get(oid)
            if not o or o["status"] != "awaiting_payment":
                await event.respond("⚠️ Order expired or invalid.")
                return
            cpn = text.upper()
            if cpn in db.get("coupons", {}):
                disc = db["coupons"][cpn]
                o["coupon"] = cpn
                o["discount"] = disc
                o["amount"] = max(0, o["base_amount"] - disc)
                _write_db(db)
                await event.respond(f"🎉 **Coupon `{cpn}` Applied!** ₹{disc} discount deducted.")
                await send_payment_qr(bot_client, event.chat_id, o)
            else:
                await event.respond(
                    f"❌ Invalid coupon code `{esc(text)}`.",
                    buttons=[[Button.inline("Try Again", data=f"buy_cpn:{oid}".encode()),
                              Button.inline("Back to QR", data=f"buy_cpn_cancel:{oid}".encode())]]
                )
            return

        # 2. Search Subject
        if uid in user_search_state:
            st = user_search_state.pop(uid, None)
            if not await guard(event):
                return
            subj, tid = st["subject"], st["topic_id"]
            msgs = await get_topic_messages(tid)
            matches = []
            for i, m in enumerate(msgs):
                if m.media:
                    fname = get_filename(m, i + 1)
                    hay = f"{fname} {m.text or ''}".lower()
                    if all(w in hay for w in text.lower().split()):
                        matches.append((m, fname))
            if not matches:
                await event.respond(f"😕 No lectures found for **`{esc(text)}`** in **{subj}**.",
                                    buttons=[[Button.inline("⬅️ Back to Subject", data=b"sub_back")]])
                return
            buttons = []
            for m, fname in matches[:15]:
                short = fname[:39] + "..." if len(fname) > 42 else fname
                buttons.append([Button.inline(f"📄 {short}", data=f"file:{m.id}".encode())])
            buttons.append([Button.inline("⬅️ Back to Subject", data=b"sub_back")])
            await event.respond(f"🔎 Found {len(matches)} match(es) in **{subj}**:", buttons=buttons)
            return

        # 3. AI Doubt Solver (Text)
        if uid in user_ai_state:
            subj = user_ai_state[uid].get("subject", "General MBBS")
            is_demo = is_demo_user(uid)
            allowed, used, max_q = check_ai_limit(uid, is_demo)
            if not allowed:
                btn = [[Button.inline("🛒 Buy Full Access", data=b"req_access")]] if is_demo_bot else []
                await event.respond(f"⚠️ **AI Query Limit Reached ({used}/{max_q})**", buttons=btn)
                user_ai_state.pop(uid, None)
                return

            wait_msg = await event.respond("🤖 **Consulting AI Medical Professor...**")
            prompt = f"Subject: {subj}\nStudent Question: {text}"
            answer = await ask_gemini_ai(prompt)
            record_ai_query(uid, is_demo)
            
            await wait_msg.delete()
            buttons = [
                [Button.inline("❓ Ask Another Doubt", data=b"ask_ai_init")],
                [Button.inline("⬅️ Back to Subject", data=b"sub_back")]
            ]
            await event.respond(f"🩺 **AI Doubt Solver ({subj})**\n\n{answer}", buttons=buttons)
            return

    # 4. AI Doubt Solver (Image/Photo)
    @bot_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private and bool(e.photo)))
    async def ai_image_doubt_listener(event):
        uid = event.sender_id
        if uid not in user_ai_state or user_pay_state.get(uid):
            return

        subj = user_ai_state[uid].get("subject", "General MBBS")
        is_demo = is_demo_user(uid)
        allowed, used, max_q = check_ai_limit(uid, is_demo)
        if not allowed:
            await event.respond("⚠️ AI Query Limit Reached.")
            user_ai_state.pop(uid, None)
            return

        wait_msg = await event.respond("🔬 **Analyzing clinical image with AI...**")
        raw = await event.download_media(file=bytes)
        cap = (event.raw_text or "").strip() or "Please explain the clinical findings, diagnosis, and spotter points of this image."
        prompt = f"Subject: {subj}\nClinical Query: {cap}"
        answer = await ask_gemini_ai(prompt, image_bytes=raw, mime_type="image/jpeg")
        record_ai_query(uid, is_demo)
        
        await wait_msg.delete()
        buttons = [
            [Button.inline("❓ Ask Another Doubt", data=b"ask_ai_init")],
            [Button.inline("⬅️ Back to Subject", data=b"sub_back")]
        ]
        await event.respond(f"🩺 **AI Image Analysis ({subj})**\n\n{answer}", buttons=buttons)

    # Subject Navigation
    @bot_client.on(events.CallbackQuery(data=b"ask_ai_init"))
    async def cb_ask_ai_init(event):
        uid = event.sender_id
        subj = user_subjects.get(uid, "General MBBS")
        is_demo = is_demo_user(uid)
        allowed, used, max_q = check_ai_limit(uid, is_demo)
        
        if not allowed:
            await event.answer("AI Query Limit Reached!", alert=True)
            return

        user_ai_state[uid] = {"subject": subj}
        await event.answer()
        await edit(
            event,
            f"🤖 **AI Medical Doubt Solver — {subj}**\n\n"
            f"Queries used: `{used}/{max_q}`\n\n"
            "👇 **Send your medical question now as text or send a photo** (Histology slide, ECG, X-Ray, CT, or textbook diagram):",
            [[Button.inline("⬅️ Cancel & Back", data=b"sub_back")]]
        )

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def cb_home(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        user_ai_state.pop(uid, None)
        await edit(event, f"🎓 **{bot_title}**\n\nSelect a subject below:", menu_for(uid))

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def cb_sub(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        user_ai_state.pop(uid, None)
        idx = int(event.pattern_match.group(1))
        topics = active_topics_for(uid)
        subjects = [s for s in topics.keys() if s != "Notes"]
        if 0 <= idx < len(subjects):
            user_subjects[uid] = subjects[idx]
            await edit(event, f"📚 **{subjects[idx]}**\n\nChoose an option below:", make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"sub_back"))
    async def cb_sub_back(event):
        if not await guard(event):
            return
        uid = event.sender_id
        user_search_state.pop(uid, None)
        user_ai_state.pop(uid, None)
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid) or next(iter(topics))
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
            found = [m for m in notes if m.media and (key in re.sub(r"[^a-zA-Z0-9]", "", (m.text or "")).lower()
                     or key in re.sub(r"[^a-zA-Z0-9]", "", get_filename(m)).lower())]
            if not found:
                await status.edit(f"❌ No notes found for **{subj}**.")
                return

            demo_user = is_demo_user(uid)
            if demo_user:
                _, _, used, mx = check_demo_status(uid)
                found = found[:max(0, mx - used)]
                if not found:
                    await status.edit("📥 Demo download limit reached.")
                    return

            await status.edit(f"⚡ Delivering {len(found)} note(s)...")
            sent = 0
            for m in found:
                if await deliver_lecture(bot_client, bot_key, entity_box.get("entity"), event.chat_id, m, None):
                    sent += 1
                    if demo_user:
                        record_demo_download(uid)
            if sent and not demo_user:
                record_download(uid)
            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            await status.edit("❌ Could not deliver notes.")

    @bot_client.on(events.CallbackQuery(data=b"mcq_hub"))
    async def cb_mcq_hub(event):
        if not await guard(event):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid) or next(iter(topics))
        await edit(
            event,
            f"🎯 **{subj} MCQ & Question Bank Hub**\n\nSelect your practice material:",
            make_mcq_hub_menu(uid, is_demo_user=is_demo_user(uid))
        )

    @bot_client.on(events.CallbackQuery(data=b"search_subj"))
    async def cb_search_subj(event):
        if not await guard(event):
            return
        uid = event.sender_id
        topics = active_topics_for(uid)
        subj = user_subjects.get(uid)
        user_search_state[uid] = {"subject": subj, "topic_id": topics[subj]}
        await edit(event, f"🔎 **Search in {subj}**\n\nSend any keyword or topic name:",
                   [[Button.inline("⬅️ Cancel", data=b"sub_back")]])

    @bot_client.on(events.CallbackQuery(pattern=rb"^demo_yr:(\w+)$"))
    async def cb_demo_set_year(event):
        if not is_demo_bot:
            return
        uid = event.sender_id
        yr = event.pattern_match.group(1).decode()
        set_demo_year(uid, yr)
        await edit(event, f"🎓 **{bot_title} — {TIER_LABELS.get(yr)}**\n\nSelect a subject below:", menu_for(uid))

    @bot_client.on(events.CallbackQuery(data=b"demo_pick_year"))
    async def cb_demo_pick_year(event):
        if not is_demo_bot:
            return
        uid = event.sender_id
        await edit(event, f"🎓 **{bot_title}**\n\n👇 Select which MBBS Year you want to open:",
                   make_demo_year_picker(uid, is_demo_user(uid)))

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
            pass

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
# MANAGER BOT & ADMIN DASHBOARD
# ============================================================

def sales_totals():
    done = [o for o in db.get("orders", {}).values() if o.get("status") == "approved"]
    return len(done), sum(int(o.get("amount", 0)) for o in done)

def paid_counts():
    paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
    qb = sum(1 for u in paid if db["approved_details"].get(str(u), {}).get("content_tier") == "full")
    return len(paid), qb, len(paid) - qb

def make_manager_menu():
    pend_orders = len(pending_orders())
    paid_total, _, _ = paid_counts()
    demo_count = len(db.get("demo_sessions", {}))
    return [
        [Button.inline(f"💎 Verified Members ({paid_total})", data=b"mgmt_approved_p:0"),
         Button.inline(f"💳 Payments ({pend_orders})", data=b"mgmt_orders")],
        [Button.inline("📢 Broadcast Center", data=b"mgmt_announce"),
         Button.inline("💰 Sales, Prices & QR", data=b"mgmt_sales")],
        [Button.inline("🤖 AI Tutor Settings", data=b"mgmt_ai_settings"),
         Button.inline(f"🧪 Demo Control ({demo_count})", data=b"mgmt_demo")],
        [Button.inline("⚙️ Feature Toggles", data=b"mgmt_toggles"),
         Button.inline("🔍 Find Student", data=b"mgmt_find")],
        [Button.inline("👥 Registered Users", data=b"mgmt_users_p:0"),
         Button.inline("☁️ Cloud Backup", data=b"mgmt_do_backup")],
        [Button.inline("🔄 Restore Database", data=b"mgmt_restore_menu"),
         Button.inline("🔄 Refresh Dashboard", data=b"mgmt_home")]
    ]

def dashboard_text():
    n, rev = sales_totals()
    paid_total, qb, lec = paid_counts()
    pay_mode = "⚡ Dynamic UPI QR" if db["settings"].get("payment_mode") == "auto" else "🖼️ Custom Uploaded QR"
    return (
        "🎛️ **MBBS Management Control Center**\n\n"
        f"🤖 **Managed Bots:** `{len(active_bots)}` online\n"
        f"👥 **Total Registered Students:** `{len(db.get('users', {}))}`\n"
        f"💎 **Verified Paid Members:** `{paid_total}` (🩺 Full: `{qb}` | 📚 Lec: `{lec}`)\n"
        f"💳 **Approved Sales:** `{n}` | 💵 **Total Revenue:** **₹{rev}**\n"
        f"⏳ **Pending Verifications:** `{len(pending_orders())}`\n"
        f"🖼️ **Active Payment Mode:** `{pay_mode}`\n"
        f"🤖 **AI Doubt Engine:** `{'🟢 Active' if db['settings'].get('ai_enabled') else '🔴 Disabled'}`\n\n"
        "Select an action below:"
    )

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
        [Button.inline("➕ +30 Days", data=f"ex:{uid}:30".encode()),
         Button.inline("➕ +90 Days", data=f"ex:{uid}:90".encode()),
         Button.inline("♾ Lifetime", data=f"ex:{uid}:0".encode())],
        [Button.inline("💬 Send Message to Student", data=f"adm_msg:{uid}".encode())],
    ]
    if ctier == "full":
        buttons.append([Button.inline("🔑 Send Login Card", data=f"adm_send_cred:{uid}".encode())])
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
    def admin_only(event):
        return event.sender_id == ADMIN_ID

    @client.on(events.NewMessage(pattern=r"^/(start|panel|menu)$"))
    async def manager_start(event):
        if not admin_only(event):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await event.respond(dashboard_text(), buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_home"))
    async def cb_home(event):
        if not admin_only(event):
            return
        ADMIN_STATES.pop(ADMIN_ID, None)
        await edit(event, dashboard_text(), make_manager_menu())

    # 1. Verified Paid Members List
    @client.on(events.CallbackQuery(pattern=rb"^mgmt_approved_p:(\d+)$"))
    async def cb_approved_page(event):
        if not admin_only(event):
            return
        paid = [u for u in db.get("approved", []) if u != ADMIN_ID]
        if not paid:
            await edit(event, "ℹ️ **No verified paid students found yet.**",
                       [[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]])
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
        user_bot = db.get("users", {}).get(str(uid), {}).get("bot_used")
        ok = await send_login_card(uid, uid, pref=user_bot)
        await event.answer("Login card sent!" if ok else "Could not reach user.", alert=True)

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

    # 2. Broadcast Center
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
        await edit(event, "📢 **Broadcast Center**\n\nSelect the target audience for your announcement:", rows)

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
            [[Button.inline("❌ Cancel Broadcast", data=b"mgmt_home")]]
        )

    # 3. Payments Approval (Generates One-Time Access Link & Direct Chat)
    @client.on(events.CallbackQuery(data=b"mgmt_orders"))
    async def cb_orders(event):
        if not admin_only(event):
            return
        pend = pending_orders()
        if not pend:
            await edit(event, "✅ **No payments waiting for verification.**",
                       [[Button.inline("⬅️ Menu", data=b"mgmt_home")]])
            return
        msg = f"💳 **Pending Payments ({len(pend)}):**\n\n"
        rows = []
        for o in pend[-6:]:
            msg += f"• `{o['id']}` — {esc(display_name(o['uid']))} — ₹{o['amount']} ({TIER_SHORT.get(o['year'])})\n"
            rows.append([
                Button.inline(f"✅ Approve {o['id']}", data=f"ord_ok:{o['id']}".encode()),
                Button.inline(f"❌ Reject", data=f"ord_no:{o['id']}".encode()),
                Button.inline(f"💬 Chat", data=f"ord_msg:{o['id']}".encode())
            ])
        rows.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await edit(event, msg, rows)

    @client.on(events.CallbackQuery(pattern=rb"^ord_msg:([A-Z0-9\-]+)$"))
    async def cb_order_message(event):
        if not admin_only(event):
            return
        oid = event.pattern_match.group(1).decode()
        o = db["orders"].get(oid)
        if not o:
            await event.answer("Order not found.", alert=True)
            return
        uid = o["uid"]
        ADMIN_STATES[ADMIN_ID] = f"WAITING_STUDENT_MSG:{uid}:{oid}"
        await edit(
            event,
            f"💬 **Message Student regarding Order `{oid}`**\n\n"
            f"👤 Student: **{esc(display_name(uid))}** (`{uid}`)\n\n"
            "Send the message you want to deliver to the student (e.g. asking for clearer screenshot, UTR ID clarification, etc.):",
            [[Button.inline("❌ Cancel", data=b"mgmt_orders")]]
        )

    @client.on(events.CallbackQuery(pattern=rb"^adm_msg:(\d+)$"))
    async def cb_admin_direct_msg(event):
        if not admin_only(event):
            return
        uid = int(event.pattern_match.group(1))
        ADMIN_STATES[ADMIN_ID] = f"WAITING_DIRECT_MSG:{uid}"
        await edit(
            event,
            f"💬 **Send Message to {esc(display_name(uid))} (`{uid}`)**\n\n"
            "Send the text message you want to deliver directly to this student:",
            [[Button.inline("❌ Cancel", data=f"adm_tier_opt:{uid}".encode())]]
        )

    @client.on(events.CallbackQuery(pattern=rb"^ord_ok:([A-Z0-9\-]+)$"))
    async def cb_order_ok(event):
        if not admin_only(event):
            return
        oid = event.pattern_match.group(1).decode()
        o = db["orders"].get(oid)
        if not o or o["status"] != "pending_review":
            await event.answer("Order not pending.", alert=True)
            return
        uid = o["uid"]
        target_year = o["year"]
        
        # Generate 1-time activation token
        token = "ACT-" + _pick(12)
        target_bot_username = BOT_USERNAMES.get(target_year)
        
        # Save token details in db
        db.setdefault("activation_tokens", {})[token] = {
            "token": token,
            "uid": uid,
            "year": target_year,
            "content": o["content"],
            "used": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "demo_msg_id": None
        }

        o["status"] = "approved"
        _write_db(db)
        await event.answer("✅ Approved! Activation link sent to Demo Bot.", alert=True)
        await edit(event, order_summary(o) + "\n\n✅ **APPROVED**", [[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

        # Deliver One-Time Access Card inside Demo Bot
        demo_bot = active_bots.get("demo")
        if demo_bot and target_bot_username:
            link = f"https://t.me/{target_bot_username}?start={token}"
            access_msg = (
                f"🎉 **Payment Verified Successfully!**\n\n"
                f"🎓 **Enrolled Year:** {TIER_LABELS.get(target_year)}\n"
                f"📦 **Plan:** {CONTENT_LABELS.get(o['content'])}\n"
                f"📅 **Validity:** Lifetime Access\n\n"
                f"👇 **Tap the button below to claim and activate your {TIER_LABELS.get(target_year)} Bot:**\n"
                "*(This is a secure 1-time activation link exclusively for your account)*"
            )
            buttons = [[Button.url(f"🚀 Open & Claim {TIER_LABELS.get(target_year)} Bot", link)]]
            sent_msg = await demo_bot.send_message(uid, access_msg, buttons=buttons)
            if sent_msg:
                db["activation_tokens"][token]["demo_msg_id"] = sent_msg.id
                _write_db(db)

        await trigger_cloud_backup()

    @client.on(events.CallbackQuery(pattern=rb"^ord_no:([A-Z0-9\-]+)$"))
    async def cb_order_no(event):
        if not admin_only(event):
            return
        oid = event.pattern_match.group(1).decode()
        o = db["orders"].get(oid)
        if o:
            o["status"] = "rejected"
            _write_db(db)
            demo_bot = active_bots.get("demo")
            if demo_bot:
                await demo_bot.send_message(
                    o["uid"],
                    f"❌ **Payment verification update (Order `{oid}`):**\n"
                    "We could not verify your payment screenshot. Please message our support desk directly: "
                    f"{OWNER_CONTACT}",
                    buttons=[[Button.inline("💬 Reply to Admin", data=b"req_notify")]]
                )
        await event.answer("Rejected.", alert=True)
        await edit(event, f"❌ Order `{oid}` rejected.", [[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    # 4. Sales, Prices, QR Mode & Coupons
    @client.on(events.CallbackQuery(data=b"mgmt_sales"))
    async def cb_sales(event):
        if not admin_only(event):
            return
        n, rev = sales_totals()
        s = db["settings"]
        pmode = s.get("payment_mode", "auto")
        mode_btn = "⚡ Mode: Dynamic UPI QR" if pmode == "auto" else "🖼️ Mode: Custom Uploaded QR"
        rows = [
            [Button.inline(mode_btn, data=b"tog_pay_mode")],
            [Button.inline("📤 Upload New Custom QR Image", data=b"mgmt_upload_qr")],
            [Button.inline(f"✏️ Price Full: ₹{s.get('price_full', 1000)}", data=b"price_set:f"),
             Button.inline(f"✏️ Price Lec: ₹{s.get('price_lec', 700)}", data=b"price_set:l")],
            [Button.inline(f"🏷️ Manage Coupons ({len(db.get('coupons', {}))})", data=b"mgmt_coupons")],
            [Button.inline(f"🛒 Toggle Purchase: {'🟢 ON' if s.get('purchase_enabled') else '🔴 OFF'}", data=b"tog:purchase_enabled")],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
        ]
        has_custom = "✅ Uploaded (`custom_uploaded_qr.jpg`)" if os.path.exists(CUSTOM_QR_FILE) else "❌ Not uploaded"
        await edit(
            event,
            f"💰 **Sales, Payment QR & Pricing Controls**\n\n"
            f"• **Current QR Mode:** `{pmode.upper()}`\n"
            f"• **Custom QR Status:** {has_custom}\n"
            f"• **Approved Orders:** `{n}` | **Total Revenue:** **₹{rev}**\n\n"
            "Tap any item to edit or switch mode:", rows
        )

    @client.on(events.CallbackQuery(data=b"tog_pay_mode"))
    async def cb_tog_pay_mode(event):
        if not admin_only(event):
            return
        cur = db["settings"].get("payment_mode", "auto")
        new_mode = "manual" if cur == "auto" else "auto"
        db["settings"]["payment_mode"] = new_mode
        save_db(db)
        await event.answer(f"Switched to {new_mode.upper()} QR mode!", alert=True)
        await cb_sales(event)

    @client.on(events.CallbackQuery(data=b"mgmt_upload_qr"))
    async def cb_mgmt_upload_qr(event):
        if not admin_only(event):
            return
        ADMIN_STATES[ADMIN_ID] = "WAITING_QR_PHOTO"
        await edit(
            event,
            "🖼️ **Upload Custom Payment QR Image**\n\n"
            "Please send the image of your QR code (from PhonePe, Google Pay, Paytm, or your bank) right now in this chat:",
            [[Button.inline("❌ Cancel", data=b"mgmt_sales")]]
        )

    @client.on(events.CallbackQuery(data=b"mgmt_coupons"))
    async def cb_coupons(event):
        if not admin_only(event):
            return
        cpns = db.get("coupons", {})
        msg = f"🏷️ **Active Discount Coupons ({len(cpns)}):**\n\n"
        rows = []
        for code, disc in cpns.items():
            msg += f"• `{code}`: ₹{disc} discount\n"
            rows.append([Button.inline(f"🗑️ Delete {code}", data=f"cpn_del:{code}".encode())])
        rows.append([Button.inline("➕ Create New Coupon", data=b"cpn_add")])
        rows.append([Button.inline("⬅️ Back", data=b"mgmt_sales")])
        await edit(event, msg, rows)

    @client.on(events.CallbackQuery(pattern=rb"^cpn_del:(.+)$"))
    async def cb_cpn_del(event):
        if not admin_only(event):
            return
        code = event.pattern_match.group(1).decode()
        db.get("coupons", {}).pop(code, None)
        save_db(db)
        await event.answer(f"Coupon {code} deleted!", alert=True)
        await cb_coupons(event)

    @client.on(events.CallbackQuery(data=b"cpn_add"))
    async def cb_cpn_add(event):
        if not admin_only(event):
            return
        ADMIN_STATES[ADMIN_ID] = "WAITING_COUPON"
        await edit(event, "🏷️ Send new coupon name and discount separated by a space.\nExample: `NEET2026 250`",
                   [[Button.inline("❌ Cancel", data=b"mgmt_coupons")]])

    # 5. AI Settings
    @client.on(events.CallbackQuery(data=b"mgmt_ai_settings"))
    async def cb_ai_settings(event):
        if not admin_only(event):
            return
        s = db["settings"]
        ai_on = "🟢 ON" if s.get("ai_enabled", True) else "🔴 OFF"
        d_lim = s.get("daily_ai_limit", 15)
        demo_lim = s.get("demo_ai_limit", 3)
        rows = [
            [Button.inline(f"🤖 AI Solver: {ai_on}", data=b"tog:ai_enabled")],
            [Button.inline(f"Paid Daily Limit: {d_lim}/day", data=b"noop")],
            [Button.inline(("• " if d_lim == n else "") + f"{n}/d", data=f"set_ai_lim:{n}".encode()) for n in (10, 15, 25, 50)],
            [Button.inline(f"Demo Total Limit: {demo_lim} queries", data=b"noop")],
            [Button.inline(("• " if demo_lim == n else "") + f"{n} free", data=f"set_demo_ai:{n}".encode()) for n in (1, 3, 5)],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
        ]
        await edit(event, "🤖 **AI Doubt Solver Configuration**", rows)

    @client.on(events.CallbackQuery(pattern=rb"^set_ai_lim:(\d+)$"))
    async def cb_set_ai_lim(event):
        if not admin_only(event):
            return
        db["settings"]["daily_ai_limit"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_ai_settings(event)

    @client.on(events.CallbackQuery(pattern=rb"^set_demo_ai:(\d+)$"))
    async def cb_set_demo_ai(event):
        if not admin_only(event):
            return
        db["settings"]["demo_ai_limit"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_ai_settings(event)

    # 6. Demo Control Panel (Duration, Downloads, and Demo Users Inspector)
    @client.on(events.CallbackQuery(data=b"mgmt_demo"))
    async def cb_demo(event):
        if not admin_only(event):
            return
        s = db["settings"]
        dur = s.get("demo_duration_mins", 10)
        dl = s.get("demo_max_downloads", 2)
        sess_cnt = len(db.get("demo_sessions", {}))
        rows = [
            [Button.inline(f"👥 View Demo Users ({sess_cnt})", data=b"mgmt_demo_users_p:0")],
            [Button.inline(("• " if dur == m else "") + f"{m}m", data=f"dm_dur:{m}".encode()) for m in (5, 10, 15, 30)],
            [Button.inline(("• " if dl == n else "") + f"{n} files", data=f"dm_dl:{n}".encode()) for n in (1, 2, 3, 5)],
            [Button.inline(f"Auto-Start: {'🟢 ON' if s.get('demo_auto_start') else '🔴 OFF'}", data=b"tog:demo_auto_start")],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
        ]
        await edit(event, f"🧪 **Demo Trial Controls**\n\n• Duration: `{dur}m` | Max Files: `{dl}` | Active Sessions: `{sess_cnt}`", rows)

    @client.on(events.CallbackQuery(pattern=rb"^mgmt_demo_users_p:(\d+)$"))
    async def cb_demo_users_page(event):
        if not admin_only(event):
            return
        sessions = list(db.get("demo_sessions", {}).items())
        if not sessions:
            await edit(event, "ℹ️ **No students in demo trial right now.**", [[Button.inline("⬅️ Back", data=b"mgmt_demo")]])
            return
        per = 5
        pages = max(1, (len(sessions) + per - 1) // per)
        page = max(0, min(int(event.pattern_match.group(1)), pages - 1))
        msg = f"🧪 **Demo Students ({len(sessions)}) — Page {page + 1}/{pages}:**\n\n"
        rows = []
        for uid_str, sess in sessions[page * per:(page + 1) * per]:
            st, rem, used, mx = check_demo_status(uid_str)
            name = display_name(uid_str)
            u = db.get("users", {}).get(uid_str, {})
            uname = f"@{u['username']}" if u.get("username") else "No username"
            yr = TIER_SHORT.get(sess.get("year_tier"), "None")
            status_badge = "🟢 Active" if st == "active" else ("⏰ Expired" if st == "expired" else "📥 Limit Reached")
            msg += (
                f"• **{esc(name)}** ({esc(uname)})\n"
                f"  └ ID: `{uid_str}` | Yr: `{yr}` | Status: `{status_badge}`\n"
                f"  └ Left: `{fmt_secs(rem)}` | Files: `{used}/{mx}` | AI: `{sess.get('ai_queries_used', 0)}`\n\n"
            )
            rows.append([
                Button.inline(f"💬 Chat", data=f"adm_msg:{uid_str}".encode()),
                Button.inline(f"🔄 Reset Demo", data=f"dm_reset_one:{uid_str}".encode()),
                Button.inline(f"⚡ Full Pass", data=f"adm_set_tier:{uid_str}:full".encode())
            ])
        nav = []
        if page > 0:
            nav.append(Button.inline("◀ Prev", data=f"mgmt_demo_users_p:{page - 1}".encode()))
        if page < pages - 1:
            nav.append(Button.inline("Next ▶", data=f"mgmt_demo_users_p:{page + 1}".encode()))
        if nav:
            rows.append(nav)
        rows.append([Button.inline("⬅️ Back to Demo Settings", data=b"mgmt_demo")])
        await edit(event, msg, rows)

    @client.on(events.CallbackQuery(pattern=rb"^dm_reset_one:(\d+)$"))
    async def cb_dm_reset_one(event):
        if not admin_only(event):
            return
        uid_str = event.pattern_match.group(1).decode()
        db["demo_sessions"].pop(uid_str, None)
        user_demo_years.pop(int(uid_str), None)
        save_db(db)
        await event.answer("Demo session reset for student!", alert=True)
        await send_via_any(int(uid_str), "🎁 **Your MBBS Demo Trial has been renewed!** Send /start to begin.", pref="demo")
        await cb_demo(event)

    @client.on(events.CallbackQuery(pattern=rb"^dm_dur:(\d+)$"))
    async def cb_dm_dur(event):
        if not admin_only(event):
            return
        db["settings"]["demo_duration_mins"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_demo(event)

    @client.on(events.CallbackQuery(pattern=rb"^dm_dl:(\d+)$"))
    async def cb_dm_dl(event):
        if not admin_only(event):
            return
        db["settings"]["demo_max_downloads"] = int(event.pattern_match.group(1))
        save_db(db)
        await cb_demo(event)

    # 7. Find / Search Student
    @client.on(events.CallbackQuery(data=b"mgmt_find"))
    async def cb_find(event):
        if not admin_only(event):
            return
        ADMIN_STATES[ADMIN_ID] = "WAITING_FIND"
        await edit(event, "🔍 **Search Student**\n\nSend Telegram ID, Name, or @username:",
                   [[Button.inline("❌ Cancel", data=b"mgmt_home")]])

    # 8. Registered Users Viewer
    @client.on(events.CallbackQuery(pattern=rb"^mgmt_users_p:(\d+)$"))
    async def cb_users_page(event):
        if not admin_only(event):
            return
        users = list(db.get("users", {}).items())
        if not users:
            await edit(event, "ℹ️ No registered users found.", [[Button.inline("⬅️ Menu", data=b"mgmt_home")]])
            return
        per = 6
        pages = max(1, (len(users) + per - 1) // per)
        page = max(0, min(int(event.pattern_match.group(1)), pages - 1))
        msg = f"👥 **Registered Users ({len(users)}) — Page {page + 1}/{pages}:**\n\n"
        buttons = []
        for uid_str, u in users[page * per:(page + 1) * per]:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Student"
            uname = f"@{u['username']}" if u.get("username") else "No username"
            approved = int(uid_str) in db.get("approved", [])
            tier = db["approved_details"].get(uid_str, {}).get("content_tier") if approved else None
            badge = "🩺 Full" if tier == "full" else ("📚 Lec" if tier == "lectures_only" else "⏳ Free")
            msg += f"• **{esc(name)}** ({esc(uname)})\n  └ ID: `{uid_str}` | Plan: **{badge}** | Bot: `{u.get('bot_used', 'all')}`\n\n"
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

    # 9. Feature Toggles
    @client.on(events.CallbackQuery(data=b"mgmt_toggles"))
    async def cb_toggles(event):
        if not admin_only(event):
            return
        s = db["settings"]
        on = lambda k: "🟢 ON" if s.get(k) else "🔴 OFF"
        rows = [
            [Button.inline(f"⏳ Expiry System: {on('expiry_enabled')}", data=b"tog:expiry_enabled")],
            [Button.inline(f"🎓 Year Locking: {on('tier_access_enabled')}", data=b"tog:tier_access_enabled")],
            [Button.inline(f"🛡️ Daily Anti-Leech: {on('daily_limit_enabled')}", data=b"tog:daily_limit_enabled")],
            [Button.inline(f"🛒 Purchase Flow: {on('purchase_enabled')}", data=b"tog:purchase_enabled")],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
        ]
        await edit(event, "⚙️ **System Feature Controls**", rows)

    # 10. Database Restore Menu
    @client.on(events.CallbackQuery(data=b"mgmt_restore_menu"))
    async def cb_restore_menu(event):
        if not admin_only(event):
            return
        text = (
            "🔄 **Database Restore Center**\n\n"
            "Restore all verified students, settings, and orders.\n\n"
            "Choose a method:\n"
            "1️⃣ **Instant Restore:** Scan chat for latest backup and apply.\n"
            "2️⃣ **Send File:** Upload your `bot_database.json` directly here.\n"
            "3️⃣ **Reply:** Reply to any backup message with `/restore`."
        )
        buttons = [
            [Button.inline("⚡ Instant Restore from Chat History", data=b"mgmt_do_chat_restore")],
            [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
        ]
        await edit(event, text, buttons)

    @client.on(events.CallbackQuery(data=b"mgmt_do_chat_restore"))
    async def cb_do_chat_restore(event):
        if not admin_only(event):
            return
        await event.answer("Scanning chat for backups...")
        ok, u_cnt, a_cnt = await auto_restore_from_telegram()
        if ok:
            await edit(
                event,
                f"✅ **Database Restored from Chat Backup!**\n\n"
                f"👥 Total Students: `{u_cnt}`\n"
                f"💎 Verified Paid: `{a_cnt}`\n\n"
                "Everything has been synced with Supabase and local cache.",
                [[Button.inline("⬅️ Return to Dashboard", data=b"mgmt_home")]]
            )
        else:
            await edit(
                event,
                "⚠️ **No valid backup file found in recent messages.**\n\n"
                "Please upload your `bot_database.json` file directly into this chat to restore it.",
                [[Button.inline("⬅️ Back", data=b"mgmt_restore_menu")]]
            )

    # General Admin Listener (Uploads, Direct Messages, Prices, Coupons, Finding)
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def admin_input_listener(event):
        if not admin_only(event):
            return
        text = (event.raw_text or "").strip()

        # Custom QR photo upload
        state = ADMIN_STATES.get(ADMIN_ID, "")
        if state == "WAITING_QR_PHOTO" and bool(event.photo):
            ADMIN_STATES.pop(ADMIN_ID, None)
            status = await event.respond("⏳ **Saving custom payment QR image...**")
            try:
                await event.download_media(file=CUSTOM_QR_FILE)
                db["settings"]["payment_mode"] = "manual"
                save_db(db)
                await status.edit(
                    "✅ **Custom QR Image Saved Successfully!**\n\n"
                    "• Payment Mode switched to: **🖼️ Custom Uploaded QR**\n"
                    "• Students initiating purchases will now receive this exact QR code image.",
                    buttons=[[Button.inline("💰 View Sales & QR Settings", data=b"mgmt_sales")]]
                )
            except Exception:
                await status.edit("❌ Failed to save QR image. Please try again.")
            return

        # Document upload restore
        if event.file and (event.file.name == "bot_database.json" or "restore" in text.lower()):
            status = await event.respond("⏳ **Analyzing and restoring database file...**")
            raw = await event.download_media(file=bytes)
            if raw:
                ok, u_cnt, a_cnt = await execute_restore_from_file_bytes(raw)
                if ok:
                    await status.edit(
                        f"✅ **Database File Restored Successfully!**\n\n"
                        f"👥 Total Students: `{u_cnt}`\n"
                        f"💎 Verified Paid: `{a_cnt}`",
                        buttons=[[Button.inline("🎛️ Open Dashboard", data=b"mgmt_home")]]
                    )
                    return
                else:
                    await status.edit(f"❌ Restore failed: `{a_cnt}`")
                    return

        # Reply with /restore
        if text.lower() == "/restore" and event.is_reply:
            reply_msg = await event.get_reply_message()
            if reply_msg and reply_msg.file:
                status = await event.respond("⏳ **Restoring from replied backup file...**")
                raw = await reply_msg.download_media(file=bytes)
                if raw:
                    ok, u_cnt, a_cnt = await execute_restore_from_file_bytes(raw)
                    if ok:
                        await status.edit(
                            f"✅ **Database Restored Successfully!**\n\n"
                            f"👥 Total Students: `{u_cnt}`\n"
                            f"💎 Verified Paid: `{a_cnt}`",
                            buttons=[[Button.inline("🎛️ Open Dashboard", data=b"mgmt_home")]]
                        )
                        return
                    else:
                        await status.edit(f"❌ Restore failed: `{a_cnt}`")
                        return

        # Direct Chat with Student Regarding Payment Order
        if state.startswith("WAITING_STUDENT_MSG:"):
            parts = state.split(":")
            uid, oid = int(parts[1]), parts[2]
            ADMIN_STATES.pop(ADMIN_ID, None)
            demo_bot = active_bots.get("demo")
            if demo_bot:
                student_msg = (
                    f"📩 **Message from Admin regarding Order `{oid}`:**\n\n"
                    f"{text}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👉 *If requested, you can send your new screenshot or reply directly by typing below.*"
                )
                try:
                    await demo_bot.send_message(uid, student_msg)
                    await event.respond(
                        f"✅ **Message delivered to {esc(display_name(uid))} (`{uid}`)!**",
                        buttons=[[Button.inline("💳 Return to Payments", data=b"mgmt_orders")]]
                    )
                    return
                except Exception:
                    pass
            await event.respond("❌ Could not deliver message to student.", buttons=[[Button.inline("💳 Payments", data=b"mgmt_orders")]])
            return

        # Direct Chat with Any Registered Student
        if state.startswith("WAITING_DIRECT_MSG:"):
            uid = int(state.split(":")[1])
            ADMIN_STATES.pop(ADMIN_ID, None)
            delivered = await send_via_any(
                uid,
                f"📩 **Direct Message from MBBS Admin:**\n\n{text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Contact: {OWNER_CONTACT}"
            )
            if delivered:
                await event.respond(f"✅ **Message delivered to {esc(display_name(uid))}!**",
                                    buttons=[[Button.inline("👤 View Student", data=f"adm_tier_opt:{uid}".encode())]])
            else:
                await event.respond("❌ Could not reach student.",
                                    buttons=[[Button.inline("👤 View Student", data=f"adm_tier_opt:{uid}".encode())]])
            return

        if state == "WAITING_COUPON":
            ADMIN_STATES.pop(ADMIN_ID, None)
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                code, disc = parts[0].upper(), int(parts[1])
                db.setdefault("coupons", {})[code] = disc
                save_db(db)
                await event.respond(f"✅ Created coupon `{code}` for ₹{disc} discount!",
                                    buttons=[[Button.inline("🏷️ View Coupons", data=b"mgmt_coupons")]])
            else:
                await event.respond("❌ Invalid format. Please write like: `SAVE150 150`")
            return

        if state.startswith("WAITING_PRICE:"):
            which = state.split(":")[1]
            ADMIN_STATES.pop(ADMIN_ID, None)
            if text.isdigit() and int(text) > 0:
                db["settings"]["price_full" if which == "f" else "price_lec"] = int(text)
                save_db(db)
                await event.respond(f"✅ Price updated to ₹{int(text)}!",
                                    buttons=[[Button.inline("💰 Sales & Prices", data=b"mgmt_sales")]])
            return

        if state == "WAITING_FIND":
            ADMIN_STATES.pop(ADMIN_ID, None)
            q = text.lstrip("@").lower()
            found = []
            for uid, info in db.get("users", {}).items():
                if q in uid or q in f"{info.get('first_name', '')} {info.get('last_name', '')} {info.get('username', '')}".lower():
                    found.append(int(uid))
            if not found:
                await event.respond(f"😕 No student found matching `{esc(text)}`.",
                                    buttons=[[Button.inline("🔍 Try Again", data=b"mgmt_find"), Button.inline("⬅️ Menu", data=b"mgmt_home")]])
                return
            if len(found) == 1:
                t, b = make_student_profile_view(found[0])
                await event.respond(t, buttons=b)
            else:
                rows = [[Button.inline(f"👤 {display_name(u)[:22]}", data=f"adm_tier_opt:{u}".encode())] for u in found[:10]]
                rows.append([Button.inline("⬅️ Menu", data=b"mgmt_home")])
                await event.respond(f"🔍 Found {len(found)} students:", buttons=rows)
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
            return

    @client.on(events.CallbackQuery(pattern=rb"^price_set:([fl])$"))
    async def cb_price_set(event):
        if not admin_only(event):
            return
        which = event.pattern_match.group(1).decode()
        ADMIN_STATES[ADMIN_ID] = f"WAITING_PRICE:{which}"
        await edit(event, "✏️ Send new price in numbers (e.g. `999`):", [[Button.inline("❌ Cancel", data=b"mgmt_sales")]])

    @client.on(events.CallbackQuery(pattern=rb"^tog:(.+)$"))
    async def cb_toggle(event):
        if not admin_only(event):
            return
        key = event.pattern_match.group(1).decode()
        if key in db["settings"]:
            db["settings"][key] = not db["settings"][key]
            save_db(db)
            await event.answer(f"{key} toggled!", alert=True)
            if key == "ai_enabled":
                await cb_ai_settings(event)
            elif key == "demo_auto_start":
                await cb_demo(event)
            else:
                await cb_toggles(event)

    @client.on(events.CallbackQuery(data=b"mgmt_do_backup"))
    async def cb_do_backup(event):
        if not admin_only(event):
            return
        await trigger_cloud_backup(force=True)
        await event.answer("Backup sent to chat!", alert=True)

# ============================================================
# WEB SERVER & BACKGROUND LOOP
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
            pass
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)

async def health_check(request):
    return web.json_response({
        "status": "MBBS Bot Engine Online 24/7",
        "uptime": int(time.time() - START_TIME),
        "ai_active": bool(GEMINI_API_KEY) and db["settings"].get("ai_enabled", True),
        "payment_mode": db["settings"].get("payment_mode", "auto"),
    })

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

# ============================================================
# MAIN ENTRYPOINT
# ============================================================

async def main():
    global USER_CLIENT_ID, manager_bot_client
    if not API_ID or not API_HASH:
        raise SystemExit("API_ID or API_HASH missing.")
    
    os.makedirs("downloads", exist_ok=True)
    await start_web_server()

    if SUPABASE_SERVICE_KEY:
        await restore_db_from_cloud()
    ensure_admin()

    await user_client.start()
    me = await user_client.get_me()
    USER_CLIENT_ID = me.id
    runners = [user_client.run_until_disconnected()]

    for key, token in BOT_TOKENS.items():
        if not token:
            continue
        try:
            client = TelegramClient(f"bot_session_{key}", API_ID, API_HASH)
            await client.start(bot_token=token)

            bot_me = await client.get_me()
            BOT_USERNAMES[key] = bot_me.username

            if key == "manager":
                manager_bot_client = client
                setup_manager_bot_handlers(client)
                runners.append(client.run_until_disconnected())
                continue

            entity = None
            try:
                entity = await user_client.get_entity(bot_me.username)
            except Exception:
                pass

            box = setup_bot_handlers(client, key, BOT_SUBJECTS_MAP.get(key, {}), BOT_TITLES_MAP[key])
            box["entity"] = entity
            active_bots[key] = client
            runners.append(client.run_until_disconnected())
        except Exception as e:
            logging.error(f"Error starting {key}: {e}")

    if manager_bot_client:
        if not _cloud_ok:
            await auto_restore_from_telegram()
        try:
            await manager_bot_client.send_message(
                ADMIN_ID,
                "🟢 **MBBS Multi-Bot Ecosystem Online!**\n\n"
                "• 🧪 Clean Demo Experience: Active\n"
                "• 🖼️ Dual Payment Mode (Auto QR / Custom Uploaded QR): Active\n"
                "• 💬 Direct Admin-to-Student Chat Engine: Active\n"
                "• 🚀 Single-Use Disappearing Activation Links: Active\n"
                "• 🤖 Gemini AI Medical Doubt Solver: Active\n"
                "• 🔄 Cloud Database Restore System: Active",
                buttons=make_manager_menu()
            )
        except Exception:
            pass

    asyncio.create_task(background_loop())
    schedule_reconcile()
    await asyncio.gather(*runners)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
