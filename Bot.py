import os
import sys
import json
import logging
import asyncio
from telethon import TelegramClient, events, Button

# ================= LOGGING CONFIGURATION =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MbbsMultiBot")

# ================= SECURE ENVIRONMENT VARIABLES =================
API_ID = int(os.environ.get("API_ID", "27202302"))
API_HASH = os.environ.get("API_HASH", "2c4ec1bf4ec24190b2964fcb309605d3")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8417145295"))
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/")

# 4 Study Bots + 1 Management Bot tokens from Render
BOT_TOKEN_MGMT  = os.environ.get("BOT_TOKEN_MGMT", "")
BOT_TOKEN_YEAR1 = os.environ.get("BOT_TOKEN_YEAR1", "")
BOT_TOKEN_YEAR2 = os.environ.get("BOT_TOKEN_YEAR2", "")
BOT_TOKEN_YEAR3 = os.environ.get("BOT_TOKEN_YEAR3", "")
BOT_TOKEN_YEAR4 = os.environ.get("BOT_TOKEN_YEAR4", "")

# Verify at least the management bot token is present
if not BOT_TOKEN_MGMT:
    logger.error("❌ CRITICAL: BOT_TOKEN_MGMT is not defined in Render Environment Variables!")

# ================= PERSISTENT USER DATABASE =================
DATA_FILE = "users_db.json"

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {DATA_FILE}: {e}")
    return {"users": {}}

def save_db(db):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {DATA_FILE}: {e}")

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
            "tier": "None",       # "Full Access", "Lectures Only", or "None"
            "status": "Pending"   # "Approved" or "Pending"
        }
        save_db(db)
    else:
        # Update details in case of username change
        if username:
            db["users"][uid_str]["username"] = username
        if first_name:
            db["users"][uid_str]["name"] = first_name
        save_db(db)
    return db["users"][uid_str]

# ================= CLIENT INITIALIZATIONS =================
clients = []

# 1. Management Bot Client
mgmt_client = TelegramClient("mgmt_session", API_ID, API_HASH)
clients.append((mgmt_client, BOT_TOKEN_MGMT, "Management Bot"))

# 2. 1st Year MBBS Bot Client
if BOT_TOKEN_YEAR1:
    year1_client = TelegramClient("year1_session", API_ID, API_HASH)
    clients.append((year1_client, BOT_TOKEN_YEAR1, "1st Year MBBS Bot"))

# 3. 2nd Year MBBS Bot Client
if BOT_TOKEN_YEAR2:
    year2_client = TelegramClient("year2_session", API_ID, API_HASH)
    clients.append((year2_client, BOT_TOKEN_YEAR2, "2nd Year MBBS Bot"))

# 4. 3rd Year MBBS Bot Client
if BOT_TOKEN_YEAR3:
    year3_client = TelegramClient("year3_session", API_ID, API_HASH)
    clients.append((year3_client, BOT_TOKEN_YEAR3, "3rd Year MBBS Bot"))

# 5. 4th Year MBBS Bot Client
if BOT_TOKEN_YEAR4:
    year4_client = TelegramClient("year4_session", API_ID, API_HASH)
    clients.append((year4_client, BOT_TOKEN_YEAR4, "4th Year MBBS Bot"))

# ================= HELPER FUNCTIONS =================
def build_login_url(user_data):
    uid = user_data["stu_id"]
    key = user_data["password"]
    name = user_data["name"]
    # Supplies both search parameter and hash fragment for reliable web app auto-login
    return f"{WEB_APP_URL}?uid={uid}&key={key}&name={name}#uid={uid}&key={key}&name={name}"

# ================= STUDY BOTS HANDLERS (YEAR 1 - 4) =================
def setup_study_bot_handlers(client, bot_name):
    @client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        sender = await event.get_sender()
        user_info = get_or_create_user(sender.id, sender.username, sender.first_name)

        # Strictly check for verified Full Access
        is_full_access = (user_info.get("status") == "Approved" and "Full" in user_info.get("tier", ""))

        if is_full_access or sender.id == ADMIN_ID:
            login_link = build_login_url(user_info)
            text = (
                f"🩺 **Welcome to {bot_name}**\n\n"
                f"👤 **Candidate:** {user_info['name']}\n"
                f"🆔 **Student ID:** `{user_info['stu_id']}`\n"
                f"🔑 **Password:** `{user_info['password']}`\n"
                f"💎 **Access Tier:** `{user_info['tier']}`\n\n"
                f"Your account is verified. Click below to launch your CBT Question Bank portal:"
            )
            buttons = [
                [Button.url("🚀 Launch MBBS CBT Q-Bank", login_link)],
                [Button.url("💬 Support & Inquiries", "https://t.me/Nothing_0786")]
            ]
        else:
            text = (
                f"🔒 **{bot_name} — Restricted Access**\n\n"
                f"Hello {user_info['name']},\n"
                f"This bot and its associated Computer-Based Testing Q-Bank are restricted to paid subscribers.\n\n"
                f"🆔 **Registered ID:** `{user_info['stu_id']}`\n"
                f"⚠️ **Status:** Account Pending Approval\n\n"
                f"Contact the administrator to activate your seat."
            )
            buttons = [
                [Button.url("💎 Get Full Subscription", "https://t.me/Nothing_0786")]
            ]

        await event.respond(text, buttons=buttons)

# Register handlers on all available study bots
for cl, token, bname in clients:
    if bname != "Management Bot":
        setup_study_bot_handlers(cl, bname)

# ================= MANAGEMENT BOT HANDLERS =================
ITEMS_PER_PAGE = 8

@mgmt_client.on(events.NewMessage(pattern="/start"))
async def mgmt_start(event):
    sender = await event.get_sender()
    if sender.id != ADMIN_ID:
        await event.respond("⛔ **Access Denied:** Administrator command hub only.")
        return

    text = (
        "👑 **MBBS Management Bot — Admin Hub**\n\n"
        "Select an option below to manage students, approve memberships, and track access:"
    )
    buttons = [
        [Button.inline("👥 Registered Users", b"mgmt_users_0"), Button.inline("💎 Verified Members", b"mgmt_approved_0")],
        [Button.inline("📊 System Stats", b"mgmt_stats"), Button.url("🌐 Open Q-Bank", WEB_APP_URL)]
    ]
    await event.respond(text, buttons=buttons)

@mgmt_client.on(events.CallbackQuery(pattern=b"mgmt_main"))
async def cb_mgmt_main(event):
    if event.sender_id != ADMIN_ID:
        return
    text = (
        "👑 **MBBS Management Bot — Admin Hub**\n\n"
        "Select an option below to manage students, approve memberships, and track access:"
    )
    buttons = [
        [Button.inline("👥 Registered Users", b"mgmt_users_0"), Button.inline("💎 Verified Members", b"mgmt_approved_0")],
        [Button.inline("📊 System Stats", b"mgmt_stats"), Button.url("🌐 Open Q-Bank", WEB_APP_URL)]
    ]
    await event.edit(text, buttons=buttons)

@mgmt_client.on(events.CallbackQuery(pattern=r"mgmt_users_(\d+)"))
async def cb_mgmt_users(event):
    if event.sender_id != ADMIN_ID:
        return

    page = int(event.pattern_match.group(1))
    all_users = list(db["users"].values())
    total_users = len(all_users)

    if total_users == 0:
        await event.edit("ℹ️ No registered users in the database.", buttons=[Button.inline("◀️ Back", b"mgmt_main")])
        return

    total_pages = (total_users + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_users = all_users[start:end]

    text = f"👥 **Registered Users (Page {page + 1}/{total_pages})**\n\n"
    buttons = []

    for u in page_users:
        uname = f"@{u['username']}" if u.get("username") else "No Username"
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

@mgmt_client.on(events.CallbackQuery(pattern=r"mgmt_approved_(\d+)"))
async def cb_mgmt_approved(event):
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
    end = start + ITEMS_PER_PAGE
    page_users = approved_users[start:end]

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

@mgmt_client.on(events.CallbackQuery(pattern=r"usr_det_(\d+)"))
async def cb_user_detail(event):
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
        [
            Button.inline("🚫 Revoke Access", f"set_tier_{u['id']}_Revoke".encode())
        ],
        [Button.inline("◀️ Back to Users", b"mgmt_users_0")]
    ]
    await event.edit(text, buttons=buttons)

@mgmt_client.on(events.CallbackQuery(pattern=r"set_tier_(\d+)_(.+)"))
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
    # Refresh detail display
    await cb_user_detail(event)

@mgmt_client.on(events.CallbackQuery(pattern=b"mgmt_stats"))
async def cb_stats(event):
    if event.sender_id != ADMIN_ID:
        return

    total = len(db["users"])
    approved = sum(1 for u in db["users"].values() if u.get("status") == "Approved")
    pending = total - approved

    text = (
        "📊 **Current System Statistics**\n\n"
        f"👥 **Total Registered Candidates:** `{total}`\n"
        f"💎 **Active Verified Members:** `{approved}`\n"
        f"⏳ **Pending Verification:** `{pending}`\n"
        f"🤖 **Connected Bots:** `{len(clients)}`"
    )
    buttons = [[Button.inline("◀️ Back", b"mgmt_main")]]
    await event.edit(text, buttons=buttons)

# ================= MAIN STARTUP RUNNER =================
async def main():
    logger.info("==================================================")
    logger.info("🚀 Starting MBBS Multi-Bot Cluster on Render...")
    logger.info("==================================================")

    for client, token, name in clients:
        try:
            logger.info(f"⏳ Connecting {name}...")
            await client.start(bot_token=token)
            me = await client.get_me()
            logger.info(f"✅ {name} online as @{me.username}")
        except Exception as e:
            logger.error(f"❌ Failed to start {name}: {e}")

    logger.info("==================================================")
    logger.info(f"👑 Cluster operational. Admin ID: {ADMIN_ID}")
    logger.info("==================================================")

    # Keep clients running asynchronously
    await asyncio.gather(*(c[0].run_until_disconnected() for c in clients))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bots shut down gracefully.")
