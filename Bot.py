import os
import sys
import json
import logging
import asyncio
from telethon import TelegramClient, events, Button

# ================= LOGGING SETUP =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MbbsMultiBot")

# ================= ENVIRONMENT VARIABLES =================
API_ID = int(os.environ.get("API_ID", "27202302"))
API_HASH = os.environ.get("API_HASH", "2c4ec1bf4ec24190b2964fcb309605d3")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8417145295"))
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/").strip()

# Strip any whitespace/newlines that might have been pasted into Render
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

# ================= HANDLER REGISTRATION HELPERS =================
def attach_study_handlers(client, bot_name):
    @client.on(events.NewMessage(pattern=r"^/start"))
    async def study_start(event):
        sender = await event.get_sender()
        user_info = get_or_create_user(sender.id, sender.username, sender.first_name)
        is_full_access = (user_info.get("status") == "Approved" and "Full" in user_info.get("tier", ""))

        if is_full_access or sender.id == ADMIN_ID:
            login_link = build_login_url(user_info)
            text = (
                f"🩺 **Welcome to {bot_name}**\n\n"
                f"👤 **Candidate:** {user_info['name']}\n"
                f"🆔 **Student ID:** `{user_info['stu_id']}`\n"
                f"🔑 **Password:** `{user_info['password']}`\n"
                f"💎 **Access Tier:** `{user_info['tier']}`\n\n"
                f"Your account is verified. Launch your CBT Question Bank portal below:"
            )
            buttons = [
                [Button.url("🚀 Launch MBBS CBT Q-Bank", login_link)],
                [Button.url("💬 Support & Inquiries", "https://t.me/Nothing_0786")]
            ]
        else:
            text = (
                f"🔒 **{bot_name} — Restricted Access**\n\n"
                f"Hello {user_info['name']},\n"
                f"This bot and its associated CBT Q-Bank are restricted to enrolled students.\n\n"
                f"🆔 **Registered ID:** `{user_info['stu_id']}`\n"
                f"⚠️ **Status:** Account Pending Approval\n\n"
                f"Contact the administrator to activate your access."
            )
            buttons = [
                [Button.url("💎 Get Full Subscription", "https://t.me/Nothing_0786")]
            ]

        await event.respond(text, buttons=buttons)

ITEMS_PER_PAGE = 8

def attach_mgmt_handlers(client):
    @client.on(events.NewMessage(pattern=r"^/start"))
    async def mgmt_start(event):
        if event.sender_id != ADMIN_ID:
            await event.respond("⛔ **Access Denied:** Administrator hub only.")
            return

        text = (
            "👑 **MBBS Management Bot — Admin Hub**\n\n"
            "Select an option to manage students, approve memberships, and track access:"
        )
        buttons = [
            [Button.inline("👥 Registered Users", b"mgmt_users_0"), Button.inline("💎 Verified Members", b"mgmt_approved_0")],
            [Button.inline("📊 System Stats", b"mgmt_stats"), Button.url("🌐 Open Q-Bank", WEB_APP_URL)]
        ]
        await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=b"mgmt_main"))
    async def cb_main(event):
        if event.sender_id != ADMIN_ID:
            return
        text = (
            "👑 **MBBS Management Bot — Admin Hub**\n\n"
            "Select an option to manage students, approve memberships, and track access:"
        )
        buttons = [
            [Button.inline("👥 Registered Users", b"mgmt_users_0"), Button.inline("💎 Verified Members", b"mgmt_approved_0")],
            [Button.inline("📊 System Stats", b"mgmt_stats"), Button.url("🌐 Open Q-Bank", WEB_APP_URL)]
        ]
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"mgmt_users_(\d+)"))
    async def cb_users(event):
        if event.sender_id != ADMIN_ID:
            return
        page = int(event.pattern_match.group(1))
        all_users = list(db["users"].values())
        total = len(all_users)

        if total == 0:
            await event.edit("ℹ️ No registered users found.", buttons=[Button.inline("◀️ Back", b"mgmt_main")])
            return

        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        start = page * ITEMS_PER_PAGE
        page_users = all_users[start:start + ITEMS_PER_PAGE]

        text = f"👥 **Registered Users (Page {page + 1}/{total_pages})**\n\n"
        buttons = []
        for u in page_users:
            status_icon = "💎" if u.get("status") == "Approved" else "⏳"
            btn_text = f"{status_icon} {u['name']} ({u['stu_id']})"
            buttons.append([Button.inline(btn_text, f"usr_det_{u['id']}".encode())])

        nav = []
        if page > 0:
            nav.append(Button.inline("◀️ Prev", f"mgmt_users_{page - 1}".encode()))
        if page < total_pages - 1:
            nav.append(Button.inline("Next ▶️", f"mgmt_users_{page + 1}".encode()))
        if nav:
            buttons.append(nav)

        buttons.append([Button.inline("◀️ Main Menu", b"mgmt_main")])
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"mgmt_approved_(\d+)"))
    async def cb_approved(event):
        if event.sender_id != ADMIN_ID:
            return
        page = int(event.pattern_match.group(1))
        approved_users = [u for u in db["users"].values() if u.get("status") == "Approved"]
        total = len(approved_users)

        if total == 0:
            await event.edit("ℹ️ No verified members yet.", buttons=[Button.inline("◀️ Back", b"mgmt_main")])
            return

        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        start = page * ITEMS_PER_PAGE
        page_users = approved_users[start:start + ITEMS_PER_PAGE]

        text = f"💎 **Verified Members (Page {page + 1}/{total_pages})**\n\n"
        buttons = []
        for u in page_users:
            btn_text = f"✅ {u['name']} [{u['tier']}]"
            buttons.append([Button.inline(btn_text, f"usr_det_{u['id']}".encode())])

        nav = []
        if page > 0:
            nav.append(Button.inline("◀️ Prev", f"mgmt_approved_{page - 1}".encode()))
        if page < total_pages - 1:
            nav.append(Button.inline("Next ▶️", f"mgmt_approved_{page + 1}".encode()))
        if nav:
            buttons.append(nav)

        buttons.append([Button.inline("◀️ Main Menu", b"mgmt_main")])
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"usr_det_(\d+)"))
    async def cb_usr_detail(event):
        if event.sender_id != ADMIN_ID:
            return
        uid_str = event.pattern_match.group(1).decode()
        u = db["users"].get(uid_str)
        if not u:
            await event.answer("User record not found.", alert=True)
            return

        uname = f"@{u['username']}" if u.get("username") else "None"
        text = (
            f"👤 **Student Profile Card**\n\n"
            f"• **Name:** {u['name']}\n"
            f"• **Telegram ID:** `{u['id']}`\n"
            f"• **Username:** {uname}\n"
            f"• **Student ID:** `{u['stu_id']}`\n"
            f"• **Password:** `{u['password']}`\n"
            f"• **Tier:** `{u.get('tier', 'None')}`\n"
            f"• **Status:** `{u.get('status', 'Pending')}`"
        )
        buttons = [
            [
                Button.inline("💎 Full Access", f"set_tier_{u['id']}_Full Access".encode()),
                Button.inline("📚 Lectures Only", f"set_tier_{u['id']}_Lectures Only".encode())
            ],
            [Button.inline("🚫 Revoke Access", f"set_tier_{u['id']}_Revoke".encode())],
            [Button.inline("◀️ Back to Users", b"mgmt_users_0")]
        ]
        await event.edit(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=r"set_tier_(\d+)_(.+)"))
    async def cb_set_tier(event):
        if event.sender_id != ADMIN_ID:
            return
        uid_str = event.pattern_match.group(1).decode()
        action = event.pattern_match.group(2).decode()
        u = db["users"].get(uid_str)
        if not u:
            await event.answer("User not found.", alert=True)
            return

        if action == "Revoke":
            u["tier"] = "None"
            u["status"] = "Pending"
            await event.answer("Access revoked.", alert=True)
        else:
            u["tier"] = action
            u["status"] = "Approved"
            await event.answer(f"Updated to {action}!", alert=True)

        save_db(db)
        await cb_usr_detail(event)

    @client.on(events.CallbackQuery(pattern=b"mgmt_stats"))
    async def cb_stats(event):
        if event.sender_id != ADMIN_ID:
            return
        total = len(db["users"])
        approved = sum(1 for u in db["users"].values() if u.get("status") == "Approved")
        text = (
            "📊 **Current System Statistics**\n\n"
            f"👥 **Total Registered Candidates:** `{total}`\n"
            f"💎 **Active Verified Members:** `{approved}`\n"
            f"⏳ **Pending Verification:** `{total - approved}`"
        )
        buttons = [[Button.inline("◀️ Back", b"mgmt_main")]]
        await event.edit(text, buttons=buttons)

# ================= ASYNC RUNNER =================
async def main():
    logger.info("Initializing bot cluster...")
    active_clients = []

    for key, token in BOT_TOKENS.items():
        if not token:
            logger.warning(f"Skipping {BOT_NAMES[key]}: Token not provided in environment.")
            continue

        session_name = f"sess_{key}"
        try:
            client = TelegramClient(session_name, API_ID, API_HASH)
            await client.start(bot_token=token)
            me = await client.get_me()
            logger.info(f"✅ {BOT_NAMES[key]} connected successfully as @{me.username}")

            if key == "mgmt":
                attach_mgmt_handlers(client)
            else:
                attach_study_handlers(client, BOT_NAMES[key])

            active_clients.append(client)
        except Exception as err:
            logger.error(f"❌ Failed to start {BOT_NAMES[key]}: {err}")

    if not active_clients:
        logger.critical("No bots were started! Please check your Render Environment Variables.")
        sys.exit(1)

    logger.info(f"🚀 Cluster online ({len(active_clients)} active bots). Admin ID: {ADMIN_ID}")
    await asyncio.gather(*(c.run_until_disconnected() for c in active_clients))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Service stopped.")
