
import base64
import os
from pathlib import Path
from email.utils import parseaddr
from datetime import datetime, timezone

from .gmail_service import service as get_gmail_service
from .resume_preview import preview_resume


def decode_attachment(encoded_data):
    """Decode Gmail URL-safe Base64 attachment data."""

    if not encoded_data:
        return b""

    encoded_data += "=" * (-len(encoded_data) % 4)
    return base64.urlsafe_b64decode(encoded_data)


def get_headers(message):
    """Return message headers as a lowercase-key dictionary."""

    return {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }


def collect_parts(part):
    """Collect MIME parts that have filenames."""

    found = []

    if part.get("filename"):
        found.append(part)

    for child in part.get("parts", []) or []:
        found.extend(collect_parts(child))

    return found


def get_received_date(message):
    """Convert Gmail internal timestamp to readable UTC date."""

    timestamp = message.get("internalDate")

    if not timestamp:
        return None

    return datetime.fromtimestamp(
        int(timestamp) / 1000,
        tz=timezone.utc,
    ).isoformat()


def preview_gmail():
    """
    Preview Gmail messages and supported resume attachments.

    This function does not insert, update, or delete candidate records.
    """

    api = get_gmail_service()

    query = os.getenv(
        "GMAIL_QUERY",
        "in:anywhere -in:spam -in:trash",
    )

    max_messages = int(
        os.getenv("GMAIL_PREVIEW_MAX_MESSAGES", "100")
    )

    messages = []
    page_token = None

    print("GMAIL QUERY:", query)

    while len(messages) < max_messages:

        page_size = min(100, max_messages - len(messages))

        response = api.users().messages().list(
            userId="me",
            q=query,
            maxResults=page_size,
            pageToken=page_token,
        ).execute()

        page_messages = response.get("messages", [])
        messages.extend(page_messages)

        page_token = response.get("nextPageToken")

        if not page_token or not page_messages:
            break

    print("GMAIL MESSAGES FOUND:", len(messages))

    results = []
    attachments_checked = 0
    messages_without_attachments = 0

    for ref in messages:

        message_id = ref["id"]

        try:
            message = api.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
            ).execute()

            headers = get_headers(message)

            sender_name, sender_email = parseaddr(
                headers.get("from", "")
            )

            parts = collect_parts(
                message.get("payload", {})
            )

            attachment_metadata = []

            for part in parts:

                filename = Path(part["filename"]).name
                body = part.get("body", {})

                attachment_metadata.append({
                    "filename": filename,
                    "mime_type": part.get("mimeType"),
                    "size_bytes": body.get("size", 0),
                    "is_supported_resume": (
                        Path(filename).suffix.lower()
                        in (".pdf", ".docx")
                    ),
                })

            if not attachment_metadata:
                messages_without_attachments += 1

            email_result = {
                "message_id": message_id,
                "thread_id": message.get("threadId"),
                "sender_name": sender_name,
                "sender": sender_email,
                "subject": headers.get("subject", ""),
                "received_at": get_received_date(message),
                "snippet": message.get("snippet", ""),
                "labels": message.get("labelIds", []),
                "has_attachments": bool(attachment_metadata),
                "attachment_count": len(attachment_metadata),
                "attachments": attachment_metadata,
                "resume_previews": [],
                "database_changed": False,
            }

            for part in parts:

                filename = Path(part["filename"]).name

                if Path(filename).suffix.lower() not in (
                    ".pdf",
                    ".docx",
                ):
                    continue

                attachments_checked += 1

                try:
                    body = part.get("body", {})

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

                        raw = decode_attachment(
                            attachment.get("data", "")
                        )

                    else:
                        raw = decode_attachment(
                            body.get("data", "")
                        )

                    details = preview_resume(filename, raw)

                    email_result["resume_previews"].append({
                        "filename": filename,
                        **details,
                        "database_changed": False,
                    })

                except Exception as exc:

                    email_result["resume_previews"].append({
                        "filename": filename,
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{str(exc)[:200]}"
                        ),
                        "database_changed": False,
                    })

            results.append(email_result)

        except Exception as exc:

            results.append({
                "message_id": message_id,
                "error": (
                    f"{type(exc).__name__}: "
                    f"{str(exc)[:200]}"
                ),
                "database_changed": False,
            })

    return {
        "mode": "preview_only",
        "database_changed": False,
        "gmail_messages_found": len(messages),
        "messages_returned": len(results),
        "messages_without_attachments": messages_without_attachments,
        "attachments_checked": attachments_checked,
        "results": results,
    }
