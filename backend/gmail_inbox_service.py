
import json
import os
from datetime import datetime, timezone
from email.utils import parseaddr, getaddresses
from pathlib import Path

from dotenv import load_dotenv

from .gmail_service import service
from .db import connect

load_dotenv()


def collect_attachments(part, path=""):
    """Collect attachment metadata recursively."""

    attachments = []

    parts = part.get("parts", []) or []

    for index, child in enumerate(parts):
        child_path = f"{path}.{index}"

        if child.get("filename"):
            body = child.get("body", {})

            attachments.append({
                "key": child.get("partId", child_path),
                "attachment_id": body.get("attachmentId"),
                "filename": Path(child["filename"]).name,
                "mime_type": child.get("mimeType"),
                "size_bytes": body.get("size", 0),
            })

        attachments.extend(
            collect_attachments(child, child_path)
        )

    return attachments


def get_message_headers(message):
    """Extract Gmail headers."""

    return {
        h["name"].lower(): h["value"]
        for h in message.get("payload", {}).get("headers", [])
    }


def parse_message_date(message):
    """Convert Gmail timestamp into MySQL-compatible UTC datetime."""

    timestamp = message.get("internalDate")

    if not timestamp:
        return None

    return datetime.fromtimestamp(
        int(timestamp) / 1000,
        tz=timezone.utc
    ).replace(tzinfo=None)


def sync_gmail_inbox():
    """
    Synchronize received and sent Gmail messages.

    Stores message and attachment metadata only.
    Does not import resumes into candidates.
    """

    api = service()

    query = os.getenv(
        "GMAIL_QUERY",
        "in:anywhere -in:spam -in:trash"
    )

    max_messages = int(
        os.getenv("GMAIL_SYNC_MAX_MESSAGES", "100")
    )

    messages = []
    page_token = None

    # Retrieve messages with pagination.
    while len(messages) < max_messages:

        page_size = min(
            100,
            max_messages - len(messages)
        )

        response = api.users().messages().list(
            userId="me",
            q=query,
            maxResults=page_size,
            pageToken=page_token
        ).execute()

        page_messages = response.get("messages", [])
        messages.extend(page_messages)

        page_token = response.get("nextPageToken")

        if not page_token or not page_messages:
            break

    output = {
        "messages_found": len(messages),
        "messages_saved": 0,
        "messages_updated": 0,
        "attachments_saved": 0,
        "failed": 0,
        "database_changed": True
    }

    for reference in messages:

        message_id = reference["id"]

        try:
            message = api.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
            ).execute()

            headers = get_message_headers(message)

            sender_name, sender_email = parseaddr(
                headers.get("from", "")
            )

            recipient_values = []

            for header_name in ("to", "cc", "bcc"):
                recipient_values.extend(
                    getaddresses([headers.get(header_name, "")])
                )

            recipients = [
                {
                    "name": name,
                    "email": email
                }
                for name, email in recipient_values
                if email
            ]

            labels = message.get("labelIds", [])

            is_sent = "SENT" in labels
            is_received = not is_sent

            attachments = collect_attachments(
                message.get("payload", {})
            )

            received_at = parse_message_date(message)

            db = connect()

            try:
                cursor = db.cursor()

                cursor.execute(
                    """
                    SELECT id
                    FROM gmail_messages
                    WHERE gmail_message_id = %s
                    """,
                    (message_id,)
                )

                existing = cursor.fetchone()

                cursor.execute(
                    """
                    INSERT INTO gmail_messages (
                        gmail_message_id,
                        thread_id,
                        sender_name,
                        sender_email,
                        recipients,
                        subject,
                        snippet,
                        received_at,
                        is_received,
                        is_sent,
                        has_attachments,
                        attachment_count,
                        labels,
                        sync_status
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, 'received'
                    )
                    ON DUPLICATE KEY UPDATE
                        thread_id = VALUES(thread_id),
                        sender_name = VALUES(sender_name),
                        sender_email = VALUES(sender_email),
                        recipients = VALUES(recipients),
                        subject = VALUES(subject),
                        snippet = VALUES(snippet),
                        received_at = VALUES(received_at),
                        is_received = VALUES(is_received),
                        is_sent = VALUES(is_sent),
                        has_attachments = VALUES(has_attachments),
                        attachment_count = VALUES(attachment_count),
                        labels = VALUES(labels)
                    """,
                    (
                        message_id,
                        message.get("threadId"),
                        sender_name,
                        sender_email,
                        json.dumps(recipients),
                        headers.get("subject", ""),
                        message.get("snippet", ""),
                        received_at,
                        is_received,
                        is_sent,
                        bool(attachments),
                        len(attachments),
                        json.dumps(labels)
                    )
                )

                cursor.execute(
                    """
                    SELECT id
                    FROM gmail_messages
                    WHERE gmail_message_id = %s
                    """,
                    (message_id,)
                )

                message_row = cursor.fetchone()
                message_pk = message_row[0]

                if existing:
                    output["messages_updated"] += 1
                else:
                    output["messages_saved"] += 1

                for attachment in attachments:

                    filename = attachment["filename"]

                    is_resume = (
                        Path(filename).suffix.lower()
                        in (".pdf", ".docx")
                    )

                    cursor.execute(
                        """
                        INSERT INTO gmail_attachments (
                            gmail_message_pk,
                            attachment_key,
                            gmail_attachment_id,
                            filename,
                            mime_type,
                            size_bytes,
                            is_resume,
                            processing_status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'received')
                        ON DUPLICATE KEY UPDATE
                            gmail_attachment_id =
                                VALUES(gmail_attachment_id),
                            filename = VALUES(filename),
                            mime_type = VALUES(mime_type),
                            size_bytes = VALUES(size_bytes),
                            is_resume = VALUES(is_resume)
                        """,
                        (
                            message_pk,
                            attachment["key"],
                            attachment["attachment_id"],
                            filename,
                            attachment["mime_type"],
                            attachment["size_bytes"],
                            is_resume
                        )
                    )

                    output["attachments_saved"] += 1

                db.commit()

            except Exception:
                db.rollback()
                raise

            finally:
                db.close()

        except Exception as exc:
            output["failed"] += 1
            print(
                f"Failed to synchronize {message_id}: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            )

    return output
