
import asyncio
import json
import logging
import os
import random
import re
import string
import time
from telethon import TelegramClient, events, Button
from telethon.errors import RPCError, FloodWaitError, ChatForwardsRestrictedError

# ============================================================
# CONFIGURATION
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8417145295"))
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "@Nothing_0786")

# Dedicated Trial Bot Token
TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN", "8789870802:AAGU7KY8FvoUf66sZ_hlPJMY80sYqmsNc00")

# Live GitHub Pages App Base URL
CBT_WEBAPP_BASE_URL = "https://ahteshamneet-gif.github.io/Mbbsbot/index.html"

# Database storage for access control and student credentials
BOT_DB_FILE = "bot_student_access.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def load_access_db():
    if os.path.exists(BOT_DB_FILE):
        try:
            with open(BOT_DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            logging.exception("Failed to load bot database")
    return {
        "users": {},        # { user_id: { name, username, tier, qbank_id, qbank_pass, joined } }
        "banned": []
    }

def save_access_db(data):
    try:
        with open(BOT_DB_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logging.exception("Failed to save bot database")

bot_db = load_access_db()

def get_or_create_qbank_creds(user_id):
    """Automatically generates a clean Student ID and simple password"""
    uid_str = str(user_id)
    if uid_str not in bot_db["users"]:
        bot_db["users"][uid_str] = {}
    
    user_data = bot_db["users"][uid_str]
    if "qbank_id" not in user_data or not user_data["qbank_id"]:
        suffix = uid_str[-4:] if len(uid_str) >= 4 else str(random.randint(1000, 9999))
        user_data["qbank_id"] = f"STU-{suffix}"
        user_data["qbank_pass"] = f"mbbs{random.randint(1000, 9999)}"
        save_access_db(bot_db)
    
    return user_data["qbank_id"], user_data["qbank_pass"]

def get_user_tier(user_id):
    """Returns 'admin', 'full', 'qbank', 'lectures_only', or None"""
    if int(user_id) == ADMIN_ID:
        return "admin"
    uid_str = str(user_id)
    return bot_db["users"].get(uid_str, {}).get("tier", None)

def is_banned(user_id):
    return int(user_id) in bot_db.get("banned", [])

def generate_webapp_launch_url(user_id):
    """
    Creates a 1-tap auto-login URL.
    Appends both ?query and #hash so mobile browsers and Telegram WebViews
    preserve credentials across redirects.
    """
    tier = get_user_tier(user_id)
    if tier == "admin":
        return CBT_WEBAPP_BASE_URL
    
    qid, qpass = get_or_create_qbank_creds(user_id)
    return f"{CBT_WEBAPP_BASE_URL}?uid={qid}&key={qpass}#uid={qid}&key={qpass}"

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

user_client = TelegramClient("termux_session", API_ID, API_HASH)
test_bot = TelegramClient("dummy_test_bot_session", API_ID, API_HASH)

USER_CLIENT_ID = None
BOT_ENTITY_FOR_USER = None

user_subjects = {}
user_units = {}
TOPIC_CACHE = {}
TOPIC_CACHE_TTL = 600

relay_lock = asyncio.Lock()
active_relay_future = None

def make_main_menu(topics):
    subjects = list(topics.keys())
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(subjects[i], data=f"d_sub:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(subjects[i + 1], data=f"d_sub:{i + 1}".encode()))
        buttons.append(row)
    return buttons

def make_subject_menu():
    return [
        [
            Button.inline("📚 Video Lectures", data=b"d_lectures"),
            Button.inline("📝 Notes & PDFs", data=b"d_notes"),
        ],
        [
            Button.inline("🎯 High-Yield MCQ Hub", data=b"d_mcq_hub"),
        ],
        [
            Button.inline("⬅ All Subjects", data=b"d_home"),
        ]
    ]

def make_mcq_hub_menu(user_id):
    tier = get_user_tier(user_id)
    has_qbank = tier in ["admin", "full", "qbank"]

    if has_qbank:
        launch_url = generate_webapp_launch_url(user_id)
        cbt_btn = Button.url("🌐 Launch MBBS CBT Q-Bank App", launch_url)
    else:
        cbt_btn = Button.inline("🔒 CBT Q-Bank (Upgrade Required)", data=b"mcq_upgrade_info")

    return [
        [cbt_btn],
        [Button.inline("📂 Topic-Wise Q-Bank PDFs", data=b"mcq:topic_wise")],
        [Button.inline("🏛️ Previous Year Questions (PYQs)", data=b"mcq:pyqs")],
        [Button.inline("🎲 Random / Mock Test MCQs", data=b"mcq:random")],
        [Button.inline("⬅️ Back to Subject", data=b"d_sub_back")],
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

async def deliver_lecture(chat_id, message, status_msg=None):
    global active_relay_future

    async with relay_lock:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        active_relay_future = future
        relayed_msg = None

        try:
            await user_client.forward_messages(BOT_ENTITY_FOR_USER, message)
            relayed_msg = await asyncio.wait_for(future, timeout=10.0)

            caption = message.text or ""
            try:
                await test_bot.send_file(
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
            logging.warning("Relay fallback to stream...")
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
                await test_bot.send_file(
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

@test_bot.on(events.NewMessage)
async def bot_relay_listener(event):
    global active_relay_future
    if event.is_private and event.sender_id == USER_CLIENT_ID:
        if active_relay_future and not active_relay_future.done():
            active_relay_future.set_result(event.message)

@test_bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):
    uid = event.sender_id
    if is_banned(uid):
        await event.respond("⛔ You are restricted from using this service.")
        return

    uid_str = str(uid)
    sender = await event.get_sender()
    name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "Student"
    username = f"@{sender.username}" if sender.username else ""

    if uid_str not in bot_db["users"]:
        bot_db["users"][uid_str] = {
            "name": name,
            "username": username,
            "tier": "pending",
            "joined": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_access_db(bot_db)
    else:
        bot_db["users"][uid_str]["name"] = name
        bot_db["users"][uid_str]["username"] = username
        save_access_db(bot_db)

    tier = get_user_tier(uid)

    credentials_banner = ""
    if tier in ["full", "qbank"]:
        qid, qpass = get_or_create_qbank_creds(uid)
        credentials_banner = (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "🩺 **YOUR Q-BANK LOGIN CREDENTIALS:**\n"
            f"🆔 **Student ID:** `{qid}`\n"
            f"🔑 **Password:** `{qpass}`\n"
            "*(Auto-logs you in when tapping Launch Q-Bank)*\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
    elif tier == "lectures_only":
        credentials_banner = (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "📚 **ENROLLED PLAN:** Lectures & Notes Only\n"
            f"💡 *To unlock the interactive CBT Q-Bank, contact {OWNER_CONTACT}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
    elif tier == "admin":
        credentials_banner = "\n\n👑 **ADMINISTRATOR SESSION ACTIVE**"

    welcome_text = (
        "🧪 **MBBS Comprehensive Learning & MCQ Hub**\n\n"
        "All 19 Subjects with instant video lectures, notes, and interactive Q-Bank test simulator."
        f"{credentials_banner}\n\n"
        "Select a subject below to begin:"
    )
    await event.respond(welcome_text, buttons=make_main_menu(TOPICS_ALL))

@test_bot.on(events.NewMessage(pattern=r"^/users$"))
async def admin_list_users(event):
    if event.sender_id != ADMIN_ID:
        return
    users = bot_db.get("users", {})
    if not users:
        await event.respond("ℹ️ No registered users found.")
        return

    msg = f"👥 **Registered Students ({len(users)}):**\n\n"
    for uid, data in list(users.items())[-20:]:
        name = data.get("name", "Student")
        uname = data.get("username", "")
        tier = data.get("tier", "pending")
        qid = data.get("qbank_id", "-")
        joined = data.get("joined", "")
        msg += f"• `{uid}`: **{name}** {uname}\n  └ Plan: `{tier}` | ID: `{qid}` | Joined: {joined}\n"

    await event.respond(msg)

@test_bot.on(events.NewMessage(pattern=r"^/approved$"))
async def admin_list_approved(event):
    if event.sender_id != ADMIN_ID:
        return
    users = bot_db.get("users", {})
    paid = [(uid, d) for uid, d in users.items() if d.get("tier") in ["full", "qbank", "lectures_only"]]
    
    if not paid:
        await event.respond("ℹ️ No verified paid members yet. Grant access via `/grant_qbank <id>` or `/grant_lectures <id>`.")
        return

    msg = f"💎 **Verified Paid Members ({len(paid)}):**\n\n"
    for uid, d in paid:
        tier_label = "🩺 Full (Lec + Q-Bank)" if d.get("tier") in ["full", "qbank"] else "📚 Lectures Only"
        qid = d.get("qbank_id", "None")
        qpass = d.get("qbank_pass", "None")
        msg += (
            f"👤 **{d.get('name', 'Student')}** (`{uid}`)\n"
            f"  └ Tier: **{tier_label}**\n"
            f"  └ Login: ID: `{qid}` | Pass: `{qpass}`\n\n"
        )

    await event.respond(msg)

@test_bot.on(events.NewMessage(pattern=r"^/grant_lectures (\d+)$"))
async def admin_grant_lectures(event):
    if event.sender_id != ADMIN_ID:
        return
    target_id = int(event.pattern_match.group(1))
    t_str = str(target_id)
    if t_str not in bot_db["users"]:
        bot_db["users"][t_str] = {}
    bot_db["users"][t_str]["tier"] = "lectures_only"
    save_access_db(bot_db)
    
    await event.respond(f"✅ User `{target_id}` set to **Lectures & Notes Only** (No Q-Bank credentials issued).")
    try:
        await test_bot.send_message(
            target_id,
            "🎉 **Access Granted!**\n\nYou have been enrolled in **MBBS Lectures & Notes**. Send /start to begin browsing lectures!"
        )
    except Exception:
        pass

@test_bot.on(events.NewMessage(pattern=r"^/grant_qbank (\d+)$"))
async def admin_grant_qbank(event):
    if event.sender_id != ADMIN_ID:
        return
    target_id = int(event.pattern_match.group(1))
    t_str = str(target_id)
    if t_str not in bot_db["users"]:
        bot_db["users"][t_str] = {}
    bot_db["users"][t_str]["tier"] = "full"
    qid, qpass = get_or_create_qbank_creds(target_id)
    save_access_db(bot_db)

    launch_url = generate_webapp_launch_url(target_id)
    await event.respond(
        f"✅ User `{target_id}` granted **Full Access (Lectures + Q-Bank)**!\n"
        f"Generated Login ➔ ID: `{qid}` | Pass: `{qpass}`"
    )

    try:
        welcome_card = (
            "🎉 **Welcome to MBBS Master Q-Bank!**\n\n"
            "Your interactive exam simulator access is now active:\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Your Student ID:** `{qid}`\n"
            f"🔑 **Your Password:** `{qpass}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tap the button below to start solving chapter MCQs right away:"
        )
        await test_bot.send_message(
            target_id,
            welcome_card,
            buttons=[[Button.url("🌐 Launch Interactive Q-Bank", launch_url)]]
        )
    except Exception:
        pass

@test_bot.on(events.NewMessage(pattern=r"^/stats$"))
async def admin_stats(event):
    if event.sender_id != ADMIN_ID:
        return
    users = bot_db.get("users", {})
    full_count = sum(1 for u in users.values() if u.get("tier") in ["full", "qbank"])
    lec_count = sum(1 for u in users.values() if u.get("tier") == "lectures_only")
    
    await event.respond(
        "📊 **Bot Access Analytics:**\n\n"
        f"👥 **Total Registered:** `{len(users)}`\n"
        f"🩺 **Full Q-Bank Enrolled:** `{full_count}`\n"
        f"📚 **Lectures Only Enrolled:** `{lec_count}`\n"
        f"🚫 **Banned:** `{len(bot_db.get('banned', []))}`\n\n"
        "Use `/users` to list all registered students or `/approved` to see login credentials."
    )

@test_bot.on(events.NewMessage(pattern=r"^/ban (\d+)$"))
async def admin_ban(event):
    if event.sender_id != ADMIN_ID:
        return
    tid = int(event.pattern_match.group(1))
    if tid not in bot_db["banned"]:
        bot_db["banned"].append(tid)
        save_access_db(bot_db)
        await event.respond(f"⛔ User `{tid}` has been banned.")

@test_bot.on(events.NewMessage(pattern=r"^/unban (\d+)$"))
async def admin_unban(event):
    if event.sender_id != ADMIN_ID:
        return
    tid = int(event.pattern_match.group(1))
    if tid in bot_db["banned"]:
        bot_db["banned"].remove(tid)
        save_access_db(bot_db)
        await event.respond(f"✅ User `{tid}` unbanned.")

@test_bot.on(events.CallbackQuery(data=b"d_home"))
async def cb_home(event):
    if is_banned(event.sender_id):
        return
    await event.edit("🧪 **MBBS Comprehensive Learning & MCQ Hub**\n\nSelect a subject below:", buttons=make_main_menu(TOPICS_ALL))

@test_bot.on(events.CallbackQuery(pattern=rb"^d_sub:(\d+)$"))
async def cb_sub_select(event):
    if is_banned(event.sender_id):
        return
    idx = int(event.pattern_match.group(1))
    subjects = list(TOPICS_ALL.keys())
    if 0 <= idx < len(subjects):
        subj = subjects[idx]
        user_subjects[event.sender_id] = subj
        await event.edit(f"📚 **{subj}**\n\nChoose an option below:", buttons=make_subject_menu())

@test_bot.on(events.CallbackQuery(data=b"d_sub_back"))
async def cb_sub_back(event):
    uid = event.sender_id
    subj = user_subjects.get(uid, "Anatomy")
    await event.edit(f"📚 **{subj}**\n\nChoose an option below:", buttons=make_subject_menu())

@test_bot.on(events.CallbackQuery(data=b"d_lectures"))
async def cb_lectures(event):
    uid = event.sender_id
    subj = user_subjects.get(uid)
    if not subj or subj not in TOPICS_ALL:
        await event.answer("Please select subject again.")
        return

    topic_id = TOPICS_ALL[subj]
    await event.answer("Loading lectures...")
    units = await get_topic_units(topic_id)

    if not units:
        await event.edit(f"📚 **{subj}**\n\nNo lecture units found.", buttons=[[Button.inline("⬅️ Back", data=b"d_home")]])
        return

    unit_names = list(units.keys())
    user_units[uid] = {"subject": subj, "units": units, "unit_names": unit_names}

    buttons = []
    for i, u in enumerate(unit_names):
        buttons.append([Button.inline(f"📂 #{u} ({len(units[u])})", data=f"unit:{i}".encode())])
    buttons.append([Button.inline("⬅️ Back to Subject", data=b"d_sub_back")])

    await event.edit(f"📚 **{subj} Lectures**\n\nSelect a unit:", buttons=buttons)

@test_bot.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
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
        buttons.append([Button.inline("⬅️ Units", data=b"d_lectures")])

        await event.edit(f"📂 **#{unit_name}** ({len(lectures)} lectures):\n\nSelect lecture:", buttons=buttons)

@test_bot.on(events.CallbackQuery(pattern=rb"^file:(\d+)$"))
async def cb_file(event):
    mid = int(event.pattern_match.group(1))
    await event.answer("⚡ Sending lecture...")
    status = await test_bot.send_message(event.chat_id, "⚡ **Sending lecture directly...**")

    try:
        msg = await user_client.get_messages(GROUP_ID, ids=mid)
        if msg and msg.media:
            await deliver_lecture(event.chat_id, msg, status)
        else:
            await status.edit("❌ Lecture file not found.")
    except Exception:
        logging.exception("File deliver error")
        await status.edit("❌ Delivery failed.")

@test_bot.on(events.CallbackQuery(data=b"d_notes"))
async def cb_notes(event):
    uid = event.sender_id
    subj = user_subjects.get(uid)
    if not subj:
        await event.answer("Select subject again.")
        return

    status = await test_bot.send_message(event.chat_id, f"🔍 Searching notes for **{subj}**...")
    try:
        notes = await get_topic_messages(TOPICS_ALL.get("Notes", 33))
        clean_subj = re.sub(r"[^a-zA-Z0-9]", "", subj).lower()
        found = [m for m in notes if m.media and (clean_subj in (m.text or "").lower() or clean_subj in get_filename(m).lower())]

        if not found:
            await status.edit(f"❌ No notes found for **{subj}**.")
            return

        await status.edit("⚡ Delivering note(s)...")
        for m in found:
            await deliver_lecture(event.chat_id, m, status)
    except Exception:
        logging.exception("Notes deliver error")
        await status.edit("❌ Could not deliver notes.")

@test_bot.on(events.CallbackQuery(data=b"d_mcq_hub"))
async def cb_mcq_hub(event):
    uid = event.sender_id
    subj = user_subjects.get(uid, "Anatomy")
    await event.edit(
        f"🎯 **{subj} MCQ & Question Bank Hub**\n\n"
        "Select your practice material:\n\n"
        "• 🌐 **Interactive CBT App**: Full browser CBT test simulator with scorecards & stored progress.\n"
        "• 📂 **Topic-Wise Q-Bank**: Unit-wise question papers & PDFs.\n"
        "• 🏛️ **Previous Year Questions (PYQs)**: Recalls & past exams.\n"
        "• 🎲 **Random / Mock Test MCQs**: Mixed grand question banks.",
        buttons=make_mcq_hub_menu(uid)
    )

@test_bot.on(events.CallbackQuery(data=b"mcq_upgrade_info"))
async def cb_upgrade_info(event):
    await event.answer("🔒 Q-Bank Access Required", alert=True)
    await event.respond(
        f"🔒 **Interactive Q-Bank Not Included in Your Plan**\n\n"
        "Your account currently has access to **Lectures & Notes Only**.\n\n"
        f"To unlock the interactive CBT exam simulator with randomized questions, timers, and scorecards, contact {OWNER_CONTACT} to upgrade your plan."
    )

@test_bot.on(events.CallbackQuery(pattern=rb"^mcq:(.+)$"))
async def cb_mcq_category(event):
    cat = event.pattern_match.group(1).decode()
    uid = event.sender_id
    subj = user_subjects.get(uid, "Anatomy")

    titles = {
        "topic_wise": "📂 Topic-Wise Q-Bank PDFs",
        "pyqs": "🏛️ Previous Year Questions (PYQs)",
        "random": "🎲 Random / Mock Test MCQs"
    }

    await event.edit(
        f"📑 **{subj} — {titles.get(cat, 'MCQs')}**\n\n"
        "Searching available PDF question banks in storage...",
        buttons=[[Button.inline("⬅️ Back to MCQ Hub", data=b"d_mcq_hub")]]
    )

async def main():
    global USER_CLIENT_ID, BOT_ENTITY_FOR_USER
    os.makedirs("downloads", exist_ok=True)

    print("\n" + "=" * 60)
    print("⏳ Connecting user client ('termux_session')...")
    await user_client.start()
    user_me = await user_client.get_me()
    USER_CLIENT_ID = user_me.id
    print(f"✅ User client online: {user_me.first_name} (ID: {user_me.id})")

    print("⏳ Connecting test bot client ('dummy_test_bot_session')...")
    await test_bot.start(bot_token=TEST_BOT_TOKEN)
    bot_me = await test_bot.get_me()
    BOT_ENTITY_FOR_USER = await user_client.get_entity(bot_me.username)
    print(f"✅ Bot client online: @{bot_me.username} (ID: {bot_me.id})")

    print("\n" + "=" * 60)
    print(f"🎉 TRIAL DUMMY BOT ONLINE: @{bot_me.username}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print("Commands available for Admin:")
    print(" • /users     ➔ List all registered students")
    print(" • /approved  ➔ List verified members with Student IDs & Passwords")
    print(" • /stats     ➔ Total active enrollment statistics")
    print(" • /grant_qbank <id> ➔ Grant Full Access + Auto-generate credentials")
    print("=" * 60 + "\n")

    await asyncio.gather(
        user_client.run_until_disconnected(),
        test_bot.run_until_disconnected()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped cleanly.")
    except Exception as e:
        print(f"\nFatal error: {e}")
