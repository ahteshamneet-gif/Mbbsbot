# Run ONCE on your own computer:  pip install telethon  &&  python gen_session.py
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID: "))
api_hash = input("API_HASH: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as c:
    print("\nSESSION_STRING (put in Render env, keep it secret):\n")
    print(c.session.save())
