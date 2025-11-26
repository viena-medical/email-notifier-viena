import email
from email.header import decode_header
from email.utils import parseaddr
import html
import datetime
import aiohttp
import imaplib
from . import config

def connect_to_mailbox(context):
    """
    Подключается к Яндекс.Почте через IMAP, используя пароль приложения.
    """
    try:
        context.log(f"🔌 Подключение к IMAP серверу {config.IMAP_SERVER}:{config.IMAP_PORT}")
        imap = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
        context.log("🔐 Выполнение аутентификации...")
        imap.login(config.EMAIL_LOGIN, config.EMAIL_PASSWORD)
        context.log("📁 Выбор папки inbox...")
        imap.select("inbox")
        context.log("✅ Успешное подключение к почтовому ящику")
        return imap
    except Exception as e:
        context.log(f"❌ Ошибка при подключении к IMAP: {e}")
        return None


def fetch_unread_emails(context):
    context.log("🔍 Начало поиска непрочитанных писем")
    imap = connect_to_mailbox(context)
    if not imap:
        context.error("❌ Не удалось подключиться к почтовому ящику")
        return []

    all_email_ids = set()  # набор всех непрочитанных ID
    context.log(f"📋 Настроенные отправители: {config.SENDER_EMAILS}")

    # Calculate date 24 hours ago for filtering recent emails
    date_24h_ago = datetime.datetime.now() - datetime.timedelta(hours=72)
    date_str = date_24h_ago.strftime("%d-%b-%Y")

    try:
        for sender in config.SENDER_EMAILS:
            context.log(f"🔎 Поиск непрочитанных писем от: {sender}")
            search_criteria = f'(UNSEEN FROM {sender} SINCE {date_str})'
            context.log(f"🔍 Критерий поиска: {search_criteria}")
            status, data = imap.search(None, search_criteria)
            if status == 'OK':
                email_ids = data[0].decode().split()
                context.log(f"📧 Найдено {len(email_ids)} непрочитанных писем от {sender}")
                for eid in email_ids:
                    all_email_ids.add(eid)
            else:
                context.error(f"❌ Ошибка поиска писем от {sender}: status={status}, data={data}")

        context.log(f"📊 Всего уникальных непрочитанных писем: {len(all_email_ids)}")
        unread_emails = []

        for email_id in all_email_ids:
            context.log(f"📨 Обработка письма ID: {email_id}")
            status, data = imap.fetch(email_id, "(BODY[])")
            if status != "OK":
                context.error(f"❌ Ошибка получения письма {email_id}")
                continue

            # Extract message data
            if not data:
                context.error(f"❌ Нет данных для письма {email_id}")
                continue
            msg_data = data[0][1]
            if isinstance(msg_data, bytes):
                pass
            else:
                msg_data = bytes(msg_data)

            msg = email.message_from_bytes(msg_data)

            # Safely decode subject
            subject_header = msg.get("Subject")
            if subject_header:
                subject, encoding = decode_header(subject_header)[0]
                subject = (
                    subject.decode(encoding or "utf-8")
                    if isinstance(subject, bytes)
                    else subject
                )
            else:
                subject = "Без темы"

            from_email = msg.get("From")
            sender_name, sender_email = parseaddr(from_email or "")
            context.log(f"📧 Письмо от: {sender_name} <{sender_email}>, тема: {subject[:50]}...")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="ignore")
                        break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")

            unread_emails.append(
                {"subject": subject, "from": sender_email, "body": body[:500]}
            )
            context.log(f"✅ Письмо обработано: {subject[:30]}...")

            # Помечаем письмо как прочитанное
            imap.store(email_id, "+FLAGS", "\\Seen")
            context.log(f"👁️ Письмо {email_id} помечено как прочитанное")

        context.log(f"🔚 Завершение поиска писем. Обработано: {len(unread_emails)} писем")
        return unread_emails

    finally:
        imap.close()
        imap.logout()


async def send_telegram_message(context, text):
    context.log("📤 Отправка сообщения в Telegram")
    context.log(f"Текст сообщения: {text[:100]}...")

    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        safe_text = html.escape(text)

        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": safe_text,
            "parse_mode": "HTML",
        }

        try:
            context.log("Выполнение HTTP запроса к Telegram API")
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    context.log("✅ Сообщение успешно отправлено в Telegram")
                    # context.log(f"Ответ Telegram API: {await resp.text()}")
                else:
                    error_text = await resp.text()
                    context.error(f"❌ Ошибка при отправке в Telegram (статус {resp.status}): {error_text}")
        except Exception as e:
            context.error(f"❌ Исключение при отправке в Telegram: {e}")


async def check_new_emails(context):
    context.log("🔄 Начало проверки новых писем")
    unread_emails = fetch_unread_emails(context)

    if not unread_emails:
        context.log("📭 Нет новых писем для обработки")
        return

    context.log(f"📨 Найдено {len(unread_emails)} новых писем для отправки в Telegram")

    # Rate limiting: max 10 messages per second
    last_send_time = None

    for i, email_data in enumerate(unread_emails):
        context.log(f"📤 Обработка письма {i}/{len(unread_emails)}: {email_data['subject'][:30]}...")

        text = (
            f"📩 Новое письмо от {html.escape(email_data['from'])}\n"
            f"Тема: {html.escape(email_data['subject'])}\n\n"
            f"Текст: {html.escape(email_data['body'])}"
        )

        # Enforce rate limit
        current_time = time.time()
        if last_send_time is not None:
            elapsed = current_time - last_send_time
            if elapsed < 0.1:
                sleep_time = 0.1 - elapsed
                context.log(f"⏱️ Rate limiting: sleeping for {sleep_time:.2f} seconds")
                await asyncio.sleep(sleep_time)
        last_send_time = time.time()

        try:
            await send_telegram_message(context, text)
            context.log(f"✅ Письмо {i} успешно отправлено в Telegram")
        except Exception as e:
            context.error(f"❌ Ошибка отправки письма {i} в Telegram: {e}")

    context.log(f"🎉 Завершена обработка {len(unread_emails)} писем")


async def main(context):
    context.log("🚀 Запуск основной функции email-notifier")

    try:
        await check_new_emails(context)
        context.log("✅ Основная функция выполнена успешно")
        return context.res.json({
            "success": True
        }, 200)
    except Exception as e:
        context.error(f"❌ Критическая ошибка в основной функции: {e}")
        return context.res.json({
            "success": False
        }, 500)
