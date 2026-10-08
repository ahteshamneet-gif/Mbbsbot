import os
import sys
import json
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx

# ================= LOGGING SETUP =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MbbsMultiBot")

# ================= SECURE ENVIRONMENT VARIABLES =================
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8417145295"))
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/").strip()
PORT = int(os.environ.get("PORT", 8080))

BOT_TOKENS = {
    "mgmt": os.environ.get("BOT_TOKEN_MGMT", "").strip(),
    "year1": os.environ.get("BOT_TOKEN_YEAR1", "").strip(),
    "year2": os.environ.get("BOT_TOKEN_YEAR2", "").strip(),
    "year3": os.environ.get("BOT_TOKEN_YEAR3", "").strip(),
    "year4": os.environ.get("BOT_TOKEN_YEAR4", "").strip(),
}

BOT_NAMES = {
    "mgmt": "Management Bot",
    "year1": "1st Year MBBS Bot",
    "year2": "2nd Year MBBS Bot",
    "year3": "3rd Year MBBS Bot",
    "year4": "4th Year MBBS Bot",
}

# ================= RENDER DUMMY WEB SERVER (PORT BINDING) =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"MBBS Bot Cluster Active and Healthy")

    def log_message(self, format, *args):
        return  # Suppress HTTP request logs to keep terminal clean

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    logger.info(f"🌐 Internal health check server listening on port {PORT}")
    server.serve_forever()

# Start dummy server in background daemon thread
threading.Thread(target=run_health_server, daemon=True).start()

# ================= USER PERSISTENCE DATABASE =================
DATA_FILE = "users_db.json"

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading {DATA_FILE}: {e}")
    return {"users": {}}

def save_db(db_data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db_data, f, indent=2)
    except Exception as e:
        logger.error(f"Error writing {DATA_FILE}: {e}")

db = load_db()

def get_or_create_user(user_id, username, first_name):
    uid_str = str(user_id)
    if uid_str not in db["users"]:
        stu_id = f"STU-{str(user_id)[-4:]}"
        stu_pwd = f"mbbs{str(user_id)[-4:]}"
        db["users"][uid_str] = {
            "id": user_id,
            "stu_id": stu_id,
            "password": stu_pwd,
            "username": username or "",
            "name": first_name or "Student",
            "tier": "None",
            "status": "Pending"
        }
        save_db(db)
    else:
        if username:
            db["users"][uid_str]["username"] = username
        if first_name:
            db["users"][uid_str]["name"] = first_name
        save_db(db)
    return db["users"][uid_str]

def build_login_url(user_data):
    uid = user_data["stu_id"]
    key = user_data["password"]
    name = user_data["name"]
    return f"{WEB_APP_URL}?uid={uid}&key={key}&name={name}#uid={uid}&key={key}&name={name}"

# ================= TELEGRAM DISPATCHERS =================
async def send_message(client, token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        logger.error(f"sendMessage error: {e}")

async def edit_message(client, token, chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        logger.error(f"editMessageText error: {e}")

async def answer_callback(client, token, callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = True
    try:
        await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        logger.error(f"answerCallbackQuery error: {e}")

# ================= STUDY BOTS HANDLERS =================
async def handle_study_update(client, token, bot_name, update):
    message = update.get("message")
    if not message or "text" not in message:
        return

    text = message["text"].strip()
    if not text.startswith("/start"):
        return

    sender = message.get("from", {})
    user_id = sender.get("id")
    username = sender.get("username", "")
    first_name = sender.get("first_name", "Student")

    user_info = get_or_create_user(user_id, username, first_name)
    is_full_access = (user_info.get("status") == "Approved" and "Full" in user_info.get("tier", ""))

    if is_full_access or user_id == ADMIN_ID:
        login_link = build_login_url(user_info)
        reply = (
            f"🩺 *Welcome to {bot_name}*\n\n"
            f"👤 *Candidate:* {user_info['name']}\n"
            f"🆔 *Student ID:* `{user_info['stu_id']}`\n"
            f"🔑 *Password:* `{user_info['password']}`\n"
            f"💎 *Access Tier:* `{user_info['tier']}`\n\n"
            f"Your account is verified. Click below to launch your CBT Question Bank portal:"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🚀 Launch MBBS CBT Q-Bank", "url": login_link}],
                [{"text": "💬 Support & Inquiries", "url": "https://t.me/Nothing_0786"}]
            ]
        }
    else:
        reply = (
            f"🔒 *{bot_name} — Restricted Access*\n\n"
            f"Hello {user_info['name']},\n"
            f"This bot and its associated CBT Q-Bank are restricted to enrolled students.\n\n"
            f"🆔 *Registered ID:* `{user_info['stu_id']}`\n"
            f"⚠️ *Status:* Account Pending Approval\n\n"
            f"Contact the administrator to activate your seat."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "💎 Get Full Subscription", "url": "https://t.me/Nothing_0786"}]
            ]
        }

    await send_message(client, token, message["chat"]["id"], reply, markup)

# ================= MANAGEMENT BOT HANDLERS =================
ITEMS_PER_PAGE = 8

async def handle_mgmt_update(client, token, update):
    if "message" in update:
        msg = update["message"]
        sender_id = msg.get("from", {}).get("id")
        text = msg.get("text", "").strip()

        if sender_id != ADMIN_ID:
            if text.startswith("/start"):
                await send_message(client, token, msg["chat"]["id"], "⛔ *Access Denied:* Administrator hub only.")
            return

        if text.startswith("/start"):
            welcome = (
                "👑 *MBBS Management Bot — Admin Hub*\n\n"
                "Select an option to manage students, approve memberships, and track access:"
            )
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "👥 Registered Users", "callback_data": "mgmt_users_0"},
                        {"text": "💎 Verified Members", "callback_data": "mgmt_approved_0"}
                    ],
                    [
                        {"text": "📊 System Stats", "callback_data": "mgmt_stats"},
                        {"text": "🌐 Open Q-Bank", "url": WEB_APP_URL}
                    ]
                ]
            }
            await send_message(client, token, msg["chat"]["id"], welcome, markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        sender_id = cb.get("from", {}).get("id")
        data = cb.get("data", "")
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        msg_id = cb.get("message", {}).get("message_id")
        cb_id = cb.get("id")

        if sender_id != ADMIN_ID:
            await answer_callback(client, token, cb_id, "Unauthorized.")
            return

        await answer_callback(client, token, cb_id)

        if data == "mgmt_main":
            text = (
                "👑 *MBBS Management Bot — Admin Hub*\n\n"
                "Select an option to manage students, approve memberships, and track access:"
            )
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "👥 Registered Users", "callback_data": "mgmt_users_0"},
                        {"text": "💎 Verified Members", "callback_data": "mgmt_approved_0"}
                    ],
                    [
                        {"text": "📊 System Stats", "callback_data": "mgmt_stats"},
                        {"text": "🌐 Open Q-Bank", "url": WEB_APP_URL}
                    ]
                ]
            }
            await edit_message(client, token, chat_id, msg_id, text, markup)

        elif data.startswith("mgmt_users_"):
            page = int(data.split("_")[2])
            all_users = list(db["users"].values())
            total = len(all_users)

            if total == 0:
                markup = {"inline_keyboard": [[{"text": "◀️ Back", "callback_data": "mgmt_main"}]]}
                await edit_message(client, token, chat_id, msg_id, "ℹ️ No registered users found.", markup)
                return

            total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            start = page * ITEMS_PER_PAGE
            page_users = all_users[start:start + ITEMS_PER_PAGE]

            text = f"👥 *Registered Users (Page {page + 1}/{total_pages})*\n\n"
            keyboard = []
            for u in page_users:
                status_icon = "💎" if u.get("status") == "Approved" else "⏳"
                keyboard.append([{"text": f"{status_icon} {u['name']} ({u['stu_id']})", "callback_data": f"usr_det_{u['id']}"}])

            nav = []
            if page > 0:
                nav.append({"text": "◀️ Prev", "callback_data": f"mgmt_users_{page - 1}"})
            if page < total_pages - 1:
                nav.append({"text": "Next ▶️", "callback_data": f"mgmt_users_{page + 1}"})
            if nav:
                keyboard.append(nav)

            keyboard.append([{"text": "◀️ Main Menu", "callback_data": "mgmt_main"}])
            await edit_message(client, token, chat_id, msg_id, text, {"inline_keyboard": keyboard})

        elif data.startswith("mgmt_approved_"):
            page = int(data.split("_")[2])
            approved_users = [u for u in db["users"].values() if u.get("status") == "Approved"]
            total = len(approved_users)

            if total == 0:
                markup = {"inline_keyboard": [[{"text": "◀️ Back", "callback_data": "mgmt_main"}]]}
                await edit_message(client, token, chat_id, msg_id, "ℹ️ No verified members yet.", markup)
                return

            total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            start = page * ITEMS_PER_PAGE
            page_users = approved_users[start:start + ITEMS_PER_PAGE]

            text = f"💎 *Verified Members (Page {page + 1}/{total_pages})*\n\n"
            keyboard = []
            for u in page_users:
                keyboard.append([{"text": f"✅ {u['name']} [{u['tier']}]", "callback_data": f"usr_det_{u['id']}"}])

            nav = []
            if page > 0:
                nav.append({"text": "◀️ Prev", "callback_data": f"mgmt_approved_{page - 1}"})
            if page < total_pages - 1:
                nav.append({"text": "Next ▶️", "callback_data": f"mgmt_approved_{page + 1}"})
            if nav:
                keyboard.append(nav)

            keyboard.append([{"text": "◀️ Main Menu", "callback_data": "mgmt_main"}])
            await edit_message(client, token, chat_id, msg_id, text, {"inline_keyboard": keyboard})

        elif data.startswith("usr_det_"):
            uid_str = data.split("_")[2]
            u = db["users"].get(uid_str)
            if not u:
                return

            uname = f"@{u['username']}" if u.get("username") else "None"
            text = (
                f"👤 *Student Profile Card*\n\n"
                f"• *Name:* {u['name']}\n"
                f"• *Telegram ID:* `{u['id']}`\n"
                f"• *Username:* {uname}\n"
                f"• *Student ID:* `{u['stu_id']}`\n"
                f"• *Password:* `{u['password']}`\n"
                f"• *Tier:* `{u.get('tier', 'None')}`\n"
                f"• *Status:* `{u.get('status', 'Pending')}`"
            )
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "💎 Full Access", "callback_data": f"tier_{u['id']}_Full Access"},
                        {"text": "📚 Lectures Only", "callback_data": f"tier_{u['id']}_Lectures Only"}
                    ],
                    [{"text": "🚫 Revoke Access", "callback_data": f"tier_{u['id']}_Revoke"}],
                    [{"text": "◀️ Back to Users", "callback_data": "mgmt_users_0"}]
                ]
            }
            await edit_message(client, token, chat_id, msg_id, text, markup)

        elif data.startswith("tier_"):
            parts = data.split("_", 2)
            uid_str = parts[1]
            action = parts[2]
            u = db["users"].get(uid_str)
            if u:
                if action == "Revoke":
                    u["tier"] = "None"
                    u["status"] = "Pending"
                else:
                    u["tier"] = action
                    u["status"] = "Approved"
                save_db(db)

                uname = f"@{u['username']}" if u.get("username") else "None"
                text = (
                    f"👤 *Student Profile Card*\n\n"
                    f"• *Name:* {u['name']}\n"
                    f"• *Telegram ID:* `{u['id']}`\n"
                    f"• *Username:* {uname}\n"
                    f"• *Student ID:* `{u['stu_id']}`\n"
                    f"• *Password:* `{u['password']}`\n"
                    f"• *Tier:* `{u.get('tier', 'None')}`\n"
                    f"• *Status:* `{u.get('status', 'Pending')}`"
                )
                markup = {
                    "inline_keyboard": [
                        [
                            {"text": "💎 Full Access", "callback_data": f"tier_{u['id']}_Full Access"},
                            {"text": "📚 Lectures Only", "callback_data": f"tier_{u['id']}_Lectures Only"}
                        ],
                        [{"text": "🚫 Revoke Access", "callback_data": f"tier_{u['id']}_Revoke"}],
                        [{"text": "◀️ Back to Users", "callback_data": "mgmt_users_0"}]
                    ]
                }
                await edit_message(client, token, chat_id, msg_id, text, markup)

        elif data == "mgmt_stats":
            total = len(db["users"])
            approved = sum(1 for u in db["users"].values() if u.get("status") == "Approved")
            text = (
                "📊 *Current System Statistics*\n\n"
                f"👥 *Total Registered Candidates:* `{total}`\n"
                f"💎 *Active Verified Members:* `{approved}`\n"
                f"⏳ *Pending Verification:* `{total - approved}`"
            )
            markup = {"inline_keyboard": [[{"text": "◀️ Back", "callback_data": "mgmt_main"}]]}
            await edit_message(client, token, chat_id, msg_id, text, markup)

# ================= ASYNCHRONOUS POLLER WORKER =================
async def poll_bot(key, token, name):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    offset = 0
    logger.info(f"🚀 Worker starting for {name}...")

    async with httpx.AsyncClient(timeout=35.0) as client:
        try:
            me_res = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if me_res.status_code == 200:
                username = me_res.json().get("result", {}).get("username")
                logger.info(f"✅ {name} connected as @{username}")
            else:
                logger.error(f"❌ {name} token rejected: {me_res.text}")
                return
        except Exception as e:
            logger.error(f"❌ Connection error for {name}: {e}")
            return

        while True:
            try:
                res = await client.get(url, params={"offset": offset, "timeout": 25})
                if res.status_code == 200:
                    data = res.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        if key == "mgmt":
                            asyncio.create_task(handle_mgmt_update(client, token, update))
                        else:
                            asyncio.create_task(handle_study_update(client, token, name, update))
                elif res.status_code == 409:
                    logger.warning(f"⚠️ Polling conflict for {name}. Backing off 5s...")
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3)

# ================= MAIN BOOTSTRAPPER =================
async def main():
    logger.info("Initializing multi-bot runner...")
    tasks = []

    for key, token in BOT_TOKENS.items():
        if token:
            tasks.append(poll_bot(key, token, BOT_NAMES[key]))
        else:
            logger.warning(f"Skipping {BOT_NAMES[key]}: Token missing in environment.")

    if not tasks:
        logger.critical("No bot tokens configured in Render environment!")
        sys.exit(1)

    logger.info(f"Starting {len(tasks)} parallel bot workers...")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Services stopped.")
