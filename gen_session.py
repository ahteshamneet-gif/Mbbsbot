!pip install telethon
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
api_id = 37864520
api_hash = "d92bf252ab0a7835d2639d49920f714a"
with TelegramClient(StringSession(), api_id, api_hash) as c:
    print(c.session.save())
