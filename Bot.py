
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from aiohttp import web

from telethon import TelegramClient, events, Button
from telethon.errors import RPCError, FloodWaitError, ChatForwardsRestrictedError

# ============================================================
# CONFIGURATION
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

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
# DATABASE, MIGRATION & SETTINGS
# ============================================================

DB_FILE = "bot_database.json"

DEFAULT_SETTINGS = {
    "expiry_enabled": False,       # Toggle 1: Subscriptions with expiry date
    "tier_access_enabled": False,  # Toggle 2: Year-specific bot locking
    "daily_limit_enabled": False,  # Toggle 3: Anti-Leech download limiter
    "daily_limit_max": 30,         # Maximum downloads per day per user
    "cloud_backup_enabled": True   # Toggle 4: Telegram cloud auto-sync
}

def load_db():
    data = {"users": {}, "banned": [], "approved": [], "approved_details": {}, "settings": DEFAULT_SETTINGS.copy(), "daily_downloads": {}}
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

    # Backward compatibility: automatically migrate existing approved users to Lifetime All-Year
    for uid in data["approved"]:
        s_uid = str(uid)
        if s_uid not in data["approved_details"]:
            data["approved_details"][s_uid] = {
                "tier": "all",
                "expiry": None,  # None means Lifetime
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

# Auto-add admin to approved list
if ADMIN_ID not in db["approved"]:
    db["approved"].append(ADMIN_ID)
    db["approved_details"][str(ADMIN_ID)] = {"tier": "all", "expiry": None, "added_at": "SYSTEM"}
    save_db(db)

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

def is_banned(user_id):
    return int(user_id) in db.get("banned", [])

def check_access(user_id, bot_type):
    """
    Evaluates student access based on active toggles:
    - Expiry check (if enabled)
    - Year tier check (if enabled)
    Returns: (is_allowed: bool, reason: str)
    """
    uid = int(user_id)
    if uid == ADMIN_ID:
        return True, "admin"

    if uid not in db.get("approved", []):
        return False, "not_approved"

    details = db.get("approved_details", {}).get(str(uid), {})

    # 1. Check Expiry if toggle is ON
    if db["settings"].get("expiry_enabled", False):
        expiry_str = details.get("expiry")
        if expiry_str:
            try:
                exp_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                if datetime.now().date() > exp_date:
                    # Auto-revoke expired user
                    db["approved"].remove(uid)
                    save_db(db)
                    return False, "expired"
            except Exception:
                pass

    # 2. Check Year Tier if toggle is ON
    if db["settings"].get("tier_access_enabled", False):
        user_tier = details.get("tier", "all")
        if user_tier != "all" and user_tier != bot_type:
            return False, f"tier_mismatch:{user_tier}"

    return True, "allowed"

def check_daily_limit(user_id):
    """
    Checks if Anti-Leech limit is enabled and validates downloads for today.
    Returns: (allowed: bool, current: int, max_limit: int)
    """
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
    """Increments the student's daily download count"""
    if int(user_id) == ADMIN_ID:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    downloads = db["daily_downloads"].setdefault(today, {})
    downloads[str(user_id)] = downloads.get(str(user_id), 0) + 1
    save_db(db)

LOCKED_MESSAGE = (
    "🔒 **Access Restricted**\n\n"
    "Heyy this is paid bot only limited users can have accese only this bot if you want the access then contact @Nothing_0786\n\n"
    "Send your **User ID** to get verified:\n"
    "`{user_id}`"
)

# ============================================================
# CLIENTS & GLOBALS
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
    """Sends a copy of bot_database.json to the admin chat to protect against Render disk resets"""
    if not manager_bot_client or not db["settings"].get("cloud_backup_enabled", True):
        return
    try:
        if os.path.exists(DB_FILE):
            await manager_bot_client.send_file(
                ADMIN_ID,
                DB_FILE,
                caption=f"☁️ **Auto-Sync Cloud Backup**\n📅 Date: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n👥 Users: `{len(db.get('users', {}))}` | 💎 Paid: `{len(db.get('approved', []))}`"
            )
    except Exception:
        logging.exception("Cloud backup dispatch failed")

async def auto_restore_from_telegram():
    """If bot_database.json is missing or wiped on Render, auto-restores the newest backup from Telegram"""
    global db
    if not manager_bot_client:
        return
    try:
        # Check if local DB is empty
        if len(db.get("users", {})) <= 1:
            logging.info("Checking Telegram chat for cloud database backups...")
            async for msg in manager_bot_client.iter_messages(ADMIN_ID, limit=15):
                if msg.file and (msg.file.name == "bot_database.json" or (msg.text and "Auto-Sync Cloud Backup" in msg.text)):
                    await msg.download_media(file=DB_FILE)
                    db = load_db()
                    logging.info("Successfully restored database from Telegram cloud backup!")
                    await manager_bot_client.send_message(ADMIN_ID, "🔄 **Database Restored!** Loaded your backup from Telegram.")
                    break
    except Exception:
        logging.exception("Failed to auto-restore database")

async def notify_manager_new_request(user, bot_type):
    """Sends an instant notification with 1-click Quick Approval to the Management Bot"""
    if not manager_bot_client:
        return
    try:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
        username = f"@{user.username}" if user.username else "No username"
        text = (
            f"🔔 **New Access Request!**\n\n"
            f"👤 **Student:** {name} ({username})\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🤖 **Bot Requested:** `{bot_type}`\n"
            f"🕒 **Time:** `{datetime.now().strftime('%H:%M:%S')}`"
        )
        buttons = [
            [
                Button.inline("⚡ Quick Approve (Full)", data=f"adm_app:{user.id}".encode()),
                Button.inline("⚙️ Choose Tier / Expiry", data=f"adm_tier_opt:{user.id}".encode())
            ],
            [
                Button.inline("⛔ Ban", data=f"adm_ban:{user.id}".encode())
            ]
        ]
        await manager_bot_client.send_message(ADMIN_ID, text, buttons=buttons)
    except Exception:
        logging.exception("Failed to dispatch manager alert")

# ============================================================
# HEALTH-CHECK WEB SERVER FOR RENDER
# ============================================================

async def health_check(request):
    return web.Response(text="MBBS Multi-Bot Engine is live and healthy!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info("Web server listening on port %s", PORT)

# ============================================================
# MENUS & HELPERS
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
            Button.inline("📚 Lectures", data=b"lectures"),
            Button.inline("📝 Notes", data=b"notes"),
        ],
        [
            Button.inline("⬅️ Back", data=b"home"),
        ]
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
# TOPIC MESSAGES FETCHING
# ============================================================

async def get_topic_messages(topic_id):
    messages = []
    try:
        async for message in user_client.iter_messages(GROUP_ID, reply_to=topic_id):
            messages.append(message)
        messages.reverse()
    except FloodWaitError as e:
        logging.warning("Flood wait: %s seconds", e.seconds)
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

# ============================================================
# INSTANT CLOUD DELIVERY ENGINE
# ============================================================

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
            except Exception as e:
                logging.info("send_file fallback to forward: %s", e)
                await relayed_msg.forward_to(chat_id)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            return True

        except ChatForwardsRestrictedError:
            logging.warning("Source group has protected content. Falling back to stream.")
        except asyncio.TimeoutError:
            logging.warning("Relay timeout. Falling back to stream.")
        except Exception:
            logging.exception("Relay error. Falling back to stream.")
        finally:
            active_relay_future = None
            if relayed_msg:
                try:
                    await relayed_msg.delete()
                except Exception:
                    pass

        # Fallback stream
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
# BOT HANDLERS GENERATOR (FOR ALL YEAR BOTS)
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    bot_entity_box = {}

    @bot_client.on(events.NewMessage)
    async def relay_listener(event):
        global active_relay_future
        if event.is_private and event.sender_id == USER_CLIENT_ID:
            if active_relay_future and not active_relay_future.done():
                active_relay_future.set_result(event.message)

    # --- Student User Handlers ---
    @bot_client.on(events.NewMessage(pattern=r"^/start$"))
    async def start_handler(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)

        if is_banned(event.sender_id):
            await event.respond("⛔ You are restricted from using this service.")
            return

        # Check access with toggles
        allowed, reason = check_access(event.sender_id, bot_key)
        if not allowed:
            if reason.startswith("tier_mismatch"):
                user_tier = reason.split(":")[1]
                await event.respond(
                    f"⚠️ **Year Access Restricted**\n\nYour subscription is activated for **{user_tier.replace('_', ' ').title()}**, but this is the **{bot_title}**.\n\n"
                    f"To upgrade or change your enrolled year, contact {OWNER_CONTACT}."
                )
                return
            elif reason == "expired":
                await event.respond(
                    f"⚠️ **Subscription Expired!**\n\nYour access period has ended. Please contact {OWNER_CONTACT} to renew your subscription."
                )
                return
            else:
                await event.respond(LOCKED_MESSAGE.format(user_id=event.sender_id))
                await notify_manager_new_request(sender, bot_key)
                return

        # Show remaining daily download limit if anti-leech enabled
        limit_note = ""
        if db["settings"].get("daily_limit_enabled", False) and event.sender_id != ADMIN_ID:
            _, curr, mlimit = check_daily_limit(event.sender_id)
            limit_note = f"\n⚡ Daily Limit: `{curr}/{mlimit}` downloads used"

        await event.respond(
            f"🎓 **{bot_title}**{limit_note}\n\nSelect a subject to begin:",
            buttons=make_main_menu(bot_topics)
        )

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def home_handler(event):
        if is_banned(event.sender_id):
            await event.answer("⛔ Restricted.", alert=True)
            return
        allowed, _ = check_access(event.sender_id, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            await event.edit(LOCKED_MESSAGE.format(user_id=event.sender_id))
            return

        await event.edit(
            f"🎓 **{bot_title}**\n\nSelect a subject:",
            buttons=make_main_menu(bot_topics)
        )

    @bot_client.on(events.CallbackQuery(pattern=rb"^sub:(\d+)$"))
    async def sub_handler(event):
        if is_banned(event.sender_id):
            await event.answer("⛔ Restricted.", alert=True)
            return
        allowed, _ = check_access(event.sender_id, bot_key)
        if not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            await event.edit(LOCKED_MESSAGE.format(user_id=event.sender_id))
            return

        idx = int(event.pattern_match.group(1))
        subjects = list(bot_topics.keys())
        if 0 <= idx < len(subjects):
            subj = subjects[idx]
            user_subjects[event.sender_id] = subj
            await event.edit(f"📚 **{subj}**\n\nChoose an option:", buttons=make_subject_menu())

    @bot_client.on(events.CallbackQuery(data=b"lectures"))
    async def lectures_handler(event):
        allowed, _ = check_access(event.sender_id, bot_key)
        if is_banned(event.sender_id) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return
        uid = event.sender_id
        subj = user_subjects.get(uid)
        if not subj or subj not in bot_topics:
            await event.answer("Select subject again.")
            return

        topic_id = bot_topics[subj]
        await event.answer("Loading lectures...")
        units = await get_topic_units(topic_id)

        if not units:
            await event.edit(
                f"📚 **{subj}**\n\nNo lecture units found.",
                buttons=[[Button.inline("⬅️ Back", data=b"home")]]
            )
            return

        unit_names = list(units.keys())
        user_units[uid] = {"subject": subj, "units": units, "unit_names": unit_names}

        buttons = []
        for i, u in enumerate(unit_names):
            buttons.append([Button.inline(f"📂 #{u} ({len(units[u])})", data=f"unit:{i}".encode())])
        buttons.append([Button.inline("⬅️ Back", data=b"home")])

        await event.edit(f"📚 **{subj} Lectures**\n\nSelect a unit:", buttons=buttons)

    @bot_client.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
    async def unit_handler(event):
        allowed, _ = check_access(event.sender_id, bot_key)
        if is_banned(event.sender_id) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return
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
    async def file_handler(event):
        allowed, _ = check_access(event.sender_id, bot_key)
        if is_banned(event.sender_id) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return

        # Check Anti-Leech Daily Limit
        can_download, count, max_dl = check_daily_limit(event.sender_id)
        if not can_download:
            await event.answer("⚠️ Daily limit reached!", alert=True)
            await event.respond(f"⚠️️ **Daily Download Limit Reached!**\n\nYou have used your daily limit of `{max_dl}` lectures today. Your limit will reset at midnight.")
            return

        mid = int(event.pattern_match.group(1))
        await event.answer("⚡ Sending lecture...")
        status = await bot_client.send_message(event.chat_id, "⚡ **Sending lecture directly...**")

        try:
            msg = await user_client.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                success = await deliver_lecture(bot_client, bot_entity_box.get("entity"), event.chat_id, msg, status)
                if success:
                    record_download(event.sender_id)
            else:
                await status.edit("❌ Lecture file not found.")
        except Exception:
            logging.exception("File deliver error")
            await status.edit("❌ Delivery failed.")

    @bot_client.on(events.CallbackQuery(data=b"notes"))
    async def notes_handler(event):
        allowed, _ = check_access(event.sender_id, bot_key)
        if is_banned(event.sender_id) or not allowed:
            await event.answer("🔒 Paid access only.", alert=True)
            return
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

            await status.edit(f"⚡ Delivering note(s)...")
            for m in found:
                await deliver_lecture(bot_client, bot_entity_box.get("entity"), event.chat_id, m, status)
        except Exception:
            logging.exception("Notes deliver error")
            await status.edit("❌ Could not deliver notes.")

    return bot_entity_box

# ============================================================
# DEDICATED BOTS MANAGEMENT BOT ENGINE
# ============================================================

def make_manager_menu():
    return [
        [
            Button.inline("📊 System Stats", data=b"mgmt_stats"),
            Button.inline("⚙️ Feature Toggles", data=b"mgmt_toggles"),
        ],
        [
            Button.inline("⏳ Pending Requests", data=b"mgmt_pending"),
            Button.inline("💎 Verified Members", data=b"mgmt_approved"),
        ],
        [
            Button.inline("👥 Recent Users", data=b"mgmt_users"),
            Button.inline("🚫 Banned Users", data=b"mgmt_banned"),
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
        [Button.inline(f"⏳ Sub Expiry: {btn_exp}", data=b"tog:expiry_enabled")],
        [Button.inline(f"🎓 Year-Lock Tier: {btn_tier}", data=b"tog:tier_access_enabled")],
        [Button.inline(f"🛡️ Anti-Leech Limit: {btn_limit}", data=b"tog:daily_limit_enabled")],
        [Button.inline(f"☁️ Cloud Auto-Sync: {btn_sync}", data=b"tog:cloud_backup_enabled")],
        [Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]
    ]

def setup_manager_bot_handlers(client):
    """Sets up the dedicated Management Bot interface exclusively for the admin"""

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def manager_start(event):
        if event.sender_id != ADMIN_ID:
            await event.respond("⛔ Access Denied. This is a private management control center.")
            return

        total_users = len(db.get("users", {}))
        approved_users = len(db.get("approved", []))
        banned_users = len(db.get("banned", []))
        online_bots = len(active_bots)

        text = (
            "🎛️ **MBBS Bots Management Control Panel**\n\n"
            f"🤖 **Managed Bots Online:** `{online_bots}` bots\n"
            f"👥 **Total Registered Students:** `{total_users}`\n"
            f"💎 **Verified Paid Members:** `{approved_users}`\n"
            f"🚫 **Blocked Users:** `{banned_users}`\n\n"
            "Use the controls below to configure your features, manage users, or backup your system:"
        )
        await event.respond(text, buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_home"))
    async def cb_manager_home(event):
        if event.sender_id != ADMIN_ID:
            return
        total_users = len(db.get("users", {}))
        approved_users = len(db.get("approved", []))
        banned_users = len(db.get("banned", []))
        online_bots = len(active_bots)

        text = (
            "🎛️ **MBBS Bots Management Control Panel**\n\n"
            f"🤖 **Managed Bots Online:** `{online_bots}` bots\n"
            f"👥 **Total Registered Students:** `{total_users}`\n"
            f"💎 **Verified Paid Members:** `{approved_users}`\n"
            f"🚫 **Blocked Users:** `{banned_users}`\n\n"
            "Use the controls below to configure your features, manage users, or backup your system:"
        )
        await event.edit(text, buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_toggles"))
    async def cb_manager_toggles(event):
        if event.sender_id != ADMIN_ID:
            return
        text = (
            "⚙️ **System Feature Controls (ON / OFF)**\n\n"
            "Tap any toggle below to turn it ON or OFF instantly:\n\n"
            "• **Sub Expiry:** When OFF, approvals are permanent Lifetime. When ON, access expires automatically.\n"
            "• **Year-Lock Tier:** When OFF, students can use all bots. When ON, only the year bot they bought.\n"
            "• **Anti-Leech Limit:** Limits lectures per student per day to stop spam/account sharing.\n"
            "• **Cloud Auto-Sync:** Backs up database to Telegram automatically."
        )
        await event.edit(text, buttons=make_toggles_menu())

    @client.on(events.CallbackQuery(pattern=rb"^tog:(.+)$"))
    async def cb_toggle_switch(event):
        if event.sender_id != ADMIN_ID:
            return
        key = event.pattern_match.group(1).decode()
        if key in db["settings"]:
            db["settings"][key] = not db["settings"][key]
            save_db(db)
            state_str = "ENABLED (ON)" if db["settings"][key] else "DISABLED (OFF)"
            await event.answer(f"Feature {key} is now {state_str}!", alert=True)
            await cb_manager_toggles(event)

    @client.on(events.CallbackQuery(data=b"mgmt_do_backup"))
    async def cb_do_backup(event):
        if event.sender_id != ADMIN_ID:
            return
        await event.answer("Dispatching cloud backup to chat...")
        await trigger_cloud_backup()
        await event.edit("✅ **Cloud backup dispatched!** A secure copy of `bot_database.json` has been sent directly to this chat.", buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(data=b"mgmt_stats"))
    async def cb_stats(event):
        if event.sender_id != ADMIN_ID:
            return
        total = len(db.get("users", {}))
        approved = len(db.get("approved", []))
        banned = len(db.get("banned", []))
        uptime = int(time.time() - START_TIME)
        up_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

        settings = db["settings"]
        t_exp = "🟢 ON" if settings.get("expiry_enabled") else "🔴 OFF"
        t_tier = "🟢 ON" if settings.get("tier_access_enabled") else "🔴 OFF"
        t_limit = "🟢 ON" if settings.get("daily_limit_enabled") else "🔴 OFF"

        bot_list = "\n".join([f"• `{k}`: Online" for k in active_bots.keys()])
        text = (
            "📊 **Live System Analytics**\n\n"
            f"👥 **Total Students:** `{total}`\n"
            f"💎 **Paid Verified:** `{approved}`\n"
            f"🚫 **Blocked:** `{banned}`\n"
            f"⏱️ **Uptime:** `{up_str}`\n\n"
            f"⚙️ **Active Toggles:**\n"
            f"• Sub Expiry: {t_exp}\n"
            f"• Year-Lock: {t_tier}\n"
            f"• Anti-Leech: {t_limit}\n\n"
            f"🤖 **Connected Bots:**\n{bot_list}"
        )
        await event.edit(text, buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]])

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
            await event.edit(
                "✅ **No pending access requests!** All registered students are verified or dealt with.",
                buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]]
            )
            return

        buttons = []
        for uid, udata in pending[-8:]:
            name = udata.get("first_name", "Student")
            buttons.append([
                Button.inline(f"⚡ Approve {name} ({uid})", data=f"adm_app:{uid}".encode()),
                Button.inline(f"⚙️ Tier/Exp", data=f"adm_tier_opt:{uid}".encode())
            ])
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])

        await event.edit(f"⏳ **Pending Verification Requests ({len(pending)}):**\nTap to approve:", buttons=buttons)

    # Specific Tier & Expiry selection menu for a user
    @client.on(events.CallbackQuery(pattern=rb"^adm_tier_opt:(\d+)$"))
    async def cb_tier_options(event):
        if event.sender_id != ADMIN_ID:
            return
        uid = int(event.pattern_match.group(1))
        buttons = [
            [
                Button.inline("👑 All Years (Lifetime)", data=f"adm_gr:{uid}:all:0".encode()),
                Button.inline("📅 All Years (30 Days)", data=f"adm_gr:{uid}:all:30".encode()),
            ],
            [
                Button.inline("🎓 1st Year (30 Days)", data=f"adm_gr:{uid}:year_1:30".encode()),
                Button.inline("🎓 1st Year (1 Year)", data=f"adm_gr:{uid}:year_1:365".encode()),
            ],
            [
                Button.inline("🎓 2nd Year (30 Days)", data=f"adm_gr:{uid}:year_2:30".encode()),
                Button.inline("🎓 2nd Year (1 Year)", data=f"adm_gr:{uid}:year_2:365".encode()),
            ],
            [
                Button.inline("🎓 3rd Year (1 Year)", data=f"adm_gr:{uid}:year_3:365".encode()),
                Button.inline("🎓 Final Year (1 Year)", data=f"adm_gr:{uid}:final_year:365".encode()),
            ],
            [
                Button.inline("⬅️ Cancel", data=b"mgmt_home")
            ]
        ]
        await event.edit(f"⚙️ **Select Enrolled Tier & Duration for User `{uid}`:**", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_gr:(\d+):([a-z0-9_]+):(\d+)$"))
    async def cb_grant_custom(event):
        if event.sender_id != ADMIN_ID:
            return
        uid = int(event.pattern_match.group(1))
        tier = event.pattern_match.group(2).decode()
        days = int(event.pattern_match.group(3))

        expiry_date = None
        exp_text = "Permanent Lifetime"
        if days > 0:
            expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            exp_text = f"Valid until `{expiry_date}` ({days} days)"

        if uid not in db["approved"]:
            db["approved"].append(uid)

        db["approved_details"][str(uid)] = {
            "tier": tier,
            "expiry": expiry_date,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_db(db)
        await trigger_cloud_backup()

        await event.answer("✅ Enrolled Successfully!", alert=True)
        tier_title = BOT_TITLES_MAP.get(tier, tier.title())
        await event.edit(
            f"✅ **Access Granted!**\n\n👤 User: `{uid}`\n🎓 Enrolled Tier: **{tier_title}**\n⏳ Expiry: {exp_text}",
            buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]]
        )

        # Notify student
        for bot in active_bots.values():
            try:
                await bot.send_message(
                    uid,
                    f"🎉 **Your account has been verified!**\n\n🎓 Enrolled: **{tier_title}**\n⏳ Duration: {exp_text}\n\nSend /start to begin studying!"
                )
                break
            except Exception:
                pass

    @client.on(events.CallbackQuery(data=b"mgmt_users"))
    async def cb_users(event):
        if event.sender_id != ADMIN_ID:
            return
        users = db.get("users", {})
        if not users:
            await event.edit("No users registered yet.", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])
            return

        msg = f"👥 **Recent 15 Registered Students:**\n\n"
        for uid, udata in list(users.items())[-15:]:
            name = udata.get("first_name", "Unknown")
            uname = f"@{udata.get('username')}" if udata.get("username") else "No username"
            status = "💎" if int(uid) in db.get("approved", []) else ("⛔" if is_banned(uid) else "🔒")
            tier = db.get("approved_details", {}).get(str(uid), {}).get("tier", "all")
            msg += f"{status} `{uid}`: **{name}** ({uname}) [{tier}]\n"

        await event.edit(msg, buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(data=b"mgmt_approved"))
    async def cb_approved(event):
        if event.sender_id != ADMIN_ID:
            return
        approved_list = db.get("approved", [])
        msg = f"💎 **Verified Paid Students ({len(approved_list)}):**\n\n"
        buttons = []
        for uid in approved_list[-10:]:
            if uid == ADMIN_ID:
                continue
            udata = db.get("users", {}).get(str(uid), {})
            name = udata.get("first_name", f"User {uid}")
            det = db.get("approved_details", {}).get(str(uid), {})
            t_name = det.get("tier", "all")
            buttons.append([Button.inline(f"❌ Revoke {name} ({t_name})", data=f"adm_rev:{uid}".encode())])

        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await event.edit(msg + "Tap any user below to revoke their access:", buttons=buttons)

    @client.on(events.CallbackQuery(data=b"mgmt_banned"))
    async def cb_banned(event):
        if event.sender_id != ADMIN_ID:
            return
        banned_list = db.get("banned", [])
        if not banned_list:
            await event.edit("🎉 No users are currently banned.", buttons=[[Button.inline("⬅️ Back", data=b"mgmt_home")]])
            return

        buttons = []
        for uid in banned_list[-10:]:
            buttons.append([Button.inline(f"🔓 Unban `{uid}`", data=f"adm_unb:{uid}".encode())])
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])
        await event.edit(f"🚫 **Blocked Users ({len(banned_list)}):**\nTap to unban:", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"^adm_app:(\d+)$"))
    async def cb_quick_approve(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id not in db["approved"]:
            db["approved"].append(target_id)
            db["approved_details"][str(target_id)] = {
                "tier": "all",
                "expiry": None,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_db(db)
            await trigger_cloud_backup()
            await event.answer("✅ Access Granted (All Years Lifetime)!", alert=True)
            await event.edit(f"✅ User `{target_id}` approved with Full Access!", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])
            for bot in active_bots.values():
                try:
                    await bot.send_message(
                        target_id,
                        "🎉 **Your payment was verified and access granted!**\n\nSend /start to browse all your MBBS lectures and notes!"
                    )
                    break
                except Exception:
                    pass
        else:
            await event.answer("Already approved.", alert=True)

    @client.on(events.CallbackQuery(pattern=rb"^adm_rev:(\d+)$"))
    async def cb_quick_revoke(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("approved", []):
            db["approved"].remove(target_id)
            save_db(db)
            await trigger_cloud_backup()
            await event.answer("🔒 Access Revoked!", alert=True)
            await event.edit(f"🔒 Access revoked for user `{target_id}`.", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])
        else:
            await event.answer("User was not approved.", alert=True)

    @client.on(events.CallbackQuery(pattern=rb"^adm_ban:(\d+)$"))
    async def cb_quick_ban(event):
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
            await event.edit(f"⛔ User `{target_id}` banned across all bots.", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(pattern=rb"^adm_unb:(\d+)$"))
    async def cb_quick_unban(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("banned", []):
            db["banned"].remove(target_id)
            save_db(db)
            await trigger_cloud_backup()
            await event.answer("✅ User Unbanned!", alert=True)
            await event.edit(f"✅ User `{target_id}` unbanned.", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])

    # Text commands in Management Bot
    @client.on(events.NewMessage(pattern=r"^/broadcast (.+)"))
    async def manager_broadcast(event):
        if event.sender_id != ADMIN_ID:
            return
        text = event.pattern_match.group(1).strip()
        users = db.get("users", {})
        status = await event.respond(f"📢 Broadcasting to {len(users)} students across all bots...")
        sent, failed = 0, 0

        sender_bot = list(active_bots.values())[0] if active_bots else client
        for uid in list(users.keys()):
            if is_banned(uid):
                continue
            try:
                await sender_bot.send_message(int(uid), f"📢 **Announcement:**\n\n{text}")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await status.edit(f"✅ Broadcast complete!\n\nDelivered: `{sent}` | Failed: `{failed}`")

    @client.on(events.NewMessage(pattern=r"^/approve (\d+)$"))
    async def manager_cmd_approve(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id not in db["approved"]:
            db["approved"].append(target_id)
            db["approved_details"][str(target_id)] = {"tier": "all", "expiry": None, "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            save_db(db)
            await trigger_cloud_backup()
            await event.respond(f"✅ User `{target_id}` approved (All Years Lifetime)!")
        else:
            await event.respond(f"ℹ️️ User `{target_id}` is already approved.")

    @client.on(events.NewMessage(pattern=r"^/remove (\d+)$"))
    async def manager_cmd_remove(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("approved", []):
            db["approved"].remove(target_id)
            save_db(db)
            await trigger_cloud_backup()
            await event.respond(f"🔒 Access revoked for `{target_id}`.")
        else:
            await event.respond(f"ℹ️ User `{target_id}` was not in the approved list.")

# ============================================================
# ENGINE ENTRYPOINT
# ============================================================

async def main():
    global USER_CLIENT_ID, manager_bot_client
    os.makedirs("downloads", exist_ok=True)
    await start_web_server()

    logging.info("Connecting Telegram user client...")
    await user_client.start()
    user_me = await user_client.get_me()
    USER_CLIENT_ID = user_me.id

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

    # Cloud Auto-Restore Check
    if manager_bot_client:
        await auto_restore_from_telegram()

    logging.info("All MBBS bots and Management Control Bot online.")
    await asyncio.gather(*runners)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down.")
    except Exception:
        logging.exception("Fatal engine crash")
