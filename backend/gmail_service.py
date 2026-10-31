
import base64
import os
from pathlib import Path
from email.utils import parseaddr

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .db import connect
from .resume_service import save_resume

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def service():
    """Create an authenticated Gmail API client."""

    token = Path(os.getenv("GMAIL_TOKEN_FILE", "token.json"))
    credfile = Path(
        os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    )

    creds = None

    if token.exists():
        creds = Credentials.from_authorized_user_file(
            str(token), SCOPES
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")

    if not creds or not creds.valid:

        if not credfile.exists():
            raise RuntimeError(
                "credentials.json missing; follow docs/gmail_setup.md"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(credfile), SCOPES
        )

        creds = flow.run_local_server(port=0)

        token.write_text(creds.to_json(), encoding="utf-8")

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def decode(data):
    """Decode Gmail URL-safe Base64 attachment data."""

    if not data:
        return b""

    data += "=" * (-len(data) % 4)

    return base64.urlsafe_b64decode(data)


def log(
    mid,
    sender,
    subject,
    name,
    status,
    cid=None,
    error=None,
):
    """Save Gmail attachment processing history."""

    c = connect()

    try:
        cur = c.cursor()

        cur.execute(
            """
            INSERT INTO email_ingestion_logs
            (
                provider,
                provider_message_id,
                sender,
                subject,
                attachment_name,
                status,
                candidate_id,
                error_message,
                received_at
            )
            VALUES
            (
                'gmail',
                %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                candidate_id = VALUES(candidate_id),
                error_message = VALUES(error_message)
            """,
            (
                mid,
                sender,
                subject,
                name,
                status,
                cid,
                error,
            ),
        )

        c.commit()

    finally:
        c.close()


def get_attachment_parts(payload):
    """Recursively collect Gmail attachment MIME parts."""

    parts = []

    if payload.get("filename"):
        parts.append(payload)

    for child in payload.get("parts", []) or []:
        parts.extend(get_attachment_parts(child))

    return parts


def poll_gmail():
    """
    Import supported Gmail resume attachments.

    WARNING:
    This function changes the candidate database.
    Use Gmail preview first before running this function.
    """

    api = service()

    query = os.getenv(
        "GMAIL_QUERY",
        "in:anywhere -in:spam -in:trash",
    )

    max_messages = int(
        os.getenv("GMAIL_SYNC_MAX_MESSAGES", "100")
    )

    print("GMAIL QUERY:", query)

    messages = []
    page_token = None

    # Gmail pagination.
    while len(messages) < max_messages:

        page_size = min(
            100,
            max_messages - len(messages),
        )

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

    out = {
        "scanned": len(messages),
        "processed": 0,
        "duplicates": 0,
        "failed": 0,
        "skipped": 0,
    }

    for ref in messages:

        mid = ref["id"]

        try:
            msg = api.users().messages().get(
                userId="me",
                id=mid,
                format="full",
            ).execute()

            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get(
                    "payload", {}
                ).get("headers", [])
            }

            sender = parseaddr(
                headers.get("from", "")
            )[1]

            subject = headers.get("subject", "")

            parts = get_attachment_parts(
                msg.get("payload", {})
            )

            resumes = [
                p for p in parts
                if Path(p["filename"]).suffix.lower()
                in (".pdf", ".docx")
            ]

            if not resumes:
                out["skipped"] += 1

                # Log only if your existing schema permits it.
                # This is processing history, not inbox storage.
                log(
                    mid,
                    sender,
                    subject,
                    None,
                    "skipped",
                    error="No supported resume attachment",
                )

                continue

            for part in resumes:

                name = Path(part["filename"]).name

                # Check whether this exact attachment was imported.
                c = connect()

                try:
                    cur = c.cursor()

                    cur.execute(
                        """
                        SELECT ingestion_id
                        FROM email_ingestion_logs
                        WHERE provider = %s
                        AND provider_message_id = %s
                        AND attachment_name = %s
                        AND status = 'processed'
                        LIMIT 1
                        """,
                        ("gmail", mid, name),
                    )

                    already_processed = cur.fetchone()

                finally:
                    c.close()

                if already_processed:
                    out["duplicates"] += 1
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
                                messageId=mid,
                                id=body["attachmentId"],
                            )
                            .execute()
                        )

                        raw = decode(
                            attachment.get("data", "")
                        )

                    else:
                        raw = decode(
                            body.get("data", "")
                        )

                    saved = save_resume(
                        name,
                        raw,
                        "gmail",
                    )

                    log(
                        mid,
                        sender,
                        subject,
                        name,
                        "processed",
                        saved["candidate_id"],
                    )

                    out["processed"] += 1

                except Exception as exc:

                    log(
                        mid,
                        sender,
                        subject,
                        name,
                        "failed",
                        error=str(exc)[:800],
                    )

                    out["failed"] += 1

        except Exception as exc:

            out["failed"] += 1

            print(
                f"Gmail message {mid} failed: {str(exc)[:300]}"
            )

    return out
