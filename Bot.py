import os
import sys
import json
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================= LOGGING SETUP =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MbbsMultiBot")

# ================= SECURE ENVIRONMENT VARIABLES =================
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8417145295"))
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://ahteshamneet-gif.github.io/Mbbsbot/").strip()

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

# ================= STUDY BOTS HANDLER =================
def create_study_start_handler(bot_name):
    async def study_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        sender = update.effective_user
        user_info = get_or_create_user(sender.id, sender.username, sender.first_name)
        is_full_access = (user_info.get("status") == "Approved" and "Full" in user_info.get("tier", ""))

        if is_full_access or sender.id == ADMIN_ID:
            login_link = build_login_url(user_info)
            text = (
                f"🩺 *Welcome to {bot_name}*\n\n"
                f"👤 *Candidate:* {user_info['name']}\n"
                f"🆔 *Student ID:* `{user_info['stu_id']}`\n"
                f"🔑 *Password:* `{user_info['password']}`\n"
                f"💎 *Access Tier:* `{user_info['tier']}`\n\n"
                f"Your account is verified. Click below to launch your CBT Question Bank portal:"
            )
            keyboard = [
                [InlineKeyboardButton("🚀 Launch MBBS CBT Q-Bank", url=login_link)],
                [InlineKeyboardButton("💬 Support & Inquiries", url="https://t.me/Nothing_0786")]
            ]
        else:
            text = (
                f"🔒 *{bot_name} — Restricted Access*\n\n"
                f"Hello {user_info['name']},\n"
                f"This bot and its associated Computer-Based Testing Q-Bank are restricted to enrolled students.\n\n"
                f"🆔 *Registered ID:* `{user_info['stu_id']}`\n"
                f"⚠️ *Status:* Account Pending Approval\n\n"
                f"Contact the administrator to activate your seat."
            )
            keyboard = [
                [InlineKeyboardButton("💎 Get Full Subscription", url="https://t.me/Nothing_0786")]
            ]

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    return study_start

# ================= MANAGEMENT BOT HANDLERS =================
ITEMS_PER_PAGE = 8

async def mgmt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    if sender.id != ADMIN_ID:
        await update.message.reply_text("⛔ *Access Denied:* Administrator hub only.", parse_mode="Markdown")
        return

    text = (
        "👑 *MBBS Management Bot — Admin Hub*\n\n"
        "Select an option to manage students, approve memberships, and track access:"
    )
    keyboard = [
        [
            InlineKeyboardButton("👥 Registered Users", callback_data="mgmt_users_0"),
            InlineKeyboardButton("💎 Verified Members", callback_data="mgmt_approved_0")
        ],
        [
            InlineKeyboardButton("📊 System Stats", callback_data="mgmt_stats"),
            InlineKeyboardButton("🌐 Open Q-Bank", url=WEB_APP_URL)
        ]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_mgmt_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    text = (
        "👑 *MBBS Management Bot — Admin Hub*\n\n"
        "Select an option to manage students, approve memberships, and track access:"
    )
    keyboard = [
        [
            InlineKeyboardButton("👥 Registered Users", callback_data="mgmt_users_0"),
            InlineKeyboardButton("💎 Verified Members", callback_data="mgmt_approved_0")
        ],
        [
            InlineKeyboardButton("📊 System Stats", callback_data="mgmt_stats"),
            InlineKeyboardButton("🌐 Open Q-Bank", url=WEB_APP_URL)
        ]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_mgmt_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    page = int(query.data.split("_")[2])
    all_users = list(db["users"].values())
    total = len(all_users)

    if total == 0:
        await query.edit_message_text(
            "ℹ️ No registered users found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="mgmt_main")]])
        )
        return

    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = page * ITEMS_PER_PAGE
    page_users = all_users[start:start + ITEMS_PER_PAGE]

    text = f"👥 *Registered Users (Page {page + 1}/{total_pages})*\n\n"
    keyboard = []
    for u in page_users:
        status_icon = "💎" if u.get("status") == "Approved" else "⏳"
        keyboard.append([InlineKeyboardButton(f"{status_icon} {u['name']} ({u['stu_id']})", callback_data=f"usr_det_{u['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"mgmt_users_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"mgmt_users_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("◀️ Main Menu", callback_data="mgmt_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_mgmt_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    page = int(query.data.split("_")[2])
    approved_users = [u for u in db["users"].values() if u.get("status") == "Approved"]
    total = len(approved_users)

    if total == 0:
        await query.edit_message_text(
            "ℹ️ No verified members yet.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="mgmt_main")]])
        )
        return

    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = page * ITEMS_PER_PAGE
    page_users = approved_users[start:start + ITEMS_PER_PAGE]

    text = f"💎 *Verified Members (Page {page + 1}/{total_pages})*\n\n"
    keyboard = []
    for u in page_users:
        keyboard.append([InlineKeyboardButton(f"✅ {u['name']} [{u['tier']}]", callback_data=f"usr_det_{u['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"mgmt_approved_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"mgmt_approved_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("◀️ Main Menu", callback_data="mgmt_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_usr_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    uid_str = query.data.split("_")[2]
    u = db["users"].get(uid_str)
    if not u:
        await query.answer("User record not found.", show_alert=True)
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
    keyboard = [
        [
            InlineKeyboardButton("💎 Full Access", callback_data=f"tier_{u['id']}_Full Access"),
            InlineKeyboardButton("📚 Lectures Only", callback_data=f"tier_{u['id']}_Lectures Only")
        ],
        [InlineKeyboardButton("🚫 Revoke Access", callback_data=f"tier_{u['id']}_Revoke")],
        [InlineKeyboardButton("◀️ Back to Users", callback_data="mgmt_users_0")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_set_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return

    parts = query.data.split("_", 2)
    uid_str = parts[1]
    action = parts[2]
    u = db["users"].get(uid_str)

    if not u:
        await query.answer("User not found.", show_alert=True)
        return

    if action == "Revoke":
        u["tier"] = "None"
        u["status"] = "Pending"
        await query.answer("Access revoked.", show_alert=True)
    else:
        u["tier"] = action
        u["status"] = "Approved"
        await query.answer(f"Updated to {action}!", show_alert=True)

    save_db(db)

    # Re-render updated user profile
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
    keyboard = [
        [
            InlineKeyboardButton("💎 Full Access", callback_data=f"tier_{u['id']}_Full Access"),
            InlineKeyboardButton("📚 Lectures Only", callback_data=f"tier_{u['id']}_Lectures Only")
        ],
        [InlineKeyboardButton("🚫 Revoke Access", callback_data=f"tier_{u['id']}_Revoke")],
        [InlineKeyboardButton("◀️ Back to Users", callback_data="mgmt_users_0")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    total = len(db["users"])
    approved = sum(1 for u in db["users"].values() if u.get("status") == "Approved")
    text = (
        "📊 *Current System Statistics*\n\n"
        f"👥 *Total Registered Candidates:* `{total}`\n"
        f"💎 *Active Verified Members:* `{approved}`\n"
        f"⏳ *Pending Verification:* `{total - approved}`"
    )
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="mgmt_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ================= MULTI-APP BOOTSTRAPPER =================
async def main():
    logger.info("Initializing Bot applications...")
    apps = []

    for key, token in BOT_TOKENS.items():
        if not token:
            logger.warning(f"Skipping {BOT_NAMES[key]}: Token missing in environment.")
            continue

        try:
            app = ApplicationBuilder().token(token).build()

            if key == "mgmt":
                app.add_handler(CommandHandler("start", mgmt_start))
                app.add_handler(CallbackQueryHandler(cb_mgmt_main, pattern="^mgmt_main$"))
                app.add_handler(CallbackQueryHandler(cb_mgmt_users, pattern="^mgmt_users_"))
                app.add_handler(CallbackQueryHandler(cb_mgmt_approved, pattern="^mgmt_approved_"))
                app.add_handler(CallbackQueryHandler(cb_usr_detail, pattern="^usr_det_"))
                app.add_handler(CallbackQueryHandler(cb_set_tier, pattern="^tier_"))
                app.add_handler(CallbackQueryHandler(cb_stats, pattern="^mgmt_stats$"))
            else:
                app.add_handler(CommandHandler("start", create_study_start_handler(BOT_NAMES[key])))

            apps.append((app, BOT_NAMES[key]))
            logger.info(f"Registered {BOT_NAMES[key]}")
        except Exception as err:
            logger.error(f"Error initializing {BOT_NAMES[key]}: {err}")

    if not apps:
        logger.critical("No valid bots found. Please configure bot tokens in Render.")
        sys.exit(1)

    for app, name in apps:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info(f"✅ {name} polling active")

    logger.info(f"🚀 Cluster online ({len(apps)} bots active). Admin ID: {ADMIN_ID}")

    # Keep running indefinitely
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bots shut down.")
