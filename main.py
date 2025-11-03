import imaplib
import asyncio
import email
from email.header import decode_header
from email.utils import parseaddr
import html
import aiogram
import aiohttp
from loguru import logger
from . import config
from appwrite.functions import AppwriteFunction

bot = aiogram.Bot(token=config.TELEGRAM_BOT_TOKEN)


def connect_to_mailbox():
    """
    Подключается к Яндекс.Почте через IMAP, используя пароль приложения.
    """
    try:
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
        mail.login(config.EMAIL_LOGIN, config.EMAIL_PASSWORD)
        mail.select("inbox")
        return mail
    except imaplib.IMAP4.error as e:
        logger.error(f"❌ Ошибка аутентификации в IMAP: {e}")
        return None


def fetch_unread_emails():
    mail = connect_to_mailbox()
    if not mail:
        return []

    all_email_ids = set()  # набор всех непрочитанных ID

    for sender in config.SENDER_EMAILS:
        status, messages = mail.search(None, f'(UNSEEN FROM "{sender}")')
        if status == "OK":
            email_ids = messages[0].split()
            for eid in email_ids:
                all_email_ids.add(eid)
        else:
            logger.warning(f"Ошибка поиска писем от {sender}. Пропускаем...")

    unread_emails = []

    for email_id in all_email_ids:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        if status != "OK":
            continue

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                subject, encoding = decode_header(msg["Subject"])[0]
                subject = (
                    subject.decode(encoding or "utf-8")
                    if isinstance(subject, bytes)
                    else subject
                )

                from_email = msg.get("From")
                sender_name, sender_email = parseaddr(from_email)

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type == "text/plain":
                            body = part.get_payload(decode=True).decode(
                                "utf-8", errors="ignore"
                            )
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                unread_emails.append(
                    {"subject": subject, "from": sender_email, "body": body[:500]}
                )

        # Помечаем письмо как прочитанное
        mail.store(email_id, "+FLAGS", "\\Seen")

    mail.close()
    mail.logout()
    return unread_emails


async def send_telegram_message(text):
    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        safe_text = html.escape(text)

        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": safe_text,
            "parse_mode": "HTML",
        }
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Ошибка при отправке в Telegram: {await resp.text()}")


async def check_new_emails():
    unread_emails = fetch_unread_emails()
    if not unread_emails:
        logger.info("Нет новых писем.")
        return

    for email_data in unread_emails:
        text = (
            f"📩 Новое письмо от {html.escape(email_data['from'])}\n"
            f"Тема: {html.escape(email_data['subject'])}\n\n"
            f"Текст: {html.escape(email_data['body'])}"
        )
        await send_telegram_message(text)


def main(context: AppwriteFunction):
    context.log("Running main function...")
    asyncio.run(check_new_emails())
    context.log("Main function finished.")
