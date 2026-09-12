
import asyncio
import logging
import os
import re
import time
from aiohttp import web

from telethon import TelegramClient, events, Button
from telethon.errors import RPCError, FloodWaitError, ChatForwardsRestrictedError

# ============================================================
# CONFIGURATION
# ============================================================

API_ID = int(os.getenv("API_ID", "37864520"))
API_HASH = os.getenv("API_HASH", "d92bf252ab0a7835d2639d49920f714a")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8808156804:AAEaw2NqVi7wQXiP_TqMsGxnNTwyR2yICrs")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004409849262"))
PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================================
# TELEGRAM TOPICS
# ============================================================

TOPICS = {
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

# ============================================================
# CLIENTS & GLOBALS
# ============================================================

user_client = TelegramClient("session", API_ID, API_HASH)
bot = TelegramClient("mbbs_lecture_bot", API_ID, API_HASH)

USER_CLIENT_ID = None
BOT_USER_ID = None
BOT_ENTITY_FOR_USER = None

user_subjects = {}
user_units = {}
TOPIC_CACHE = {}
TOPIC_CACHE_TTL = 600

relay_lock = asyncio.Lock()
active_relay_future = None

# ============================================================
# HEALTH-CHECK WEB SERVER FOR RENDER (KEEPS BOT ALIVE)
# ============================================================

async def health_check(request):
    return web.Response(text="MBBS Telegram Bot is live and healthy!")

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
# MENUS
# ============================================================

def main_menu_buttons():
    subjects = list(TOPICS.keys())
    buttons = []
    for i in range(0, len(subjects), 2):
        row = [Button.inline(subjects[i], data=f"subject:{i}".encode())]
        if i + 1 < len(subjects):
            row.append(Button.inline(subjects[i + 1], data=f"subject:{i + 1}".encode()))
        buttons.append(row)
    return buttons

def subject_menu_buttons():
    return [
        [
            Button.inline("📚 Lectures", data=b"lectures"),
            Button.inline("📝 Notes", data=b"notes"),
        ],
        [
            Button.inline("⬅️ Back", data=b"home"),
        ]
    ]

def subject_index(subject):
    return list(TOPICS.keys()).index(subject)

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
# RELAY LISTENER
# ============================================================

@bot.on(events.NewMessage)
async def bot_pm_relay_listener(event):
    global active_relay_future
    if event.is_private and event.sender_id == USER_CLIENT_ID:
        if active_relay_future and not active_relay_future.done():
            active_relay_future.set_result(event.message)

# ============================================================
# INSTANT CLOUD DELIVERY ENGINE
# ============================================================

async def deliver_lecture_instant(chat_id, message, status_msg=None):
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
                await bot.send_file(
                    entity=chat_id,
                    file=relayed_msg.media,
                    caption=caption,
                    supports_streaming=True
                )
            except Exception as e:
                logging.info("send_file cloud fallback to forward: %s", e)
                await relayed_msg.forward_to(chat_id)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            logging.info("Instant cloud delivery succeeded.")
            return True

        except ChatForwardsRestrictedError:
            logging.warning("Source group has protected content. Falling back.")
        except asyncio.TimeoutError:
            logging.warning("Relay timeout.")
        except Exception:
            logging.exception("Relay error.")
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
                await bot.send_file(
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
# BOT HANDLERS
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):
    await event.respond(
        "🎓 **MBBS Lecture Library**\n\nSelect a subject to get started:",
        buttons=main_menu_buttons()
    )

@bot.on(events.CallbackQuery(data=b"home"))
async def home_handler(event):
    await event.edit(
        "🎓 **MBBS Lecture Library**\n\nSelect a subject:",
        buttons=main_menu_buttons()
    )

@bot.on(events.CallbackQuery(pattern=rb"^subject:(\d+)$"))
async def subject_handler(event):
    try:
        index = int(event.pattern_match.group(1))
        subjects = list(TOPICS.keys())
        if index < 0 or index >= len(subjects):
            await event.answer("Invalid subject.")
            return

        subject = subjects[index]
        user_subjects[event.sender_id] = subject

        await event.edit(
            f"📚 **{subject}**\n\nChoose an option below:",
            buttons=subject_menu_buttons()
        )
    except Exception:
        logging.exception("Subject handler error")
        await event.answer("Could not open subject.")

@bot.on(events.CallbackQuery(data=b"lectures"))
async def lectures_handler(event):
    try:
        user_id = event.sender_id
        subject = user_subjects.get(user_id)
        if not subject:
            await event.answer("Please select a subject again.")
            return

        topic_id = TOPICS.get(subject)
        if not topic_id:
            await event.answer("Subject topic not found.")
            return

        await event.answer("Loading lectures...")
        units = await get_topic_units(topic_id)

        if not units:
            await event.edit(
                f"📚 **{subject}**\n\nNo lecture units found.",
                buttons=[[Button.inline("⬅️ Back", data=f"subject:{subject_index(subject)}".encode())]]
            )
            return

        unit_names = list(units.keys())
        user_units[user_id] = {
            "subject": subject,
            "units": units,
            "unit_names": unit_names
        }

        buttons = []
        for index, unit in enumerate(unit_names):
            count = len(units[unit])
            buttons.append([Button.inline(f"📂 #{unit} ({count})", data=f"unit:{index}".encode())])

        buttons.append([Button.inline("⬅️ Back", data=f"subject:{subject_index(subject)}".encode())])

        await event.edit(
            f"📚 **{subject} Lectures**\n\nSelect a unit:",
            buttons=buttons
        )
    except Exception:
        logging.exception("Lecture menu error")
        await event.answer("Could not load lectures.")

@bot.on(events.CallbackQuery(pattern=rb"^unit:(\d+)$"))
async def unit_handler(event):
    try:
        user_id = event.sender_id
        data = user_units.get(user_id)
        if not data:
            await event.answer("Please open the subject again.")
            return

        unit_index = int(event.pattern_match.group(1))
        unit_names = data["unit_names"]
        units = data["units"]

        if unit_index < 0 or unit_index >= len(unit_names):
            await event.answer("Invalid unit.")
            return

        unit_name = unit_names[unit_index]
        lectures = units.get(unit_name, [])

        if not lectures:
            await event.answer("No lectures found.")
            return

        buttons = []
        for index, lecture in enumerate(lectures):
            filename = get_filename(lecture, index + 1)
            if len(filename) > 42:
                filename = filename[:39] + "..."
            buttons.append([Button.inline(f"📄 {filename}", data=f"file:{lecture.id}".encode())])

        buttons.append([Button.inline("⬅️ Units", data=b"back_units")])

        await event.edit(
            f"📂 **#{unit_name}**\n\nFound **{len(lectures)}** lecture(s).\n\nSelect a lecture:",
            buttons=buttons
        )
    except Exception:
        logging.exception("Unit handler error")
        await event.answer("Could not load this unit.")

@bot.on(events.CallbackQuery(data=b"back_units"))
async def back_units_handler(event):
    try:
        user_id = event.sender_id
        data = user_units.get(user_id)
        if not data:
            await event.answer("Please open the subject again.")
            return

        subject = data["subject"]
        units = data["units"]
        unit_names = data["unit_names"]

        buttons = []
        for index, unit in enumerate(unit_names):
            count = len(units[unit])
            buttons.append([Button.inline(f"📂 #{unit} ({count})", data=f"unit:{index}".encode())])

        buttons.append([Button.inline("⬅️ Back", data=f"subject:{subject_index(subject)}".encode())])

        await event.edit(f"📚 **{subject} Lectures**\n\nSelect a unit:", buttons=buttons)
    except Exception:
        logging.exception("Back units error")
        await event.answer("Something went wrong.")

@bot.on(events.CallbackQuery(pattern=rb"^file:(\d+)$"))
async def file_handler(event):
    message_id = int(event.pattern_match.group(1))
    await event.answer("⚡ Sending lecture...")
    status_msg = await bot.send_message(event.chat_id, "⚡ **Sending lecture directly...**")

    try:
        message = await user_client.get_messages(GROUP_ID, ids=message_id)
        if not message or not message.media:
            await status_msg.edit("❌ Lecture file not found.")
            return

        await deliver_lecture_instant(event.chat_id, message, status_msg)
    except FloodWaitError as e:
        await status_msg.edit(f"⚠️ Telegram flood wait. Retry in {e.seconds}s.")
    except Exception:
        logging.exception("File deliver error")
        await status_msg.edit("❌ Failed to deliver lecture.")

@bot.on(events.CallbackQuery(data=b"notes"))
async def notes_handler(event):
    user_id = event.sender_id
    subject = user_subjects.get(user_id)
    if not subject:
        await event.answer("Please select a subject again.")
        return

    await event.answer("Finding notes...")
    status_msg = await bot.send_message(event.chat_id, f"🔍 **Searching notes for {subject}...**")

    try:
        notes = await get_topic_messages(TOPICS["Notes"])
        subject_clean = re.sub(r"[^a-zA-Z0-9]", "", subject).lower()
        found_notes = []

        for message in notes:
            if not message.media:
                continue
            text = (message.text or "").lower()
            fname = get_filename(message).lower()
            clean_text = re.sub(r"[^a-zA-Z0-9]", "", text)
            clean_fname = re.sub(r"[^a-zA-Z0-9]", "", fname)

            if subject_clean in clean_text or subject_clean in clean_fname:
                found_notes.append(message)

        if not found_notes:
            await status_msg.edit(f"❌ No notes found for **{subject}**.")
            return

        await status_msg.edit(f"⚡ **Delivering note(s) for {subject}...**")
        for note_msg in found_notes:
            await deliver_lecture_instant(event.chat_id, note_msg, status_msg)

    except Exception:
        logging.exception("Notes deliver error")
        await status_msg.edit("❌ Could not deliver notes.")

# ============================================================
# START ENGINE
# ============================================================

async def main():
    global USER_CLIENT_ID, BOT_USER_ID, BOT_ENTITY_FOR_USER
    os.makedirs("downloads", exist_ok=True)

    # Start the web server for Render health checks
    await start_web_server()

    logging.info("Starting user client...")
    await user_client.start()

    logging.info("Starting bot...")
    await bot.start(bot_token=BOT_TOKEN)

    bot_me = await bot.get_me()
    user_me = await user_client.get_me()

    BOT_USER_ID = bot_me.id
    USER_CLIENT_ID = user_me.id
    BOT_ENTITY_FOR_USER = await user_client.get_entity(bot_me.username)

    try:
        await user_client.get_entity(GROUP_ID)
        logging.info("Group access verified.")
    except Exception:
        logging.warning("Please verify your user account is in GROUP_ID.")

    logging.info("MBBS Bot is live and running 24/7 on Render.")

    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot.run_until_disconnected()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped.")
    except Exception:
        logging.exception("Fatal error")
