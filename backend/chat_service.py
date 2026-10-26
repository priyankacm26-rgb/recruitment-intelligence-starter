import json
import os
import re

from dotenv import load_dotenv
from google import genai

from .db import connect
from .email_analytics import get_today_email_analytics

load_dotenv()


def get_skills(value):
    """Normalize JSON skills or text skills into a list of strings."""
    if not value:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if item]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item]
        except (json.JSONDecodeError, TypeError):
            pass

        return [item.strip() for item in re.split(r"[,;|]", value) if item.strip()]

    return []


def general_reply(message):
    """Handle greetings and general conversation without querying candidates."""
    q = message.strip().lower().rstrip("!.?")

    replies = {
        "hi": "Hi! 👋 How can I help you today?",
        "hello": "Hello! 😊 What can I help you with?",
        "hey": "Hey! 👋 I'm here to help.",
        "how are you": "I'm doing well, thanks for asking! 😊 How can I help you?",
        "good morning": "Good morning! ☀️ What can I help you with today?",
        "good afternoon": "Good afternoon! How can I help?",
        "good evening": "Good evening! 😊 How can I assist you?",
        "thank you": "You're welcome! 😊 Anything else I can help with?",
        "thanks": "You're welcome! 😊",
        "bye": "Goodbye! Have a great day. 👋",
        "who are you": (
            "I'm your Recruitment Intelligence Assistant. I can help you "
            "search candidates, review skills, check available jobs, answer "
            "questions about today's Gmail inbox, and answer general questions."
        ),
        "what can you do": (
            "I can count and search candidates, filter by skills or experience, "
            "show available jobs, count today's inbox emails and preview resume "
            "attachments without importing them into the database."
        ),
    }

    if q in replies:
        return replies[q]

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        try:
            client = genai.Client(api_key=key)
            result = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=(
                    "You are a friendly assistant inside a recruitment application. "
                    "Answer general questions naturally. Do not invent candidate, "
                    "job, or email database facts. For recruitment facts, explain "
                    "that the app can query its connected data. User message: "
                    + message
                ),
            )
            if result.text:
                return result.text.strip()
        except Exception:
            pass

    return (
        "I'm here to help! Try 'How many candidates are there?', "
        "'Find candidates with Python skills', 'Show available jobs', "
        "'How many emails did we receive today?', or "
        "'How many resumes were received today?'"
    )


def _is_count_question(q):
    return bool(re.search(r"\b(how many|count|total number|number of|total)\b", q))


def email_question_intent(message):
    """
    Return a Gmail analytics intent, or None if this is not an email question.
    Email analytics always run before candidate intent classification.
    """
    q = message.lower().replace("’", "'")

    email_terms = r"\b(emails?|e-mails?|mails?|inbox|gmail messages?)\b"
    resume_terms = r"\b(resumes?|cv files?|curriculum vitae|resume attachments?)\b"

    asks_today = bool(re.search(r"\b(today|today's|todays|this day)\b", q))
    asks_count = _is_count_question(q)
    asks_list = bool(re.search(r"\b(list|show|display|which|who|applicants?)\b", q))
    asks_skills = bool(re.search(r"\b(skills?|skill set|technologies)\b", q))

    # Specific questions about applicants/resumes attached to today's emails.
    if asks_today and asks_skills and (asks_list or re.search(r"\b(candidate|applicant|resume)\b", q)):
        return "list_today_resumes"

    if asks_today and re.search(r"\b(applicants?|candidates?)\b", q) and asks_list:
        return "list_today_resumes"

    # Count messages and resume files separately.
    if re.search(resume_terms, q) and (asks_count or asks_today):
        return "count_today_resumes"

    if re.search(email_terms, q) and (asks_count or asks_today):
        return "count_today_emails"

    # Direct phrasing such as "list candidates from today's emails".
    if asks_today and asks_list and re.search(r"\b(emails?|mails?|inbox)\b", q):
        return "list_today_resumes"

    return None


def _email_analytics_reply(message, intent):
    """Answer Gmail questions from live read-only analytics."""
    data = get_today_email_analytics()
    date_label = f"{data['date']} ({data['timezone']})"

    if intent == "count_today_emails":
        answer = (
            f"Today, {date_label}, I found {data['emails_received']} "
            "email message(s) in the Gmail inbox."
        )
        total = data["emails_received"]

    elif intent == "count_today_resumes":
        answer = (
            f"Today, {date_label}, I successfully previewed "
            f"{data['resume_attachments_previewed']} PDF/DOCX resume attachment(s). "
            f"The inbox contained {data['emails_received']} email message(s)."
        )
        total = data["resume_attachments_previewed"]

    else:
        previews = data.get("resumes", [])
        if not previews:
            answer = (
                f"I couldn't find any successfully previewed PDF/DOCX resume "
                f"attachments in today's inbox ({date_label})."
            )
        else:
            lines = []
            for item in previews:
                name = item.get("name") or item.get("full_name") or "Name not detected"
                skills = get_skills(item.get("skills"))
                subject = item.get("subject") or "No subject"
                email = item.get("email") or "Email not detected"
                skill_text = ", ".join(skills) if skills else "Skills not detected"
                lines.append(
                    f"- {name} | Email: {email} | Skills: {skill_text} | "
                    f"Subject: {subject}"
                )
            answer = (
                f"Resume details previewed from today's emails ({date_label}):\n"
                + "\n".join(lines)
            )
        total = len(previews)

    if data.get("errors"):
        answer += (
            f"\nNote: {len(data['errors'])} message or attachment error(s) "
            "occurred, so some results may be incomplete."
        )

    return {
        "answer": answer,
        "filters": {
            "intent": intent,
            "date": data["date"],
            "timezone": data["timezone"],
        },
        "total": total,
        "candidates": [],
        "email_analytics": data,
    }


def filters_for(message):
    """Classify recruitment queries; use safe local rules as a fallback."""
    q = message.lower()

    if _is_count_question(q):
        if re.search(r"\b(jobs?|openings?|positions?|vacancies)\b", q):
            return {"intent": "count_jobs"}
        if re.search(r"\b(candidates?|applicants?|people|resumes?)\b", q):
            return {
                "intent": "count_candidates",
                "city": None,
                "min_experience": None,
                "skills": [],
            }

    if re.search(r"\b(list|show|display|available|all)\b", q) and re.search(
        r"\b(jobs?|openings?|positions?|vacancies)\b", q
    ):
        return {"intent": "list_jobs"}

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        try:
            client = genai.Client(api_key=key)
            prompt = (
                "Classify the recruitment query. Return JSON only. "
                "Allowed intent values: search_candidates, count_candidates, "
                "count_jobs, list_jobs. Include city (string/null), "
                "min_experience (number/null), skills (array of strings). "
                "Never generate SQL. Do not invent filters. Query: " + message
            )
            result = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(result.text)
            if data.get("intent") in {
                "search_candidates", "count_candidates", "count_jobs", "list_jobs"
            }:
                data.setdefault("city", None)
                data.setdefault("min_experience", None)
                data.setdefault("skills", [])
                data["skills"] = data["skills"][:10]
                return data
        except Exception:
            pass

    if re.search(r"\b(job|jobs|opening|openings|position|positions|vacanc(?:y|ies))\b", q):
        return {"intent": "list_jobs"}

    cities = {
        "bangalore": "Bengaluru",
        "bengaluru": "Bengaluru",
        "mysore": "Mysuru",
        "mysuru": "Mysuru",
        "hyderabad": "Hyderabad",
        "pune": "Pune",
        "mumbai": "Mumbai",
        "delhi": "Delhi",
    }
    city = next((value for key, value in cities.items() if key in q), None)

    match = re.search(
        r"(?:at least|minimum|min\.?|over|more than)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
        q,
    )

    known_skills = [
        "python", "sql", "power bi", "excel", "fastapi",
        "mysql", "tableau", "java", "pandas", "aws",
        "machine learning", "data analysis", "communication",
    ]
    skills = [skill for skill in known_skills if skill in q]

    return {
        "intent": "search_candidates",
        "city": city,
        "min_experience": float(match.group(1)) if match else None,
        "skills": skills,
    }


def run_query(message):
    q = message.strip()

    if not q:
        return {
            "answer": "Please enter a message so I can help.",
            "filters": {},
            "total": 0,
            "candidates": [],
        }

    # Route email analytics before candidate searches, so "resumes received"
    # cannot accidentally become a count of rows in the candidates table.
    email_intent = email_question_intent(q)
    if email_intent:
        try:
            return _email_analytics_reply(q, email_intent)
        except Exception as exc:
            return {
                "answer": (
                    "I couldn't retrieve today's Gmail analytics. Check Gmail "
                    "authorization and configuration. "
                    f"Details: {type(exc).__name__}: {str(exc)[:200]}"
                ),
                "filters": {"intent": email_intent, "error": True},
                "total": 0,
                "candidates": [],
            }

    general_patterns = (
        r"^(hi|hello|hey)[!. ]*$",
        r"^how are you[?!. ]*$",
        r"^good (morning|afternoon|evening)[!. ]*$",
        r"^(thanks|thank you)[!. ]*$",
        r"^bye[!. ]*$",
        r"^who are you[?!. ]*$",
        r"^what can you do[?!. ]*$",
    )
    if any(re.match(pattern, q, re.IGNORECASE) for pattern in general_patterns):
        return {
            "answer": general_reply(q),
            "filters": {"intent": "general"},
            "total": 0,
            "candidates": [],
        }

    filters = filters_for(q)
    intent = filters.get("intent")

    if intent not in {
        "count_candidates", "search_candidates", "count_jobs", "list_jobs"
    }:
        return {
            "answer": general_reply(q),
            "filters": {"intent": "general"},
            "total": 0,
            "candidates": [],
        }

    conn = connect()
    try:
        cur = conn.cursor(dictionary=True)

        if intent == "count_candidates":
            cur.execute("SELECT COUNT(*) AS total FROM candidates")
            total = cur.fetchone()["total"]
            return {
                "answer": f"There are {total} candidates in the database.",
                "filters": filters,
                "total": total,
                "candidates": [],
            }

        if intent == "count_jobs":
            cur.execute("SELECT COUNT(*) AS total FROM jobs")
            total = cur.fetchone()["total"]
            return {
                "answer": f"There are {total} jobs in the database.",
                "filters": filters,
                "total": total,
                "jobs": [],
                "candidates": [],
            }

        if intent == "list_jobs":
            cur.execute(
                "SELECT job_id, title, description, source "
                "FROM jobs ORDER BY job_id DESC LIMIT 100"
            )
            jobs = cur.fetchall()
            if not jobs:
                answer = "There are no jobs in the database yet."
            else:
                lines = [
                    f"{index}. {job['title']} (Job ID: {job['job_id']})"
                    for index, job in enumerate(jobs, start=1)
                ]
                answer = f"Found {len(jobs)} job(s):\n" + "\n".join(lines)

            return {
                "answer": answer,
                "filters": filters,
                "total": len(jobs),
                "jobs": jobs,
                "candidates": [],
            }

        sql = (
            "SELECT candidate_id, first_name, last_name, email, city, "
            "current_title, years_experience, skills "
            "FROM candidates WHERE 1=1"
        )
        args = []

        if filters.get("city"):
            sql += " AND LOWER(city)=LOWER(%s)"
            args.append(filters["city"])

        experience = filters.get("min_experience")
        if experience is not None:
            try:
                experience = max(0, min(float(experience), 60))
                sql += " AND years_experience >= %s"
                args.append(experience)
            except (ValueError, TypeError):
                pass

        sql += " ORDER BY years_experience DESC LIMIT 100"
        cur.execute(sql, args)
        rows = cur.fetchall()

        skills = [str(skill).lower() for skill in filters.get("skills", [])]
        if skills:
            rows = [
                row for row in rows
                if all(
                    any(
                        skill in item.lower()
                        for item in get_skills(row.get("skills"))
                    )
                    for skill in skills
                )
            ]

        if rows:
            lines = []
            for row in rows:
                name = " ".join(
                    part for part in [row.get("first_name"), row.get("last_name")]
                    if part
                )
                candidate_skills = ", ".join(get_skills(row.get("skills"))) or "Not listed"
                lines.append(
                    f"- {name}: {row.get('current_title') or 'Title not listed'}; "
                    f"Skills: {candidate_skills}; "
                    f"Experience: {row.get('years_experience') or 0} years"
                )
            answer = f"Found {len(rows)} matching candidate(s):\n" + "\n".join(lines)
        else:
            answer = (
                "I couldn't find any candidates matching those filters. "
                "Try another skill, city, or experience level."
            )

        return {
            "answer": answer,
            "filters": filters,
            "total": len(rows),
            "candidates": rows,
        }
    finally:
        conn.close()
