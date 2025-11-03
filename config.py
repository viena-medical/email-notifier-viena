import os

IMAP_SERVER = os.getenv("IMAP_SERVER", "")
IMAP_PORT = os.getenv("IMAP_PORT", "")
EMAIL_LOGIN = os.getenv("EMAIL_LOGIN", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

raw_senders = os.getenv("SENDER_EMAILS", "")
SENDER_EMAILS = [s.strip() for s in raw_senders.split(",") if s.strip()]
