import json, os, re
from pathlib import Path
from dotenv import load_dotenv
from pypdf import PdfReader
from docx import Document
from google import genai
from .db import connect
load_dotenv()
UPLOAD=Path(os.getenv('UPLOAD_DIR','storage/resumes')); UPLOAD.mkdir(parents=True,exist_ok=True)

def extract(path):
    if path.suffix.lower()=='.pdf':
        return '\n'.join(p.extract_text() or '' for p in PdfReader(str(path)).pages)[:100000]
    if path.suffix.lower()=='.docx':
        return '\n'.join(p.text for p in Document(str(path)).paragraphs)[:100000]
    raise ValueError('Only PDF and DOCX files are supported')


def parse(text):
    """Extract resume fields locally; never call Gemini."""
    import re

    text = text or ""
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    clean = "\n".join(lines)

    def first_match(patterns, flags=re.IGNORECASE):
        for pattern in patterns:
            match = re.search(pattern, clean, flags)
            if match:
                return match.group(1).strip(" ,;:-") or None
        return None

    email_match = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        clean, re.IGNORECASE
    )
    email = email_match.group(0).lower() if email_match else None

    phone_match = re.search(
        r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)?\d{5}[\s.-]?\d{5}(?!\w)",
        clean
    )
    phone = phone_match.group(0).strip() if phone_match else None

    full_name = first_match([
        r"^(?:full name|candidate name|name)\s*[:\-]\s*(.+)$"
    ])

    if not full_name:
        for line in lines[:8]:
            candidate = line.strip(" |,-")
            if (
                2 <= len(candidate.split()) <= 4
                and re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", candidate)
                and not re.search(
                    r"\b(resume|curriculum vitae|profile|email|phone|"
                    r"engineer|developer|analyst|experience|education|"
                    r"linkedin|github)\b",
                    candidate, re.IGNORECASE
                )
            ):
                full_name = candidate
                break

    parts = full_name.split() if full_name else []
    first_name = parts[0] if parts else "Needs Review"
    last_name = " ".join(parts[1:]) if len(parts) > 1 else None

    city = first_match([
        r"^(?:current city|city|location)\s*[:\-]\s*([^,\n]+)",
        r"^(?:address)\s*[:\-]\s*([^,\n]+)",
    ])

    current_title = first_match([
        r"^(?:current title|current role|job title|designation)\s*[:\-]\s*(.+)$",
        r"^(?:professional title|headline)\s*[:\-]\s*(.+)$",
    ])

    if not current_title:
        title_keywords = (
            "data analyst", "business analyst", "software engineer",
            "data engineer", "python developer", "software developer",
            "decision engineer", "project manager", "web developer",
            "machine learning engineer", "intern"
        )
        for line in lines[:35]:
            if len(line) <= 100 and any(
                term in line.lower() for term in title_keywords
            ):
                current_title = line
                break

    experience_patterns = [
        r"\b(\d+(?:\.\d+)?)\s*\+?\s*years?\s+(?:of\s+)?experience\b",
        r"\bexperience\s*[:\-]\s*(\d+(?:\.\d+)?)\s*\+?\s*years?\b",
        r"\b(\d+(?:\.\d+)?)\s*\+?\s*years?\s+in\s+(?:the\s+)?industry\b",
    ]

    years_experience = None
    for pattern in experience_patterns:
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            years_experience = int(value) if value.is_integer() else value
            break

    known_skills = [
        "Python", "SQL", "MySQL", "PostgreSQL", "Excel", "Power BI",
        "Tableau", "Pandas", "NumPy", "Machine Learning", "Data Analysis",
        "FastAPI", "Streamlit", "Java", "JavaScript", "C++", "C",
        "AWS", "Azure", "Docker", "Git", "HTML", "CSS", "React",
        "Node.js", "TensorFlow", "PyTorch", "Communication",
        "Project Management", "Snowflake", "Redshift", "DAX",
        "Microsoft Office", "Data Visualization", "Statistics"
    ]

    skills = [
        skill for skill in known_skills
        if re.search(
            r"(?<![A-Za-z0-9+#])" + re.escape(skill) + r"(?![A-Za-z0-9+#])",
            clean, re.IGNORECASE
        )
    ]

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "city": city,
        "current_title": current_title,
        "years_experience": years_experience,
        "skills": skills,
    }


def save_resume(filename,raw,source='manual_upload'):
    if len(raw)>int(os.getenv('MAX_UPLOAD_MB','10'))*1024*1024: raise ValueError('File too large')
    suffix=Path(filename).suffix.lower()
    if suffix not in ('.pdf','.docx'): raise ValueError('Only PDF and DOCX files are supported')
    safe=re.sub(r'[^A-Za-z0-9._-]','_',Path(filename).name)[:150]
    path=UPLOAD/(os.urandom(4).hex()+'_'+safe); path.write_bytes(raw)
    text=extract(path); d=parse(text); email=(d.get('email') or '').strip().lower() or None
    conn=connect()
    try:
        cur=conn.cursor(dictionary=True); existing=None
        if email:
            cur.execute('SELECT candidate_id FROM candidates WHERE email=%s',(email,)); existing=cur.fetchone()
        skills=json.dumps(d.get('skills') or [])
        if existing:
            cid=existing['candidate_id']
            cur.execute('UPDATE candidates SET phone=COALESCE(phone,%s),city=COALESCE(city,%s),current_title=COALESCE(current_title,%s),years_experience=COALESCE(years_experience,%s),skills=IF(skills IS NULL OR JSON_LENGTH(skills)=0,%s,skills),resume_path=%s,resume_text=%s,source=%s WHERE candidate_id=%s',
              (d.get('phone'),d.get('city'),d.get('current_title'),d.get('years_experience'),skills,str(path),text,source,cid))
            status='updated_existing'
        else:
            first=(d.get('first_name') or '').strip() or 'Needs Review'
            cur.execute('INSERT INTO candidates(first_name,last_name,email,phone,city,current_title,years_experience,skills,resume_path,resume_text,source) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
              (first,d.get('last_name'),email,d.get('phone'),d.get('city'),d.get('current_title'),d.get('years_experience'),skills,str(path),text,source))
            cid=cur.lastrowid; status='created_needs_review' if not email or first=='Needs Review' else 'created'
        conn.commit()
        return {'candidate_id':cid,'status':status,'email':email,'name':d.get('first_name'),'skills':d.get('skills') or []}
    except Exception: conn.rollback(); raise
    finally: conn.close()
