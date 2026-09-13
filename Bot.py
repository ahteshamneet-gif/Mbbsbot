import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
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
    "Notes": 33,
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
    "Notes": 33,
}

TOPICS_Y2 = {
    "Pathology": 49,
    "Pharmacology": 50,
    "Microbiology": 5,
    "Forensic Medicine and Toxicology": 51,
    "Notes": 33,
}

TOPICS_Y3 = {
    "Community Medicine": 52,
    "Ophthalmology": 57,
    "Otorhinolaryngology (ENT)": 58,
    "Forensic Medicine and Toxicology": 51,
    "Notes": 33,
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
    "Notes": 33,
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

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                if "approved" not in data:
                    data["approved"] = []
                if "users" not in data:
                    data["users"] = {}
                if "banned" not in data:
                    data["banned"] = []
                return data
        except Exception:
            logging.exception("Failed to read database file")
    return {"users": {}, "banned": [], "approved": []}

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

def is_approved(user_id):
    uid = int(user_id)
    if uid == ADMIN_ID:
        return True
    return uid in db.get("approved", [])

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

async def notify_manager_new_request(user, bot_type):
    """Sends an instant notification with an Approve button to the Management Bot"""
    if not manager_bot_client:
        return
    try:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
        username = f"@{user.username}" if user.username else "No username"
        text = (
            f"🔔 **New Access Request!**\n\n"
            f"👤 **Student:** {name} ({username})\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🤖 **Bot:** `{bot_type}`\n"
            f"🕒 **Time:** `{datetime.now().strftime('%H:%M:%S')}`"
        )
        buttons = [
            [
                Button.inline("✅ Approve Access", data=f"adm_app:{user.id}".encode()),
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
# BOT HANDLERS GENERATOR
# ============================================================

def setup_bot_handlers(bot_client, bot_key, bot_topics, bot_title):
    bot_entity_box = {}

    @bot_client.on(events.NewMessage)
    async def relay_listener(event):
        global active_relay_future
        if event.is_private and event.sender_id == USER_CLIENT_ID:
            if active_relay_future and not active_relay_future.done():
                active_relay_future.set_result(event.message)

    # --- Admin Commands ---
    @bot_client.on(events.NewMessage(pattern=r"^/stats$"))
    async def admin_stats(event):
        if event.sender_id != ADMIN_ID:
            return
        total_users = len(db.get("users", {}))
        approved_users = len(db.get("approved", []))
        banned_count = len(db.get("banned", []))
        uptime_sec = int(time.time() - START_TIME)
        uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"

        text = (
            f"📊 **{bot_title} — Admin Panel**\n\n"
            f"👥 **Total Registered Users:** `{total_users}`\n"
            f"💎 **Verified Paid Users:** `{approved_users}`\n"
            f"🚫 **Blocked Users:** `{banned_count}`\n"
            f"⏱️ **Uptime:** `{uptime_str}`\n"
            f"🤖 **Active Bots Online:** `{len(active_bots)}` bots\n"
            f"🟢 **Server Status:** Running 24/7 on Render"
        )
        await event.respond(text)

    @bot_client.on(events.NewMessage(pattern=r"^/users$"))
    async def admin_users(event):
        if event.sender_id != ADMIN_ID:
            return
        users = db.get("users", {})
        if not users:
            await event.respond("No users recorded yet.")
            return

        msg = f"👥 **Recent Users ({len(users)} total):**\n\n"
        recent_users = list(users.items())[-20:]
        for uid, udata in reversed(recent_users):
            name = udata.get("first_name", "Unknown")
            uname = f"@{udata.get('username')}" if udata.get("username") else "No username"
            bot_tag = udata.get("bot_used", "all")
            status = " [💎 VERIFIED]" if is_approved(uid) else " [🔒 LOCKED]"
            if is_banned(uid):
                status = " [⛔ BANNED]"
            msg += f"• `{uid}`: **{name}** ({uname}) [{bot_tag}]{status}\n"
        await event.respond(msg)

    @bot_client.on(events.NewMessage(pattern=r"^/approve (\d+)$"))
    async def admin_approve(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id not in db["approved"]:
            db["approved"].append(target_id)
            save_db(db)
            await event.respond(f"✅ User `{target_id}` approved! They now have full access to all year bots.")
            try:
                await bot_client.send_message(
                    target_id,
                    "🎉 **Access Granted!**\n\nYour account is now verified. Send /start to access all your MBBS lectures and notes!"
                )
            except Exception:
                pass
        else:
            await event.respond(f"ℹ️ User `{target_id}` is already approved.")

    @bot_client.on(events.NewMessage(pattern=r"^/remove (\d+)$"))
    async def admin_remove(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id == ADMIN_ID:
            await event.respond("⚠️ You cannot revoke admin access.")
            return
        if target_id in db.get("approved", []):
            db["approved"].remove(target_id)
            save_db(db)
            await event.respond(f"🔒 Access revoked for user `{target_id}`.")
            try:
                await bot_client.send_message(
                    target_id,
                    "⚠️ Your subscription/access has expired or been removed. Please contact @Nothing_0786 to renew."
                )
            except Exception:
                pass
        else:
            await event.respond(f"ℹ️ User `{target_id}` was not in the approved list.")

    @bot_client.on(events.NewMessage(pattern=r"^/ban (\d+)$"))
    async def admin_ban(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id == ADMIN_ID:
            await event.respond("⚠️ You cannot ban yourself.")
            return
        if target_id not in db["banned"]:
            db["banned"].append(target_id)
            if target_id in db["approved"]:
                db["approved"].remove(target_id)
            save_db(db)
            await event.respond(f"✅ User `{target_id}` banned across all year bots.")
        else:
            await event.respond(f"ℹ️ User `{target_id}` is already banned.")

    @bot_client.on(events.NewMessage(pattern=r"^/unban (\d+)$"))
    async def admin_unban(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("banned", []):
            db["banned"].remove(target_id)
            save_db(db)
            await event.respond(f"✅ User `{target_id}` unbanned.")
        else:
            await event.respond(f"ℹ️ User `{target_id}` is not in ban list.")

    @bot_client.on(events.NewMessage(pattern=r"^/broadcast (.+)"))
    async def admin_broadcast(event):
        if event.sender_id != ADMIN_ID:
            return
        text = event.pattern_match.group(1).strip()
        users = db.get("users", {})
        status = await event.respond(f"📢 Broadcasting to {len(users)} students...")
        sent, failed = 0, 0
        for uid in list(users.keys()):
            if is_banned(uid):
                continue
            try:
                await bot_client.send_message(int(uid), f"📢 **Announcement:**\n\n{text}")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await status.edit(f"✅ Broadcast done! Delivered: `{sent}` | Failed: `{failed}`")

    # --- Student User Handlers ---
    @bot_client.on(events.NewMessage(pattern=r"^/start$"))
    async def start_handler(event):
        sender = await event.get_sender()
        track_user(sender, bot_key)

        if is_banned(event.sender_id):
            await event.respond("⛔ You are restricted from using this service.")
            return

        # Check paid approval
        if not is_approved(event.sender_id):
            await event.respond(LOCKED_MESSAGE.format(user_id=event.sender_id))
            # Dispatch instant alert with 1-click approve button to Management Bot
            await notify_manager_new_request(sender, bot_key)
            return

        await event.respond(
            f"🎓 **{bot_title}**\n\nSelect a subject to begin:",
            buttons=make_main_menu(bot_topics)
        )

    @bot_client.on(events.CallbackQuery(data=b"home"))
    async def home_handler(event):
        if is_banned(event.sender_id):
            await event.answer("⛔ Restricted.", alert=True)
            return
        if not is_approved(event.sender_id):
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
        if not is_approved(event.sender_id):
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
        if is_banned(event.sender_id) or not is_approved(event.sender_id):
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
        if is_banned(event.sender_id) or not is_approved(event.sender_id):
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
        if is_banned(event.sender_id) or not is_approved(event.sender_id):
            await event.answer("🔒 Paid access only.", alert=True)
            return
        mid = int(event.pattern_match.group(1))
        await event.answer("⚡ Sending lecture...")
        status = await bot_client.send_message(event.chat_id, "⚡ **Sending lecture directly...**")

        try:
            msg = await user_client.get_messages(GROUP_ID, ids=mid)
            if msg and msg.media:
                await deliver_lecture(bot_client, bot_entity_box.get("entity"), event.chat_id, msg, status)
            else:
                await status.edit("❌ Lecture file not found.")
        except Exception:
            logging.exception("File deliver error")
            await status.edit("❌ Delivery failed.")

    @bot_client.on(events.CallbackQuery(data=b"notes"))
    async def notes_handler(event):
        if is_banned(event.sender_id) or not is_approved(event.sender_id):
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
            Button.inline("⏳ Pending Requests", data=b"mgmt_pending"),
        ],
        [
            Button.inline("👥 Recent Users", data=b"mgmt_users"),
            Button.inline("💎 Verified Members", data=b"mgmt_approved"),
        ],
        [
            Button.inline("🚫 Banned Users", data=b"mgmt_banned"),
            Button.inline("🔄 Refresh Dashboard", data=b"mgmt_home"),
        ]
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
            "Select an action below to manage your bots in real time:"
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
            "Select an action below to manage your bots in real time:"
        )
        await event.edit(text, buttons=make_manager_menu())

    @client.on(events.CallbackQuery(data=b"mgmt_stats"))
    async def cb_stats(event):
        if event.sender_id != ADMIN_ID:
            return
        total = len(db.get("users", {}))
        approved = len(db.get("approved", []))
        banned = len(db.get("banned", []))
        uptime = int(time.time() - START_TIME)
        up_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

        bot_list = "\n".join([f"• `{k}`: Online" for k in active_bots.keys()])
        text = (
            "📊 **Live System Analytics**\n\n"
            f"👥 **Total Students:** `{total}`\n"
            f"💎 **Paid Verified:** `{approved}`\n"
            f"🚫 **Blocked:** `{banned}`\n"
            f"⏱️ **Uptime:** `{up_str}`\n"
            f"🟢 **Server:** Render Production Cloud\n\n"
            f"🤖 **Active Bots:**\n{bot_list}"
        )
        await event.edit(text, buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]])

    @client.on(events.CallbackQuery(data=b"mgmt_pending"))
    async def cb_pending(event):
        if event.sender_id != ADMIN_ID:
            return
        users = db.get("users", {})
        pending = [
            (uid, udata) for uid, udata in users.items()
            if not is_approved(uid) and not is_banned(uid)
        ]
        if not pending:
            await event.edit(
                "✅ **No pending access requests!** All registered students are either verified or dealt with.",
                buttons=[[Button.inline("⬅️ Back to Menu", data=b"mgmt_home")]]
            )
            return

        buttons = []
        for uid, udata in pending[-8:]:
            name = udata.get("first_name", "Student")
            buttons.append([Button.inline(f"✅ Approve {name} ({uid})", data=f"adm_app:{uid}".encode())])
        buttons.append([Button.inline("⬅️ Back to Menu", data=b"mgmt_home")])

        await event.edit(f"⏳ **Pending Verification Requests ({len(pending)}):**\nTap to approve instantly:", buttons=buttons)

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
            status = "💎" if is_approved(uid) else ("⛔" if is_banned(uid) else "🔒")
            msg += f"{status} `{uid}`: **{name}** ({uname})\n"

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
            buttons.append([Button.inline(f"❌ Revoke {name} ({uid})", data=f"adm_rev:{uid}".encode())])

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
            save_db(db)
            await event.answer("✅ Access Granted!", alert=True)
            await event.edit(f"✅ User `{target_id}` has been approved and granted full access!", buttons=[[Button.inline("⬅️ Menu", data=b"mgmt_home")]])
            # Notify the student on active bots
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

        # Choose the first active bot client to send
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
            save_db(db)
            await event.respond(f"✅ User `{target_id}` approved!")
        else:
            await event.respond(f"ℹ️ User `{target_id}` is already approved.")

    @client.on(events.NewMessage(pattern=r"^/remove (\d+)$"))
    async def manager_cmd_remove(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        if target_id in db.get("approved", []):
            db["approved"].remove(target_id)
            save_db(db)
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

            # If this is the dedicated Management Bot
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

    logging.info("All MBBS bots and Management Control Bot online.")
    await asyncio.gather(*runners)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down.")
    except Exception:
        logging.exception("Fatal engine crash")
