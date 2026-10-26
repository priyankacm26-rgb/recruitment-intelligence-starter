
import base64
import os
from pathlib import Path
from email.utils import parseaddr

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .resume_preview import preview_resume

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Create an authenticated Gmail API client."""
    token_path = Path(os.getenv("GMAIL_TOKEN_FILE", "token.json"))

    if not token_path.is_absolute():
        token_path = Path.cwd() / token_path

    if not token_path.is_file():
        raise RuntimeError(
            f"Gmail token file not found: {token_path}. "
            "Complete Gmail authorization first."
        )

    creds = Credentials.from_authorized_user_file(
        str(token_path),
        SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        # Save refreshed credentials for later use.
        token_path.write_text(creds.to_json(), encoding="utf-8")

    if not creds.valid:
        raise RuntimeError(
            "Gmail authorization is invalid. Please authorize Gmail again."
        )

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def decode_attachment(encoded_data):
    """Decode Gmail's URL-safe Base64 attachment data."""
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


def preview_gmail():
    """
    Preview supported Gmail resume attachments.

    This function does not call save_resume() and does not insert,
    update, or delete candidate records.
    """
    api = get_gmail_service()

    query = os.getenv(
        "GMAIL_QUERY",
        "has:attachment newer_than:7d",
    )

    response = api.users().messages().list(
        userId="me",
        q=query,
        maxResults=25,
    ).execute()

    results = []

    for ref in response.get("messages", []):
        message_id = ref["id"]

        try:
            message = api.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
            ).execute()

            headers = get_headers(message)
            sender = parseaddr(headers.get("from", ""))[1]
            subject = headers.get("subject", "")
            payload = message.get("payload", {})

            parts = collect_parts(payload)

            for part in parts:
                filename = Path(part["filename"]).name

                if Path(filename).suffix.lower() not in (
                    ".pdf",
                    ".docx",
                ):
                    continue

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

                    results.append({
                        "message_id": message_id,
                        "sender": sender,
                        "subject": subject,
                        **details,
                    })

                except Exception as exc:
                    results.append({
                        "message_id": message_id,
                        "sender": sender,
                        "subject": subject,
                        "filename": filename,
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "database_changed": False,
                    })

        except Exception as exc:
            results.append({
                "message_id": message_id,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "database_changed": False,
            })

    return {
        "mode": "preview_only",
        "database_changed": False,
        "attachments_checked": len(results),
        "results": results,
    }
