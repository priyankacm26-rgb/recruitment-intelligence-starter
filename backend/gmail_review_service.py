
import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv

from .db import connect
from .resume_service import UPLOAD, extract, parse

load_dotenv()


def import_approved_resume(
    message_id,
    filename,
    approved=False,
    raw=None,
    sender="",
    subject="",
):
    """
    Import one explicitly approved Gmail resume.

    Safety behavior:
    - Requires explicit approval.
    - Accepts PDF and DOCX only.
    - Enforces a configurable attachment size limit.
    - Validates parsed name and email before database insertion.
    - Checks for existing candidate emails and Gmail attachments.
    - Inserts candidate and ingestion log in one transaction.
    - Rolls back database changes and removes the temporary resume
      file when an import fails.
    """

    # 1. Require explicit approval.
    if approved is not True:
        raise ValueError(
            "Explicit approval is required before importing."
        )

    # 2. Validate required inputs.
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("A valid Gmail message ID is required.")

    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A valid attachment filename is required.")

    if not isinstance(raw, bytes) or not raw:
        raise ValueError("Attachment data is missing or invalid.")

    # Reject paths rather than silently accepting path components.
    if Path(filename).name != filename or filename in (".", ".."):
        raise ValueError("Invalid attachment filename.")

    filename = filename.strip()
    suffix = Path(filename).suffix.lower()

    if suffix not in (".pdf", ".docx"):
        raise ValueError("Only PDF and DOCX resumes are supported.")

    # 3. Validate the maximum upload size.
    try:
        max_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))
    except (TypeError, ValueError):
        raise ValueError("MAX_UPLOAD_MB must be a valid integer.")

    if max_mb < 1:
        raise ValueError("MAX_UPLOAD_MB must be at least 1.")

    max_bytes = max_mb * 1024 * 1024

    if len(raw) > max_bytes:
        raise ValueError(
            f"Attachment exceeds the {max_mb} MB upload limit."
        )

    # Create a unique filename to avoid overwriting other resumes.
    safe_name = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        filename,
    )[:150]

    upload_dir = Path(UPLOAD)
    saved_path = upload_dir / (
        uuid.uuid4().hex[:12] + "_" + safe_name
    )

    conn = None
    file_saved = False
    committed = False

    try:
        # 4. Save and parse the attachment.
        # This is inside the try block so failures trigger cleanup.
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(raw)
        file_saved = True

        resume_text = extract(saved_path)
        data = parse(resume_text)

        email = (
            data.get("email") or ""
        ).strip().lower()

        first_name = (
            data.get("first_name") or ""
        ).strip()

        last_name = (
            data.get("last_name") or ""
        ).strip() or None

        if not email:
            raise ValueError(
                "No email was detected. Review the resume manually."
            )

        if (
            not first_name
            or first_name.lower() == "needs review"
        ):
            raise ValueError(
                "Name could not be verified. Review the resume manually."
            )

        # Basic sanity check. The database's unique constraint remains
        # the final protection against duplicate candidate emails.
        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email,
        ):
            raise ValueError(
                "The extracted email appears invalid. "
                "Review the resume manually."
            )

        # 5. Begin a database transaction.
        conn = connect()
        conn.start_transaction()

        cur = conn.cursor(dictionary=True)

        # 6. Reject an existing candidate.
        cur.execute(
            """
            SELECT candidate_id
            FROM candidates
            WHERE LOWER(email) = %s
            FOR UPDATE
            """,
            (email,),
        )

        existing_candidate = cur.fetchone()

        if existing_candidate:
            raise ValueError(
                "Candidate email already exists "
                f"(candidate_id={existing_candidate['candidate_id']}). "
                "No import made."
            )

        # 7. Reject an attachment that has already been logged.
        cur.execute(
            """
            SELECT ingestion_id
            FROM email_ingestion_logs
            WHERE provider = %s
              AND provider_message_id = %s
              AND attachment_name = %s
            FOR UPDATE
            """,
            ("gmail", message_id, filename),
        )

        existing_log = cur.fetchone()

        if existing_log:
            raise ValueError(
                "This Gmail attachment has already been logged."
            )

        # 8. Insert the candidate.
        skills = json.dumps(data.get("skills") or [])

        cur.execute(
            """
            INSERT INTO candidates (
                first_name,
                last_name,
                email,
                phone,
                city,
                current_title,
                years_experience,
                skills,
                resume_path,
                resume_text,
                source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                first_name,
                last_name,
                email,
                data.get("phone"),
                data.get("city"),
                data.get("current_title"),
                data.get("years_experience"),
                skills,
                str(saved_path),
                resume_text,
                "gmail",
            ),
        )

        candidate_id = cur.lastrowid

        # 9. Insert the ingestion log in the same transaction.
        cur.execute(
            """
            INSERT INTO email_ingestion_logs (
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                "gmail",
                message_id,
                sender or None,
                subject or None,
                filename,
                "processed",
                candidate_id,
                None,
            ),
        )

        # Both inserts succeed together or are rolled back together.
        conn.commit()
        committed = True

        return {
            "status": "imported",
            "candidate_id": candidate_id,
            "email": email,
            "name": (
                f"{first_name} {last_name}".strip()
                if last_name
                else first_name
            ),
            "filename": filename,
            "database_changed": True,
        }

    except Exception as exc:
        # Roll back any database writes that have not committed.
        if conn is not None and not committed:
            try:
                conn.rollback()
            except Exception:
                pass

        # A MySQL duplicate-key error can occur during a concurrent
        # import even after the earlier SELECT checks.
        if getattr(exc, "errno", None) == 1062:
            raise ValueError(
                "A duplicate candidate or Gmail attachment was detected. "
                "No import was completed."
            ) from exc

        raise

    finally:
        # Close the database connection.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        # Remove the saved file if the import did not commit.
        if file_saved and not committed:
            try:
                if saved_path.exists():
                    saved_path.unlink()
            except OSError:
                # A cleanup failure must not silently replace the
                # original parsing or database error.
                pass
