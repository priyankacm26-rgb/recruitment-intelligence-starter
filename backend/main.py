
import base64
import os
from email.utils import parseaddr
from pathlib import Path

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
# Existing Gmail polling endpoint
# Do not run until the legacy poll service is reviewed.
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
# Gmail preview - must not write to the database
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
# Gmail approved import
# --------------------------------------------------

def collect_attachment_parts(part):
    """Collect named attachment parts from a Gmail MIME payload."""
    found = []

    if part.get("filename"):
        found.append(part)

    for child in part.get("parts", []) or []:
        found.extend(collect_attachment_parts(child))

    return found


@app.post("/email/gmail/import-approved")
def gmail_import_approved(req: GmailImportRequest):
    # Require explicit approval.
    if req.approved is not True:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required before importing.",
        )

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        from .gmail_review_service import import_approved_resume

        # Find the Gmail token file.
        token_path = Path(
            os.getenv("GMAIL_TOKEN_FILE", "token.json")
        )

        if not token_path.is_absolute():
            token_path = Path.cwd() / token_path

        if not token_path.is_file():
            raise HTTPException(
                status_code=500,
                detail=(
                    "Gmail token file was not found. "
                    "Check GMAIL_TOKEN_FILE and your project directory."
                ),
            )

        # Use read-only Gmail access.
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly"
        ]

        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            scopes,
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(
                credentials.to_json(),
                encoding="utf-8",
            )

        if not credentials.valid:
            raise HTTPException(
                status_code=500,
                detail="Gmail credentials are invalid. Reauthorize Gmail.",
            )

        gmail = build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )

        # Retrieve the selected Gmail message.
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

        # Match the requested attachment to this message.
        requested_filename = Path(req.filename).name

        if requested_filename != req.filename:
            raise HTTPException(
                status_code=400,
                detail="Invalid attachment filename.",
            )

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
                detail=(
                    "The specified attachment was not found "
                    "in the selected Gmail message."
                ),
            )

        body = matching_part.get("body", {})
        encoded_data = body.get("data", "")

        # Gmail often stores attachment bytes separately.
        attachment_id = body.get("attachmentId")

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
                detail="The selected attachment contains no data.",
            )

        # Decode Gmail's URL-safe Base64 attachment data.
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
                detail="Could not decode the Gmail attachment.",
            )

        if not raw_attachment:
            raise HTTPException(
                status_code=400,
                detail="The selected attachment is empty.",
            )

        # The service must validate the file, check duplicates,
        # and write candidate + ingestion log transactionally.
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
