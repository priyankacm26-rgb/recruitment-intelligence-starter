import os
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .gmail_preview_service import (
    get_gmail_service,
    get_headers,
    collect_parts,
    decode_attachment,
)
from .resume_preview import preview_resume

TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))
SUPPORTED_RESUME_EXTENSIONS = {".pdf", ".docx"}


def get_today_email_analytics():
    """
    Read today's Gmail inbox messages and preview supported resume attachments.

    Read-only: this function does not insert, update, or delete database records.
    Counts email messages separately from resume attachment files.
    """
    api = get_gmail_service()

    now = datetime.now(TIMEZONE)
    day_start = datetime.combine(now.date(), time.min, tzinfo=TIMEZONE)
    next_day_start = day_start + timedelta(days=1)

    # Gmail accepts Unix timestamps for after: and before: query operators.
    query = (
        f"after:{int(day_start.timestamp())} "
        f"before:{int(next_day_start.timestamp())} in:inbox"
    )

    message_refs = []
    page_token = None

    while True:
        params = {
            "userId": "me",
            "q": query,
            "maxResults": 100,
        }
        if page_token:
            params["pageToken"] = page_token

        response = api.users().messages().list(**params).execute()
        message_refs.extend(response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    resume_previews = []
    errors = []
    message_summaries = []

    for message_ref in message_refs:
        message_id = message_ref["id"]

        try:
            message = (
                api.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            headers = get_headers(message)
            payload = message.get("payload", {})
            sender = headers.get("from", "")
            subject = headers.get("subject", "")

            message_summaries.append({
                "message_id": message_id,
                "sender": sender,
                "subject": subject,
            })

            for part in collect_parts(payload):
                filename = Path(part.get("filename", "")).name
                if Path(filename).suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
                    continue

                body = part.get("body", {})
                encoded_data = body.get("data", "")

                if body.get("attachmentId"):
                    attachment = (
                        api.users()
                        .messages()
                        .attachments()
                        .get(
                            userId="me",
                            messageId=message_id,
                            id=body["attachmentId"],
                        )
                        .execute()
                    )
                    encoded_data = attachment.get("data", "")

                raw = decode_attachment(encoded_data)
                if not raw:
                    errors.append({
                        "message_id": message_id,
                        "filename": filename,
                        "error": "Attachment had no downloadable data.",
                    })
                    continue

                try:
                    details = preview_resume(filename, raw)
                    resume_previews.append({
                        "message_id": message_id,
                        "sender": sender,
                        "subject": subject,
                        **details,
                    })
                except Exception as exc:
                    errors.append({
                        "message_id": message_id,
                        "filename": filename,
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    })

        except Exception as exc:
            errors.append({
                "message_id": message_id,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            })

    return {
        "date": now.date().isoformat(),
        "timezone": str(TIMEZONE),
        "emails_received": len(message_refs),
        "resume_attachments_previewed": len(resume_previews),
        "messages": message_summaries,
        "resumes": resume_previews,
        "errors": errors,
        "database_changed": False,
    }
