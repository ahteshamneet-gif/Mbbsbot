
import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
from aiohttp import web

from telethon import TelegramClient, events, Button
from telethon.errors import RPCError, FloodWaitError, ChatForwardsRestrictedError

# ============================================================
# CONFIGURATION & ENVIRONMENT
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

# Live GitHub Pages CBT Web App URL
CBT_WEBAPP_BASE_URL = os.getenv("CBT_WEBAPP_BASE_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/index.html")

# ============================================================
# BOT TOKENS
# ============================================================

BOT_TOKENS = {
    "all": os.getenv("BOT_TOKEN_ALL", "8808156804:AAEaw2NqVi7wQXiP_TqMsGxnNTwyR2yICrs"),
    "year_1": os.getenv("BOT_TOKEN_Y1", "8729883373:AAESg2VRUY0K1zNYEcz-7IgRuCSEodgSvK4"),
    "year_2": os.getenv("BOT_TOKEN_Y2", "8365220049:AAGRyQ9lsUinESVJYfLa9tR-51sqskQ3ghs"),
    "year_3": os.getenv("BOT_TOKEN_Y3", "8727281228:AAHFt-YI9wBWwIU-UgdoQK4HZVw-wzsyVRk"),
    "final_year": os.getenv("BOT_TOKEN_FINAL", "8796883834:AAEDRuBWPunG-Ip7tuS2ctQEIPrmtViFhxE"),
    "manager": os.getenv("BOT_TOKEN_MANAGER", "8971926878:AAGXv0W1luCS8GiO1rc1r7lM1TBpy45z1-I"),
}

# ============================================================
# SUBJECT DICTIONARIES PER YEAR
# ============================================================

TOPICS_ALL = {
    "Anatomy": 2,
    "Physiology": 3,
    "Biochemistry": 4,
    "Microbiology": 5,
    "Pathology": 49,
    "Pharmacology": 50,
    "Forensic Medicine and Toxicology": 51,
    "Community Medicine": 52,
    "General Medicine": 53,
    "General Surgery": 54,
    "Obstetrics and Gynecology": 55,
    "Pediatrics": 56,
    "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58,
    "Orthopedics": 59,
    "Anesthesiology": 60,
    "Radiology": 61,
    "Dermatology": 62,
    "Psychiatry": 63,
}

TOPICS_Y1 = {
    "Anatomy": 2,
    "Physiology": 3,
    "Biochemistry": 4,
}

TOPICS_Y2 = {
    "Pathology": 49,
    "Pharmacology": 50,
    "Microbiology": 5,
}

TOPICS_Y3 = {
    "Community Medicine": 52,
    "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58,
    "Forensic Medicine and Toxicology": 51,
}

TOPICS_FINAL = {
    "General Medicine": 53,
    "General Surgery": 54,
    "Obstetrics and Gynecology": 55,
    "Pediatrics": 56,
    "Orthopedics": 59,
    "Anesthesiology": 60,
    "Radiology": 61,
    "Dermatology": 62,
    "Psychiatry": 63,
}

BOT_SUBJECTS_MAP = {
    "all": TOPICS_ALL,
    "year_1": TOPICS_Y1,
    "year_2": TOPICS_Y2,
    "year_3": TOPICS_Y3,
    "final_year": TOPICS_FINAL,
}

BOT_TITLES_MAP = {
    "all": "MBBS Full Library (All Subjects)",
    "year_1": "MBBS 1st Year Library",
    "year_2": "MBBS 2nd Year Library",
    "year_3": "MBBS 3rd Year Library",
    "final_year": "MBBS 4th / Final Year Library",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================================
# DATABASE & ACCESS CONTROL
# ============================================================

DB_FILE = "bot_database.json"

DEFAULT_SETTINGS = {
    "expiry_enabled": False,
    "tier_access_enabled": False,
    "daily_limit_enabled": False,
    "daily_limit_max": 30,
    "cloud_backup_enabled": True
}

def load_db():
    data = {
        "users": {},
        "banned": [],
        "approved": [],
        "approved_details": {},
        "settings": DEFAULT_SETTINGS.copy(),
        "daily_downloads": {}
    }
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                loaded = json.load(f)
                data.update(loaded)
        except Exception:
            logging.exception("Failed to read database file")

    if "settings" not in data:
        data["settings"] = DEFAULT_SETTINGS.copy()
    else:
        for k, v in DEFAULT_SETTINGS.items():
            if k not in data["settings"]:
                data["settings"][k] = v

    if "approved" not in data:
        data["approved"] = []
    if "approved_details" not in data:
        data["approved_details"] = {}
    if "users" not in data:
        data["users"] = {}
    if "banned" not in data:
        data["banned"] = []
    if "daily_downloads" not in data:
        data["daily_downloads"] = {}

    for uid in data["approved"]:
        s_uid = str(uid)
        if s_uid not in data["approved_details"]:
            data["approved_details"][s_uid] = {
                "tier": "all",
                "content_tier": "full",
                "expiry": None,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    return data

def save_db(data):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logging.exception("Failed to write database file")

db = load_db()

if ADMIN_ID not in db["approved"]:
    db["approved"].append(ADMIN_ID)
    db["approved_details"][str(ADMIN_ID)] = {
        "tier": "all",
        "content_tier": "full",
        "expiry": None,
        "added_at": "SYSTEM"
    }
    save_db(db)

def get_or_create_qbank_creds(user_id):
    """Generates and retrieves clean student Q-Bank credentials strictly for authorized users"""
    s_uid = str(user_id)
    if s_uid not in db["approved_details"]:
        db["approved_details"][s_uid] = {}

    details = db["approved_details"][s_uid]
    if "qbank_id" not in details or not details.get("qbank_id"):
        suffix = s_uid[-4:] if len(s_uid) >= 4 else str(random.randint(1000, 9999))
        details["qbank_id"] = f"STU-{suffix}"
        details["qbank_pass"] = f"mbbs{random.randint(1000, 9999)}"
        save_db(db)

    return details["qbank_id"], details["qbank_pass"]

def get_user_content_tier(user_id):
    """Returns 'full' (Lectures + QBank), 'lectures_only', or None"""
    uid_int = int(user_id)
    if uid_int == ADMIN_ID:
        return "full"
    if uid_int not in db.get("approved", []):
        return None
    s_uid = str(user_id)
    return db.get("approved_details", {}).get(s_uid, {}).get("content_tier", "lectures_only")

def generate_webapp_launch_url(user_id):
    """Builds a verified 1-tap auto-login URL embedding user details"""
    if int(user_id) == ADMIN_ID:
        return f"{CBT_WEBAPP_BASE_URL}?uid=admin&name=Administrator#uid=admin&name=Administrator"
    
    qid, qpass = get_or_create_qbank_creds(user_id)
    udata = db.get("users", {}).get(str(user_id), {})
    
    first = udata.get("first_name", "").strip()
    last = udata.get("last_name", "").strip()
    full_name = f"{first} {last}".strip() or f"Candidate {qid}"
    uname = udata.get("username", "").strip()
    
    enc_name = quote(full_name)
    enc_uname = quote(uname)
    
    query = f"uid={qid}&key={qpass}&name={enc_name}&uname={enc_uname}"
    return f"{CBT_WEBAPP_BASE_URL}?{query}#{query}"

def track_user(user, bot_type):
    if not user:
        return
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",
            "bot_used": bot_type,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_db(db)
    else:
        # Keep user information updated
        db["users"][uid]["first_name"] = user.first_name or ""
        db["users"][uid]["last_name"] = user.last_name or ""
        db["users"][uid]["username"] = user.username or ""
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
                exp_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                if datetime.now().date() > exp_date:
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
    downloads = db["daily_downloads"].setdefault(today, {})
    user_count = downloads.get(str(uid), 0)
    max_limit = db["settings"].get("daily_limit_max", 30)

    if user_count >= max_limit:
        return False, user_count, max_limit

    return True, user_count, max_limit

def record_download(user_id):
    if int(user_id) == ADMIN_ID:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    downloads = db["daily_downloads"].setdefault(today, {})
    downloads[str(user_id)] = downloads.get(str(user_id), 0) + 1
    save_db(db)

LOCKED_MESSAGE = (
    "🔒 **Access Restricted**\n\n"
    "This is a verified educational bot. Limited users have access to these resources.\n"
    f"To enroll or activate your subscription, contact {OWNER_CONTACT}\n\n"
    "Send your **User ID** to get verified:\n"
    "`{user_id}`"
)

# ============================================================
# CLIENTS & RUNTIME GLOBALS
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

# ============================================================
# CLOUD BACKUP & NOTIFICATION ENGINE
# ============================================================

async def trigger_cloud_backup():
    if not manager_bot_client or not db["settings"].get("cloud_backup_enabled", True):
        return
    try:
        if os.path.exists(DB_FILE):
            await manager_bot_client.send_file(
                ADMIN_ID,
                DB_FILE,
                caption=(
                    "☁️ **Auto-Sync Cloud Backup**\n"
                    f"📅 Date: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"👥 Registered: `{len(db.get('users', {}))}` | 💎 Paid: `{len(db.get('approved', []))}`"
                )
            )
    except Exception:
        logging.exception("Cloud backup failed")

async def auto_restore_from_telegram():
    global db
    if not manager_bot_client:
        return
    try:
        if len(db.get("users", {})) <= 1:
            logging.info("Checking Telegram chat for database backup...")
            async for msg in manager_bot_client.iter_messages(ADMIN_ID, limit=15):
                if msg.file and (msg.file.name == "bot_database.json" or (msg.text and "Auto-Sync Cloud Backup" in msg.text)):
                    await msg.download_media(file=DB_FILE)
                    db = load_db()
                    logging.info("Successfully restored database from backup.")
                    await manager_bot_client.send_message(ADMIN_ID, "🔄 **Cloud Database Auto-Restored Successfully!**")
                    break
    except Exception:
        logging.exception("Auto-restore failed")

async def notify_manager_new_request(user, bot_type):
    if not manager_bot_client:
        return
    try:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Student"
        username = f"@{user.username}" if user.username else "No username"
        text = (
            f"🔔 **New Student Access Request!**\n\n"
            f"👤 **Student:** {name} ({username})\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🤖 **Bot Selected:** `{bot_type}`\n"
            f"🕒 **Time:** `{datetime.now().strftime('%H:%M:%S')}`"
        )
        buttons = [
            [
                Button.inline("⚡ Full (Lec + Q-Bank)", data=f"adm_app_full:{user.id}".encode()),
                Button.inline("📚 Lectures Only", data=f"adm_app_lec:{user.id}".encode())
            ],
            [
                Button.inline("⚙️ Choose Year / Duration", data=f"adm_tier_opt:{user.id}".encode()),
                Button.inline("⛔ Ban", data=f"adm_ban:{user.id}".encode())
            ]
        ]
        await manager_bot_client.send_message(ADMIN_ID, text, buttons=buttons)
    except Exception:
        logging.exception("Failed to dispatch manager alert")

# ============================================================
# WEB SERVER FOR RENDER HEALTH CHECKS
# ============================================================

async def health_check(request):
    return web.Response(text="MBBS Multi-Bot Production Engine is Online 24/7.")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info("Render health-check web server listening on port %s", PORT)

# ============================================================
# UI MENUS
# ============================================================

def make_main_menu(topics):
    subjects = list(topics.keys())
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(subjects[i], data=f"sub:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(subjects[i + 1], data=f"sub:{i + 1}".encode()))
        buttons.append(row)
    return buttons

def make_subject_menu():
    return [
        [
            Button.inline("📚 Video Lectures", data=b"lectures"),
            Button.inline("📝 Notes & PDFs", data=b"notes"),
        ],
        [
            Button.inline("🎯 High-Yield MCQ Hub", data=b"mcq_hub"),
        ],
        [
            Button.inline("⬅️ All Subjects", data=b"home"),
        ]
    ]

def make_mcq_hub_menu(user_id):
    content_tier = get_user_content_tier(user_id)
    has_qbank = content_tier == "full"

    if has_qbank:
        launch_url = generate_webapp_launch_url(user_id)
        cbt_btn = Button.url("🌐 Launch MBBS CBT Q-Bank App", launch_url)
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
    match = re.search(r"(?<!\w)#([A-Za-z0-9_]+)", text)
    return match.group(1) if match else None

def get_filename(message, number=1):
    try:
        if message.document and message.document.attributes:
            for attribute in message.document.attributes:
                if hasattr(attribute, "file_name") and attribute.file_name:
                    return attribute.file_name
    except Exception:
        pass

    text = (message.text or "").strip()
    if text:
        first_line = text.splitlines()[0].strip()
        clean = re.sub(r"#\w+", "", first_line).strip()
        if clean:
            return clean

    return f"Lecture {number}"

# ============================================================
# TOPIC FETCHER & RELAY
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
    if topic_id in TOPIC_CACHE:
        cached_time, cached_data = TOPIC_CACHE[topic_id]
        if now - cached_time < TOPIC_CACHE_TTL:
            return cached_data

    messages = await get_topic_messages(topic_id)
    units = {}
    current_unit = None

    for message in messages:
        text = message.text or ""
        hashtag = extract_hashtag(text)

        if hashtag:
            current_unit = hashtag
            if current_unit not in units:
                units[current_unit] = []

        if current_unit is not None and message.media:
            units[current_unit].append(message)

    TOPIC_CACHE[topic_id] = (now, units)
    return units

async def deliver_lecture(bot_client, bot_entity, chat_id, message, status_msg=None):
    global active_relay_future

    async with relay_lock:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        active_relay_future = future
        relayed_msg = None

        try:
            await user_client.forward_messages(bot_entity, message)
            relayed_msg = await asyncio.wait_for(future, timeout=10.0)

            caption = message.text or ""
            try:
                await bot_client.send_file(
                    entity=chat_id,
                    file=relayed_msg.media,
                    caption=caption,
                    supports_streaming=True
                )
            except Exception:
                await relayed_msg.forward_to(chat_id)

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
            if relayed_msg:
                try:
                    await relayed_msg.delete()
                except Exception:
                    pass

        try:
            if status_msg:
                await status_msg.edit("⚡ **Streaming lecture...**")
            file_path = await user_client.download_media(message, file="downloads/")
            if file_path:
                await bot_client.send_file(
                    entity=chat_id,
                    file=file_path,
                    caption=message.text or "",
                    supports_streaming=True
                )
                if os.path.exists(file_path):
                    os.remove(file_path)
                if status_msg:
                    await status_msg.delete()
                return True
        except Exception:
            logging.exception("Delivery failed.")
            if status_msg:
                await status_msg.edit("❌ Failed to deliver lecture.")
            return False

# ============================================================
# STUDENT BOT GENERATOR
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    bot_entity_box = {}

    @bot_client.on(events.NewMessage)
    async def relay_listener(event):
        global active_relay_future
        if event.is_private and event.sender_id == USER_CLIENT_ID:
            if active_relay_future and not active_relay_future.done():
                active_relay_future.set_result(event.message)

    @bot_client.on(events.NewMessage(pattern=r"^/start$"))
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
                tier_label = BOT_TITLES_MAP.get(user_tier, user_tier.replace('_', ' ').title())
                await event.respond(
                    f"⚠️ **Year Access Restricted**\n\nYour subscription is activated for **{tier_label}**, but this is the **{bot_title}**.\n\n"
                    f"To upgrade or switch years, contact {OWNER_CONTACT}."
                )
                return
            elif reason == "expired":
                await event.respond(
                    f"⚠️ **Subscription Expired!**\n\nYour access period has ended. Contact {OWNER_CONTACT} to renew your enrollment."
                )
                return
            else:
                await event.respond(LOCKED_MESSAGE.format(user_id=uid))
                await notify_manager_new_request(sender, bot_key)
                return

        content_tier = get_user_content_tier(uid)
        cred_banner = ""
        
        # Only issue credentials if user paid for full Q-Bank access
        if content_tier == "full":
            qid, qpass = get_or_create_qbank_creds(uid)
            cred_banner = (
                "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                "🩺 **YOUR CBT Q-BANK CREDENTIALS:**\n"
                f"🆔 **Student ID:** `{qid}`\n"
                f"🔑 **Password:** `{qpass}`\n"
                "*(Auto-logs you into the CBT App)*\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            )
        elif content_tier == "lectures_only":
            cred_banner = (
                "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                "📚 **ENROLLED PLAN:** Video Lectures & Notes Only\n"
                f"💡 *To unlock the interactive CBT Q-Bank app, contact {OWNER_CONTACT}*\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            )

        limit_note = ""
        if db["settings"].get("daily_limit_enabled", False) and uid != ADMIN_ID:
            _, curr, mlimit = check_daily_limit(uid)
            limit_note = f"\n⚡ Daily Limit: `{curr}/{mlimit}` downloads used"

        welcome_text = (
            f"🎓 **{bot_title}**{limit_note}"
            f"{cred_banner}\n\n"
            "Select a subject below to begin:"
        )
        await event.respond(welcome_text, buttons=make_main_menu(bot_topics))

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def cb_home(event):
        if is_banned(event.sender_id):
            return
        allowed, _ = check_access(event.sender_id, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return
        await event.edit(f"🎓 **{bot_title}**\n\nSelect a subject below:", buttons=make_main_menu(bot_topics))

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def cb_sub(event):
        if is_banned(event.sender_id):
            return
        allowed, _ = check_access(event.sender_id, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return

        idx = int(event.pattern_match.group(1))
        subjects = list(bot_topics.keys())
        if 0 <= idx < len(subjects):
            subj = subjects[idx]
            user_subjects[event.sender_id] = subj
            await event.edit(f"📚 **{subj}**\n\nChoose an option below:", buttons=make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"sub_back"))
    async def cb_sub_back(event):
        uid = event.sender_id
        subj = user_subjects.get(uid, "Anatomy")
        await event.edit(f"📚 **{subj}**\n\nChoose an option below:", buttons=make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"lectures"))
    async def cb_lectures(event):
        uid = event.sender_id
        allowed, _ = check_access(uid, bot_key)
        if is_banned(uid) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return

        subj = user_subjects.get(uid)
        if not subj or subj not in bot_topics:
            await event.answer("Select subject again.")
            return

        topic_id = bot_topics[subj]
        await event.answer("Loading lectures...")
        units = await get_topic_units(topic_id)

        if not units:
            await event.edit(f"📚 **{subj}**\n\nNo lecture units found.", buttons=[[Button.inline("⬅️ Back", data=b"home")]])
            return

        unit_names = list(units.keys())
        user_units[uid] = {"subject": subj, "units": units, "unit_names": unit_names}

        buttons = []
        for i, u in enumerate(unit_names):
            buttons.append([Button.inline(f"📂 #{u} ({len(units[u])})", data=f"unit:{i}".encode())])
        buttons.append([Button.inline("⬅️ Back to Subject", data=b"sub_back")])

        await event.edit(f"📚 **{subj} Lectures**\n\nSelect a unit:", buttons=buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
    async def cb_unit(event):
        uid = event.sender_id
        data = user_units.get(uid)
        if not data:
            await event.answer("Reopen subject.")
            return

        idx = int(event.pattern_match.group(1))
        if 0 <= idx < len(data["unit_names"]):
            unit_name = data["unit_names"][idx]
            lectures = data["units"].get(unit_name, [])
            buttons = []
            for i, lec in enumerate(lectures):
                fname = get_filename(lec, i + 1)
                if len(fname) > 42:
                    fname = fname[:39] + "..."
                buttons.append([Button.inline(f"📄 {fname}", data=f"file:{lec.id}".encode())])
            buttons.append([Button.inline("⬅️ Units", data=b"lectures")])

            await event.edit(f"📂 **#{unit_name}** ({len(lectures)} lectures):\n\nSelect a lecture:", buttons=buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^file:(\d+)$"))
    async def cb_file(event):
        uid = event.sender_id
        allowed, _ = check_access(uid, bot_key)
        if is_banned(uid) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return

        can_dl, _, max_dl = check_daily_limit(uid)
        if not can_dl:
            await event.answer("⚠️ Daily download limit reached!", alert=True)
            return

        mid = int(event.pattern_match.group(1))
        await event.answer("⚡ Sending lecture...")
        status = await bot_client.send_message(event.chat_id, "⚡ **Sending lecture directly...**")

        try:
            msg = await user_client.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                success = await deliver_lecture(bot_client, bot_entity_box.get("entity"), event.chat_id, msg, status)
                if success:
                    record_download(uid)
            else:
                await status.edit("❌ Lecture file not found.")
        except Exception:
            logging.exception("File deliver error")
            await status.edit("❌ Delivery failed.")

    @bot_client.on(events.CallbackQuery(data=b"notes"))
    async def cb_notes(event):
        uid = event.sender_id
        subj = user_subjects.get(uid)
        if not subj:
            await event.answer("Select subject again.")
            return

        status = await bot_client.send_message(event.chat_id, f"🔍 Searching notes for **{subj}**...")
        try:
            notes = await get_topic_messages(bot_topics.get("Notes", 33))
            clean_subj = re.sub(r"[^a-zA-Z0-9]", "", subj).lower()
            found = [m for m in notes if m.media and (clean_subj in (m.text or "").lower() or clean_subj in get_filename(m).lower())]

            if not found:
                await status.edit(f"❌ No notes found for **{subj}**.")
                return

            await status.edit("⚡ Delivering note(s)...")
            for m in found:
                await deliver_lecture(bot_client, bot_entity_box.get("entity"), event.chat_id, m, status)
        except Exception:
            logging.exception("Notes deliver error")
            await status.edit("❌ Could not deliver notes.")

    @bot_client.on(events.CallbackQuery(data=b"mcq_hub"))
    async def cb_mcq_hub(event):
        uid = event.sender_id
        subj = user_subjects.get(uid, "Anatomy")
        await event.edit(
            f"🎯 **{subj} MCQ & Question Bank Hub**\n\n"
            "Select your practice material:\n\n"
            "• 🌐 **Interactive CBT App**: Full browser CBT exam simulator with timers & rationales.\n"
            "• 📂 **Topic-Wise Q-Bank**: Unit-wise question papers & PDFs.\n"
            "• 🏛️ **Previous Year Questions (PYQs)**: Past recalls.\n"
            "• 🎲 **Random / Mock Test MCQs**: Mixed subject questions.",
            buttons=make_mcq_hub_menu(uid)
        )

    @bot_client.on(events.CallbackQuery(data=b"mcq_upgrade_info"))
    async def cb_upgrade_info(event):
        await event.answer("🔒 Q-Bank Access Required", alert=True)
        await event.respond(
            f"🔒 **Interactive Q-Bank Not Included in Your Current Plan**\n\n"
            "Your account currently has access to **Lectures & Notes Only**.\n\n"
            f"To unlock the interactive CBT test simulator with scorecards and option shuffling, contact {OWNER_CONTACT} to upgrade your plan."
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^mcq_p:(.+)$"))
    async def cb_mcq_paper(event):
        cat = event.pattern_match.group(1).decode()
        subj = user_subjects.get(event.sender_id, "Anatomy")
        titles = {
            "topic_wise": "📂 Topic-Wise Q-Bank PDFs",
            "pyqs": "🏛️ Previous Year Questions (PYQs)",
            "random": "🎲 Random / Mock Test MCQs"
        }
        await event.edit(
            f"📑 **{subj} — {titles.get(cat, 'MCQs')}**\n\nSearching question banks in storage...",
            buttons=[[Button.inline("⬅️ Back to MCQ Hub", data=b"mcq_hub")]]
        )

    return bot_entity_box

# ============================================================
# BOT MANAGER ENGINE (ADMIN CONTROL CENTER)
# ============================================================

def make_manager_menu():
    return [
        [
            Button.inline("📊 System Stats", data=b"mgmt_stats"),
            Button.inline("⚙️ Feature Toggles", data=b"mgmt_toggles"),
        ],
        [
            Button.inline("⏳ Pending Requests", data=b"mgmt_pending"),
            Button.inline("💎 Verified Members", data=b"mgmt_approved_p:0"),
        ],
        [
            Button.inline("📢 Broadcast Announcement", data=b"mgmt_announce"),
            Button.inline("👥 Registered Users", data=b"mgmt_users_p:0"),
        ],
        [
            Button.inline("🟢 Alert: Server Online", data=b"mgmt_alert_online"),
            Button.inline("🔴 Alert: Server Down", data=b"mgmt_alert_down"),
        ],
        [
            Button.inline("☁️ Cloud Backup Now", data=b"mgmt_do_backup"),
            Button.inline("🔄 Refresh Dashboard", data=b"mgmt_home"),
        ]
    ]

def make_toggles_menu():
    settings = db["settings"]
    btn_exp = "🟢 ON" if settings.get("expiry_enabled") else "🔴 OFF"
    btn_tier = "🟢 ON" if settings.get("tier_access_enabled") else "🔴 OFF"
    btn_limit = f"🟢 ON ({settings.get('daily_limit_max', 30)}/d)" if settings.get("daily_limit_enabled") else "🔴 OFF"
    btn_sync = "🟢 ON" if settings.get("cloud_backup_enabled") else "🔴 OFF"

    return [
        [Button.inline(f"⏳ Subscription Expiry: {btn_exp}", data=b"tog:expiry_enabled")],
        [Button.inline(f"🎓 Year-Lock Tier: {btn_tier}", data=b"tog:tier_access_enabled")],
        [Button.inline(f"🛡️ Anti-Leech Limit: {btn_limit}", data=b"tog:daily_limit_enabled")],
        [Button.inline(f"☁️ Cloud Auto-Sync: {btn_sync}", data=b"tog:cloud_backup_enabled")],
        [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
    ]

def setup_manager_bot_handlers(client):

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def manager_start(event):
        if event.sender_id != ADMIN_ID:
            await event.respond("⛔ Access Denied.")
            return

        total_users = len(db.get("users", {}))
        approved_users = len(db.get("approved", []))
        qbank_count = sum(1 for d in db.get("approved_details", {}).values() if d.get("content_tier") == "full")
        lec_count = approved_users - qbank_count

        text = (
            "🎛️ **MBBS Management Control Center**\n\n"
            f"🤖 **Managed Bots Online:** `{len(active_bots)}` bots\n"
            f"👥 **Total Registered Students:** `{total_users}`\n"
            f"💎 **Verified Paid Members:** `{approved_users}`\n"
            f"  └ 🩺 Full Q-Bank Access: `{qbank_count}`\n"
            f"  └ 📚 Lectures Only: `{lec_count}`\n"
            f"🚫 **Blocked Users:** `{len(db.get('banned', []))}`\n\n"
            "Select an administrative action below:"
        )
        await event.respond(text, buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_home"))
    async def cb_manager_home(event):
        if event.sender_id != ADMIN_ID:
            return
        total_users = len(db.get("users", {}))
        approved_users = len(db.get("approved", []))
        qbank_count = sum(1 for d in db.get("approved_details", {}).values() if d.get("content_tier") == "full")
        lec_count = approved_users - qbank_count

        text = (
            "🎛️ **MBBS Management Control Center**\n\n"
            f"🤖 **Managed Bots Online:** `{len(active_bots)}` bots\n"
            f"👥 **Total Registered Students:** `{total_users}`\n"
            f"💎 **Verified Paid Members:** `{approved_users}`\n"
            f"  └ 🩺 Full Q-Bank Access: `{qbank_count}`\n"
            f"  └ 📚 Lectures Only: `{lec_count}`\n"
            f"🚫 **Blocked Users:** `{len(db.get('banned', []))}`\n\n"
            "Select an administrative action below:"
        )
        await event.edit(text, buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_toggles"))
    async def cb_manager_toggles(event):
        if event.sender_id != ADMIN_ID:
            return
        await event.edit("⚙️ **System Feature Controls (ON / OFF)**", buttons=make_toggles_menu())

    @client.on(events.CallbackQuery(pattern=rb"^tog:(.+)$"))
    async def cb_toggle_switch(event):
        if event.sender_id != ADMIN_ID:
            return
        key = event.pattern_match.group(1).decode()
        if key in db["settings"]:
            db["settings"][key] = not db["settings"][key]
            save_db(db)
            state_str = "ON" if db["settings"][key] else "OFF"
            await event.answer(f"{key} is now {state_str}!", alert=True)
            await cb_manager_toggles(event)

    @client.on(events.CallbackQuery(data=b"mgmt_do_backup"))
    async def cb_do_backup(event):
        if event.sender_id != ADMIN_ID:
            return
        await event.answer("Dispatching cloud backup to chat...")
        await trigger_cloud_backup()
        await event.edit("✅ **Cloud backup dispatched!** `bot_database.json` has been sent directly to this chat.", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(data=b"mgmt_stats"))
    async def cb_stats(event):
        if event.sender_id != ADMIN_ID:
            return
        total = len(db.get("users", {}))
        approved = len(db.get("approved", []))
        qbank_count = sum(1 for d in db.get("approved_details", {}).values() if d.get("content_tier") == "full")
        lec_count = approved - qbank_count
        uptime = int(time.time() - START_TIME)
        up_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

        text = (
            "📊 **Live System Analytics**\n\n"
            f"👥 **Total Registered Students:** `{total}`\n"
            f"💎 **Verified Paid:** `{approved}`\n"
            f"  └ 🩺 Full (Lectures + QBank): `{qbank_count}`\n"
            f"  └ 📚 Lectures & Notes Only: `{lec_count}`\n"
            f"🚫 **Blocked:** `{len(db.get('banned', []))}`\n"
            f"⏱️ **Server Uptime:** `{up_str}`\n\n"
            f"🤖 **Connected Active Bots:** `{len(active_bots)}` online"
        )
        await event.edit(text, buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])

    # ============================================================
    # REGISTERED USERS BROWSER (PAGINATED)
    # ============================================================

    @client.on(events.CallbackQuery(pattern=rb"^mgmt_users_p:(\d+)$"))
    async def cb_users_page(event):
        if event.sender_id != ADMIN_ID:
            return
        page = int(event.pattern_match.group(1))
        users = db.get("users", {})
        u_list = list(users.items())
        total_users = len(u_list)

        if total_users == 0:
            await event.edit("ℹ️ **No registered students yet.**", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])
            return

        per_page = 6
        total_pages = max(1, (total_users + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * per_page
        slice_users = u_list[start_idx:start_idx + per_page]

        msg = f"👥 **Registered Students ({total_users}) — Page {page + 1}/{total_pages}:**\n\n"
        buttons = []

        for uid_str, udata in slice_users:
            name = f"{udata.get('first_name', '')} {udata.get('last_name', '')}".strip() or "Student"
            uname = f"@{udata.get('username')}" if udata.get("username") else "No username"
            uid_int = int(uid_str)
            is_app = uid_int in db.get("approved", [])
            tier = db.get("approved_details", {}).get(uid_str, {}).get("content_tier", "none") if is_app else "Unverified"
            
            badge = "🩺 Q-Bank" if tier == "full" else ("📚 Lec" if tier == "lectures_only" else "⏳ Free")
            msg += f"• **{name}** ({uname})\n  └ ID: `{uid_str}` | Plan: **{badge}** | Bot: `{udata.get('bot_used', 'all')}`\n\n"

            row = []
            if not is_app:
                row.append(Button.inline(f"⚡ Full {name[:10]}", data=f"adm_app_full:{uid_str}".encode()))
                row.append(Button.inline(f"📚 Lec", data=f"adm_app_lec:{uid_str}".encode()))
            else:
                row.append(Button.inline(f"⚙️ Manage {name[:12]}", data=f"adm_tier_opt:{uid_str}".encode()))
            buttons.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(Button.inline("◀ Prev", data=f"mgmt_users_p:{page - 1}".encode()))
        if page < total_pages - 1:
            nav_row.append(Button.inline("Next ▶", data=f"mgmt_users_p:{page + 1}".encode()))

        if nav_row:
            buttons.append(nav_row)
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])

        await event.edit(msg, buttons=buttons)

    # ============================================================
    # VERIFIED PAID MEMBERS BROWSER (PAGINATED)
    # ============================================================

    @client.on(events.CallbackQuery(pattern=rb"^mgmt_approved_p:(\d+)$"))
    async def cb_approved_page(event):
        if event.sender_id != ADMIN_ID:
            return
        page = int(event.pattern_match.group(1))
        approved_list = [uid for uid in db.get("approved", []) if uid != ADMIN_ID]
        total_app = len(approved_list)

        if total_app == 0:
            await event.edit("ℹ️ **No verified paid students found yet.**", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])
            return

        per_page = 6
        total_pages = max(1, (total_app + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * per_page
        slice_app = approved_list[start_idx:start_idx + per_page]

        msg = f"💎 **Verified Paid Members ({total_app}) — Page {page + 1}/{total_pages}:**\n\n"
        buttons = []

        for uid in slice_app:
            s_uid = str(uid)
            udata = db.get("users", {}).get(s_uid, {})
            name = f"{udata.get('first_name', '')} {udata.get('last_name', '')}".strip() or f"User {uid}"
            uname = f"@{udata.get('username')}" if udata.get("username") else "No username"
            det = db.get("approved_details", {}).get(s_uid, {})
            c_tier = det.get("content_tier", "lectures_only")
            tier_badge = "🩺 Q-Bank (Full)" if c_tier == "full" else "📚 Lectures Only"
            qid = det.get("qbank_id", "Not Issued")

            msg += f"• **{name}** ({uname})\n  └ ID: `{uid}` | Plan: **{tier_badge}** | Q-ID: `{qid}`\n\n"

            buttons.append([
                Button.inline(f"✏️ Edit {name[:12]}", data=f"adm_tier_opt:{uid}".encode()),
                Button.inline("❌ Revoke", data=f"adm_rev:{uid}".encode())
            ])

        nav_row = []
        if page > 0:
            nav_row.append(Button.inline("◀ Prev", data=f"mgmt_approved_p:{page - 1}".encode()))
        if page < total_pages - 1:
            nav_row.append(Button.inline("Next ▶", data=f"mgmt_approved_p:{page + 1}".encode()))

        if nav_row:
            buttons.append(nav_row)
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])

        await event.edit(msg, buttons=buttons)

    # Legacy callback forwarder
    @client.on(events.CallbackQuery(data=b"mgmt_approved"))
    async def cb_approved_redirect(event):
        await cb_approved_page(event)

    @client.on(events.CallbackQuery(data=b"mgmt_users"))
    async def cb_users_redirect(event):
        await cb_users_page(event)

    @client.on(events.CallbackQuery(data=b"mgmt_pending"))
    async def cb_pending(event):
        if event.sender_id != ADMIN_ID:
            return
        users = db.get("users", {})
        pending = [
            (uid, udata) for uid, udata in users.items()
            if not is_banned(uid) and int(uid) not in db.get("approved", [])
        ]
        if not pending:
            await event.edit("✅ **No pending access requests!**", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])
            return

        buttons = []
        for uid, udata in pending[-6:]:
            name = f"{udata.get('first_name', '')} {udata.get('last_name', '')}".strip() or "Student"
            buttons.append([
                Button.inline(f"⚡ Full {name[:12]}", data=f"adm_app_full:{uid}".encode()),
                Button.inline(f"📚 Lec", data=f"adm_app_lec:{uid}".encode())
            ])
        buttons.append([Button.inline("⬅️ Back", data=b"mgmt_home")])
        await event.edit(f"⏳ **Pending Verification Requests ({len(pending)}):**", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_app_full:(\d+)$"))
    async def cb_app_full(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        t_str = str(target_id)

        if target_id not in db["approved"]:
            db["approved"].append(target_id)

        if t_str not in db["approved_details"]:
            db["approved_details"][t_str] = {}

        db["approved_details"][t_str]["content_tier"] = "full"
        db["approved_details"][t_str]["tier"] = "all"
        db["approved_details"][t_str]["expiry"] = None
        db["approved_details"][t_str]["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        qid, qpass = get_or_create_qbank_creds(target_id)
        save_db(db)
        await trigger_cloud_backup()

        await event.answer("✅ Full Access Granted!", alert=True)
        await event.edit(
            f"✅ User `{target_id}` granted **Full Access (Lectures + Q-Bank)**!\n\n"
            f"🆔 Generated Student ID: `{qid}`\n"
            f"🔑 Generated Password: `{qpass}`",
            buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]]
        )

        launch_url = generate_webapp_launch_url(target_id)
        for bot in active_bots.values():
            try:
                msg = (
                    "🎉 **Payment Verified — Full Access Granted!**\n\n"
                    "You have been enrolled in **MBBS Video Lectures + CBT Q-Bank**:\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 **Your Student ID:** `{qid}`\n"
                    f"🔑 **Your Password:** `{qpass}`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Send /start to browse lectures, or tap below to launch your interactive CBT test simulator:"
                )
                await bot.send_message(target_id, msg, buttons=[[Button.url("🌐 Launch Interactive Q-Bank", launch_url)]])
                break
            except Exception:
                pass

    @client.on(events.CallbackQuery(pattern=rb"^adm_app_lec:(\d+)$"))
    async def cb_app_lec(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        t_str = str(target_id)

        if target_id not in db["approved"]:
            db["approved"].append(target_id)

        if t_str not in db["approved_details"]:
            db["approved_details"][t_str] = {}

        db["approved_details"][t_str]["content_tier"] = "lectures_only"
        db["approved_details"][t_str]["tier"] = "all"
        db["approved_details"][t_str]["expiry"] = None
        db["approved_details"][t_str]["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_db(db)
        await trigger_cloud_backup()

        await event.answer("✅ Lectures Only Granted!", alert=True)
        await event.edit(
            f"✅ User `{target_id}` enrolled in **Lectures & Notes Only**.\n(No Q-Bank credentials issued).",
            buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]]
        )

        for bot in active_bots.values():
            try:
                await bot.send_message(
                    target_id,
                    "🎉 **Access Granted!**\n\nYour account has been enrolled in **MBBS Video Lectures & Notes**.\n"
                    "Send /start to begin studying!"
                )
                break
            except Exception:
                pass

    @client.on(events.CallbackQuery(data=b"mgmt_alert_online"))
    async def cb_server_online(event):
        if event.sender_id != ADMIN_ID:
            return
        await event.answer("Broadcasting server online notice...")
        notice = (
            "🟢 **MBBS Platform Status: All Systems Operational**\n\n"
            "The lecture streaming servers and CBT Q-Bank app are fully online and responsive. Happy studying!"
        )
        sent = 0
        sender_bot = list(active_bots.values())[0] if active_bots else client
        for uid in db.get("approved", []):
            if uid == ADMIN_ID:
                continue
            try:
                await sender_bot.send_message(uid, notice)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await event.edit(f"✅ **Server Online notice delivered to `{sent}` paid students!**", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(data=b"mgmt_alert_down"))
    async def cb_server_down(event):
        if event.sender_id != ADMIN_ID:
            return
        await event.answer("Broadcasting maintenance notice...")
        notice = (
            "🛠️ **Scheduled Maintenance Notice**\n\n"
            "We are performing quick cloud updates to improve lecture delivery speeds. "
            "Services will be back up momentarily. Thank you for your patience!"
        )
        sent = 0
        sender_bot = list(active_bots.values())[0] if active_bots else client
        for uid in db.get("approved", []):
            if uid == ADMIN_ID:
                continue
            try:
                await sender_bot.send_message(uid, notice)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await event.edit(f"✅ **Maintenance notice delivered to `{sent}` paid students!**", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(pattern=rb"^adm_tier_opt:(\d+)$"))
    async def cb_tier_options(event):
        if event.sender_id != ADMIN_ID:
            return
        uid = int(event.pattern_match.group(1))
        det = db.get("approved_details", {}).get(str(uid), {})
        curr_ctier = det.get("content_tier", "lectures_only")

        buttons = [
            [
                Button.inline("🩺 Switch to Full Access (Lec + Q-Bank)", data=f"adm_set_tier:{uid}:full".encode()),
            ],
            [
                Button.inline("📚 Switch to Lectures & Notes Only", data=f"adm_set_tier:{uid}:lectures_only".encode()),
            ],
            [
                Button.inline("⬅️ Back", data=b"mgmt_approved_p:0")
            ]
        ]
        await event.edit(
            f"⚙️ **Modify Subscription for User `{uid}`:**\n\n"
            f"• Current Plan: **{curr_ctier.upper()}**\n\n"
            "Select an updated tier below:",
            buttons=buttons
        )

    @client.on(events.CallbackQuery(pattern=rb"^adm_set_tier:(\d+):([a-z0-9_]+)$"))
    async def cb_apply_tier(event):
        if event.sender_id != ADMIN_ID:
            return
        uid = int(event.pattern_match.group(1))
        new_tier = event.pattern_match.group(2).decode()
        t_str = str(uid)

        if t_str not in db["approved_details"]:
            db["approved_details"][t_str] = {}

        db["approved_details"][t_str]["content_tier"] = new_tier
        if new_tier == "full":
            get_or_create_qbank_creds(uid)

        save_db(db)
        await trigger_cloud_backup()

        await event.answer("✅ Updated Plan Successfully!", alert=True)
        await event.edit(
            f"✅ User `{uid}` successfully updated to **{new_tier.upper()}**!",
            buttons=[[Button.inline("💎 Back to Verified Members", data=b"mgmt_approved_p:0")]]
        )

    @client.on(events.CallbackQuery(pattern=rb"^adm_rev:(\d+)$"))
    async def cb_rev(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("approved", []):
            db["approved"].remove(target_id)
            save_db(db)
            await trigger_cloud_backup()
            await event.answer("🔒 Access Revoked!", alert=True)
            await event.edit(f"🔒 Access revoked for `{target_id}`.", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(pattern=rb"^adm_ban:(\d+)$"))
    async def cb_ban(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id not in db["banned"]:
            db["banned"].append(target_id)
            if target_id in db["approved"]:
                db["approved"].remove(target_id)
            save_db(db)
            await trigger_cloud_backup()
            await event.answer("⛔ User Banned!", alert=True)
            await event.edit(f"⛔ User `{target_id}` banned.", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    # Text Commands for Admin
    @client.on(events.NewMessage(pattern=r"^/users$"))
    async def cmd_users_list(event):
        if event.sender_id != ADMIN_ID:
            return
        users = db.get("users", {})
        if not users:
            await event.respond("ℹ️ No registered users found.")
            return

        msg = f"👥 **Registered Students ({len(users)}):**\n\n"
        for uid_str, data in list(users.items())[-25:]:
            name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or "Student"
            uname = f"@{data.get('username')}" if data.get("username") else "No username"
            uid_int = int(uid_str)
            is_app = uid_int in db.get("approved", [])
            tier = db.get("approved_details", {}).get(uid_str, {}).get("content_tier", "none") if is_app else "Unverified"
            msg += f"• `{uid_str}`: **{name}** ({uname})\n  └ Plan: `{tier}` | Joined: `{data.get('joined_at', '-')}`\n"

        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/approved$"))
    async def cmd_approved_list(event):
        if event.sender_id != ADMIN_ID:
            return
        approved = [uid for uid in db.get("approved", []) if uid != ADMIN_ID]
        if not approved:
            await event.respond("ℹ️ No verified paid members yet.")
            return

        msg = f"💎 **Verified Paid Members ({len(approved)}):**\n\n"
        for uid in approved:
            s_uid = str(uid)
            udata = db.get("users", {}).get(s_uid, {})
            name = f"{udata.get('first_name', '')} {udata.get('last_name', '')}".strip() or f"User {uid}"
            uname = f"@{udata.get('username')}" if udata.get("username") else ""
            det = db.get("approved_details", {}).get(s_uid, {})
            c_tier = det.get("content_tier", "lectures_only")
            qid = det.get("qbank_id", "None")
            qpass = det.get("qbank_pass", "None")
            msg += f"👤 **{name}** {uname} (`{uid}`)\n  └ Plan: **{c_tier.upper()}** | ID: `{qid}` | Pass: `{qpass}`\n\n"

        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/grant_qbank (\d+)$"))
    async def cmd_grant_qbank(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        t_str = str(target_id)
        if target_id not in db["approved"]:
            db["approved"].append(target_id)
        if t_str not in db["approved_details"]:
            db["approved_details"][t_str] = {}

        db["approved_details"][t_str]["content_tier"] = "full"
        qid, qpass = get_or_create_qbank_creds(target_id)
        save_db(db)
        await trigger_cloud_backup()

        await event.respond(f"✅ User `{target_id}` granted **Full Access (Lectures + Q-Bank)**!\n🆔 ID: `{qid}` | 🔑 Pass: `{qpass}`")

    @client.on(events.NewMessage(pattern=r"^/grant_lectures (\d+)$"))
    async def cmd_grant_lectures(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        t_str = str(target_id)
        if target_id not in db["approved"]:
            db["approved"].append(target_id)
        if t_str not in db["approved_details"]:
            db["approved_details"][t_str] = {}

        db["approved_details"][t_str]["content_tier"] = "lectures_only"
        save_db(db)
        await trigger_cloud_backup()

        await event.respond(f"✅ User `{target_id}` granted **Lectures & Notes Only**.")

    @client.on(events.NewMessage(pattern=r"^/broadcast (.+)"))
    async def cmd_broadcast(event):
        if event.sender_id != ADMIN_ID:
            return
        text = event.pattern_match.group(1).strip()
        users = db.get("users", {})
        status = await event.respond(f"📢 Broadcasting to `{len(users)}` users...")
        sent, failed = 0, 0
        sender_bot = list(active_bots.values())[0] if active_bots else client

        for uid_str in list(users.keys()):
            if is_banned(uid_str):
                continue
            try:
                await sender_bot.send_message(int(uid_str), f"📢 **MBBS Announcement:**\n\n{text}")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        await status.edit(f"✅ **Broadcast complete!**\n📬 Delivered: `{sent}` | ❌ Failed: `{failed}`")

# ============================================================
# SYSTEM STARTUP & ORCHESTRATION
# ============================================================

async def main():
    global USER_CLIENT_ID, manager_bot_client
    os.makedirs("downloads", exist_ok=True)
    await start_web_server()

    logging.info("Starting Telegram user client ('session')...")
    await user_client.start()
    user_me = await user_client.get_me()
    USER_CLIENT_ID = user_me.id
    logging.info("User client connected as: %s (ID: %s)", user_me.first_name, user_me.id)

    runners = [user_client.run_until_disconnected()]

    for key, token in BOT_TOKENS.items():
        if not token or not token.strip():
            continue
        try:
            client = TelegramClient(f"bot_session_{key}", API_ID, API_HASH)
            await client.start(bot_token=token.strip())
            bot_me = await client.get_me()

            if key == "manager":
                manager_bot_client = client
                setup_manager_bot_handlers(client)
                runners.append(client.run_until_disconnected())
                logging.info("Started [Bots Management Bot] -> @%s", bot_me.username)
                continue

            bot_entity = await user_client.get_entity(bot_me.username)
            box = setup_bot_handlers(
                bot_client=client,
                bot_key=key,
                bot_topics=BOT_SUBJECTS_MAP[key],
                bot_title=BOT_TITLES_MAP[key]
            )
            box["entity"] = bot_entity
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
                "🟢 **MBBS Multi-Bot Production System Online!**\n\n"
                f"• Active Year Bots: `{len(active_bots)}` online\n"
                f"• User Client Connected: `{user_me.first_name}`\n"
                f"• Registered Students: `{len(db.get('users', {}))}`\n\n"
                "All lecture delivery relays, automated Q-Bank gating, and keep-alive listeners are active."
            )
        except Exception:
            pass

    logging.info("All MBBS bots and Management Control Bot are live.")
    await asyncio.gather(*runners)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("System shutting down.")
    except Exception:
        logging.exception("Fatal crash")
