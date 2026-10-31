
import base64
from pathlib import Path
from email.utils import parseaddr

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .db import connect
from .chat_service import run_query
from .resume_service import save_resume


app = FastAPI(title="Recruitment Intelligence API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Request models
# --------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = "local-session"


class GmailImportRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    approved: bool = False


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/health")
def health():
    conn = None

    try:
        conn = connect()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()

        return {
            "status": "ok",
            "database": "connected",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {str(exc)[:250]}",
        )

    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------
# List candidates
# --------------------------------------------------

@app.get("/candidates")
def candidates(limit: int = 100):
    conn = connect()

    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                candidate_id,
                first_name,
                last_name,
                email,
                city,
                current_title,
                years_experience,
                skills,
                source
            FROM candidates
            ORDER BY candidate_id DESC
            LIMIT %s
            """,
            (max(1, min(limit, 100)),),
        )

        return cur.fetchall()

    finally:
        conn.close()


# --------------------------------------------------
# Chat
# --------------------------------------------------

@app.post("/chat")
def chat(req: ChatRequest):
    conn = None

    try:
        result = run_query(req.message)

        conn = connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO chat_messages
                (session_id, role, content)
            VALUES (%s, %s, %s)
            """,
            (req.session_id, "user", req.message),
        )

        cur.execute(
            """
            INSERT INTO chat_messages
                (session_id, role, content)
            VALUES (%s, %s, %s)
            """,
            (req.session_id, "assistant", result["answer"]),
        )

        conn.commit()
        return result

    except Exception as exc:
        if conn is not None:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {str(exc)[:250]}",
        )

    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------
# Manual resume upload
# --------------------------------------------------

@app.post("/resumes/upload")
async def upload(file: UploadFile = File(...)):
    filename = file.filename or "resume"

    if Path(filename).suffix.lower() not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Upload PDF or DOCX",
        )

    try:
        content = await file.read()

        if not content:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty.",
            )

        return save_resume(filename, content)

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Resume processing failed: {str(exc)[:250]}",
        )

    finally:
        await file.close()


# --------------------------------------------------
# Email ingestion logs
# --------------------------------------------------

@app.get("/email/logs")
def email_logs(limit: int = 100):
    conn = connect()

    try:
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT *
            FROM email_ingestion_logs
            ORDER BY ingestion_id DESC
            LIMIT %s
            """,
            (max(1, min(limit, 200)),),
        )

        return cur.fetchall()

    finally:
        conn.close()


# --------------------------------------------------
# Gmail polling
# --------------------------------------------------

@app.post("/email/gmail/poll")
def gmail_poll():
    try:
        from .gmail_service import poll_gmail

        return poll_gmail()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Gmail polling failed: {str(exc)[:400]}",
        )


# --------------------------------------------------
# Gmail preview - read-only
# --------------------------------------------------

@app.post("/email/gmail/preview")
def gmail_preview():
    try:
        from .gmail_preview_service import preview_gmail

        return preview_gmail()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Gmail preview failed: {str(exc)[:400]}",
        )


# --------------------------------------------------
# Gmail attachment helper
# --------------------------------------------------

def collect_attachment_parts(part):
    """Collect named attachment parts from a Gmail MIME payload."""
    found = []

    if part.get("filename"):
        found.append(part)

    for child in part.get("parts", []) or []:
        found.extend(collect_attachment_parts(child))

    return found


# --------------------------------------------------
# Gmail synchronization
# --------------------------------------------------

@app.post("/email/gmail/sync")
def sync_gmail_endpoint():
    try:
        from .gmail_inbox_service import sync_gmail_inbox

        return sync_gmail_inbox()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Gmail synchronization failed: {str(exc)[:400]}",
        )


# --------------------------------------------------
# Gmail inbox - retrieve synchronized messages
# --------------------------------------------------

@app.get("/email/gmail/messages")
def get_gmail_messages(
    folder: str = "all",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
):
    folder = folder.lower().strip()

    if folder not in ("all", "received", "sent"):
        raise HTTPException(
            status_code=400,
            detail="folder must be all, received, or sent",
        )

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    conditions = []
    params = []

    if folder == "received":
        conditions.append("is_received = 1")

    elif folder == "sent":
        conditions.append("is_sent = 1")

    if search.strip():
        conditions.append(
            """
            (
                subject LIKE %s
                OR sender_email LIKE %s
                OR sender_name LIKE %s
                OR recipients LIKE %s
            )
            """
        )

        search_value = f"%{search.strip()}%"
        params.extend([
            search_value,
            search_value,
            search_value,
            search_value,
        ])

    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    conn = connect()

    try:
        cur = conn.cursor(dictionary=True)

        # Count matching emails.
        cur.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM gmail_messages
            {where_clause}
            """,
            tuple(params),
        )

        total = cur.fetchone()["total"]

        # Retrieve matching emails.
        cur.execute(
            f"""
            SELECT
                id,
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
            FROM gmail_messages
            {where_clause}
            ORDER BY received_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )

        messages = cur.fetchall()

        # Retrieve attachments for the displayed emails.
        message_ids = [
            message["id"]
            for message in messages
        ]

        if message_ids:
            placeholders = ",".join(
                ["%s"] * len(message_ids)
            )

            cur.execute(
                f"""
                SELECT
                    gmail_message_pk,
                    attachment_key,
                    gmail_attachment_id,
                    filename,
                    mime_type,
                    size_bytes,
                    is_resume,
                    candidate_id,
                    processing_status
                FROM gmail_attachments
                WHERE gmail_message_pk IN ({placeholders})
                ORDER BY id ASC
                """,
                tuple(message_ids),
            )

            attachments = cur.fetchall()

            attachment_map = {}

            for attachment in attachments:
                message_pk = attachment["gmail_message_pk"]

                attachment_map.setdefault(
                    message_pk, []
                ).append(attachment)

            for message in messages:
                message["attachments"] = attachment_map.get(
                    message["id"], []
                )

        else:
            for message in messages:
                message["attachments"] = []

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "folder": folder,
            "messages": messages,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not retrieve Gmail messages: {str(exc)[:300]}",
        )

    finally:
        conn.close()


# --------------------------------------------------
# Gmail approved resume import
# --------------------------------------------------

@app.post("/email/gmail/import-approved")
def gmail_import_approved(req: GmailImportRequest):

    if req.approved is not True:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required before importing.",
        )

    try:
        from .gmail_service import service
        from .gmail_review_service import import_approved_resume

        gmail = service()

        # Retrieve selected Gmail message.
        message = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=req.message_id,
                format="full",
            )
            .execute()
        )

        payload = message.get("payload", {})

        headers = {
            header["name"].lower(): header["value"]
            for header in payload.get("headers", [])
        }

        sender = parseaddr(headers.get("from", ""))[1]
        subject = headers.get("subject", "")

        # Validate filename.
        requested_filename = Path(req.filename).name

        if requested_filename != req.filename:
            raise HTTPException(
                status_code=400,
                detail="Invalid attachment filename.",
            )

        # Find selected attachment.
        matching_part = next(
            (
                part
                for part in collect_attachment_parts(payload)
                if Path(part["filename"]).name == requested_filename
            ),
            None,
        )

        if matching_part is None:
            raise HTTPException(
                status_code=404,
                detail="Selected attachment was not found.",
            )

        # Only PDF and DOCX resumes are supported.
        if Path(requested_filename).suffix.lower() not in (
            ".pdf",
            ".docx",
        ):
            raise HTTPException(
                status_code=400,
                detail="Only PDF and DOCX resumes can be imported.",
            )

        body = matching_part.get("body", {})
        encoded_data = body.get("data", "")

        attachment_id = body.get("attachmentId")

        # Download Gmail attachment if stored separately.
        if attachment_id:
            attachment = (
                gmail.users()
                .messages()
                .attachments()
                .get(
                    userId="me",
                    messageId=req.message_id,
                    id=attachment_id,
                )
                .execute()
            )

            encoded_data = attachment.get("data", "")

        if not encoded_data:
            raise HTTPException(
                status_code=400,
                detail="Selected attachment contains no data.",
            )

        # Decode URL-safe Base64 data.
        encoded_data += "=" * (-len(encoded_data) % 4)

        try:
            raw_attachment = base64.b64decode(
                encoded_data,
                altchars=b"-_",
                validate=True,
            )

        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Could not decode Gmail attachment.",
            )

        if not raw_attachment:
            raise HTTPException(
                status_code=400,
                detail="Selected attachment is empty.",
            )

        # Import service handles validation and duplicate checking.
        return import_approved_resume(
            message_id=req.message_id,
            filename=requested_filename,
            approved=True,
            raw=raw_attachment,
            sender=sender,
            subject=subject,
        )

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Approved import failed: {str(exc)[:300]}",
        )
