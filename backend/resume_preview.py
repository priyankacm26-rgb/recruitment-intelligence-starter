import json
import re
from pathlib import Path
from pypdf import PdfReader
from docx import Document
from .resume_service import parse

def extract_text(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)[:100000]
    if suffix == ".docx":
        return "\n".join(p.text for p in Document(str(path)).paragraphs)[:100000]
    raise ValueError("Only PDF and DOCX files are supported")

def preview_resume(filename, raw):
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise ValueError("Only PDF and DOCX files are supported")

    max_bytes = 10 * 1024 * 1024
    if len(raw) > max_bytes:
        raise ValueError("File exceeds the 10 MB preview limit")

    temp_dir = Path("storage") / "preview"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / ("preview_" + Path(filename).name)

    try:
        temp_path.write_bytes(raw)
        text = extract_text(temp_path)
        details = parse(text)

        email = (details.get("email") or "").strip().lower() or None
        matched_id = None

        if email:
            from .db import connect
            conn = connect()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT candidate_id FROM candidates WHERE email=%s",
                    (email,)
                )
                match = cur.fetchone()
                if match:
                    matched_id = match["candidate_id"]
            finally:
                conn.close()

        return {
            "filename": Path(filename).name,
            "email": email,
            "name": " ".join(
                str(details.get(k) or "").strip()
                for k in ("first_name", "last_name")
            ).strip() or "Needs Review",
            "city": details.get("city"),
            "current_title": details.get("current_title"),
            "years_experience": details.get("years_experience"),
            "skills": details.get("skills") or [],
            "matched_candidate_id": matched_id,
            "action": "review_existing_candidate" if matched_id else "review_new_candidate",
            "database_changed": False
        }
    finally:
        if temp_path.exists():
            temp_path.unlink()
