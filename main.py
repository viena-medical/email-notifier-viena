import imaplib
import asyncio
import email
from email.header import decode_header
from email.utils import parseaddr
import html
import aiohttp
from loguru import logger
from . import config

def connect_to_mailbox(context):
    """
    Подключается к Яндекс.Почте через IMAP, используя пароль приложения.
    """
    try:
        context.log(f"🔌 Подключение к IMAP серверу {config.IMAP_SERVER}:{config.IMAP_PORT}")
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT, timeout=10)
        context.log("🔐 Выполнение аутентификации...")
        mail.login(config.EMAIL_LOGIN, config.EMAIL_PASSWORD)
        context.log("📁 Выбор папки inbox...")
        mail.select("inbox")
        context.log("✅ Успешное подключение к почтовому ящику")
        return mail
    except imaplib.IMAP4.error as e:
        context.log(f"❌ Ошибка аутентификации в IMAP: {e}")
        logger.error(f"IMAP authentication failed: {e}")
        return None
    except Exception as e:
        context.log(f"❌ Неожиданная ошибка при подключении к IMAP: {e}")
        return None


def fetch_unread_emails(context):
    context.log("🔍 Начало поиска непрочитанных писем")
    mail = connect_to_mailbox(context)
    if not mail:
        context.log("❌ Не удалось подключиться к почтовому ящику")
        return []

    all_email_ids = set()  # набор всех непрочитанных ID
    context.log(f"📋 Настроенные отправители: {config.SENDER_EMAILS}")

    for sender in config.SENDER_EMAILS:
        context.log(f"🔎 Поиск непрочитанных писем от: {sender}")
        status, messages = mail.search(None, f'(UNSEEN FROM "{sender}")')
        if status == "OK":
            email_ids = messages[0].split()
            context.log(f"📧 Найдено {len(email_ids)} непрочитанных писем от {sender}")
            for eid in email_ids:
                all_email_ids.add(eid)
        else:
            logger.warning(f"Ошибка поиска писем от {sender}. Пропускаем...")
            context.log(f"⚠️ Ошибка поиска писем от {sender}")

    context.log(f"📊 Всего уникальных непрочитанных писем: {len(all_email_ids)}")
    unread_emails = []

    #for email_id in all_email_ids:
    for email_id in []:
        context.log(f"📨 Обработка письма ID: {email_id}")
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        if status != "OK":
            context.log(f"❌ Ошибка получения письма {email_id}")
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
                context.log(f"📧 Письмо от: {sender_email}, тема: {subject[:50]}...")

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
                context.log(f"✅ Письмо обработано: {subject[:30]}...")

        # Помечаем письмо как прочитанное
        mail.store(email_id, "+FLAGS", "\\Seen")
        context.log(f"👁️ Письмо {email_id} помечено как прочитанное")

    mail.close()
    mail.logout()
    context.log(f"🔚 Завершение поиска писем. Обработано: {len(unread_emails)} писем")
    return unread_emails


async def send_telegram_message(text):
    logger.info("📤 Отправка сообщения в Telegram")
    logger.debug(f"Текст сообщения: {text[:100]}...")

    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        safe_text = html.escape(text)

        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": safe_text,
            "parse_mode": "HTML",
        }

        try:
            logger.debug("Выполнение HTTP запроса к Telegram API")
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info("✅ Сообщение успешно отправлено в Telegram")
                    logger.debug(f"Ответ Telegram API: {await resp.text()}")
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Ошибка при отправке в Telegram (статус {resp.status}): {error_text}")
        except Exception as e:
            logger.error(f"❌ Исключение при отправке в Telegram: {e}")


async def check_new_emails(context):
    context.log("🔄 Начало проверки новых писем")
    unread_emails = fetch_unread_emails(context)

    if not unread_emails:
        context.log("📭 Нет новых писем для обработки")
        return

    context.log(f"📨 Найдено {len(unread_emails)} новых писем для отправки в Telegram")

    for i, email_data in enumerate(unread_emails, 1):
        context.log(f"📤 Обработка письма {i}/{len(unread_emails)}: {email_data['subject'][:30]}...")

        text = (
            f"📩 Новое письмо от {html.escape(email_data['from'])}\n"
            f"Тема: {html.escape(email_data['subject'])}\n\n"
            f"Текст: {html.escape(email_data['body'])}"
        )

        try:
            await send_telegram_message(text)
            context.log(f"✅ Письмо {i} успешно отправлено в Telegram")
        except Exception as e:
            context.log(f"❌ Ошибка отправки письма {i} в Telegram: {e}")
            logger.error(f"Failed to send email {i} to Telegram: {e}")

    context.log(f"🎉 Завершена обработка {len(unread_emails)} писем")


async def main(context):
    context.log("🚀 Запуск основной функции email-notifier")
    logger.info("Appwrite function started")

    try:
        await check_new_emails(context)
        context.log("✅ Основная функция выполнена успешно")
        logger.info("Appwrite function completed successfully")
        return context.res.json({
            "success": True,
            "message": "Email check completed"
        }, 200)
    except Exception as e:
        context.log(f"❌ Критическая ошибка в основной функции: {e}")
        logger.error(f"Critical error in main function: {e}")
        return context.res.json({
            "success": False,
            "error": str(e)
        }, 500)
