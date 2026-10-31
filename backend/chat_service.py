
import json
import os
import re
from difflib import SequenceMatcher

from dotenv import load_dotenv
from google import genai

from .db import connect
from .email_analytics import get_today_email_analytics

load_dotenv()


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def normalize_text(value):
    """Normalize text for consistent matching."""
    if value is None:
        return ""

    value = str(value).lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9@.+#\s-]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def get_skills(value):
    """Normalize JSON skills or text skills into a list."""

    if not value:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item
        ]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)

            if isinstance(parsed, list):
                return [
                    str(item).strip()
                    for item in parsed
                    if item
                ]

        except (json.JSONDecodeError, TypeError):
            pass

        return [
            item.strip()
            for item in re.split(r"[,;|]", value)
            if item.strip()
        ]

    return []


def safe_float(value):
    try:
        if value is None or value == "":
            return None

        return float(value)

    except (ValueError, TypeError):
        return None


def candidate_name(row):
    return " ".join(
        str(value).strip()
        for value in [
            row.get("first_name"),
            row.get("last_name"),
        ]
        if value
    ).strip()


def get_candidate_search_text(row):
    """Build searchable text from existing candidate columns."""

    skills = " ".join(get_skills(row.get("skills")))

    return normalize_text(" ".join([
        candidate_name(row),
        str(row.get("email") or ""),
        str(row.get("city") or ""),
        str(row.get("current_title") or ""),
        skills,
        str(row.get("resume_text") or ""),
    ]))


# ---------------------------------------------------------
# GENERAL CONVERSATION
# ---------------------------------------------------------

def general_reply(message):
    q = normalize_text(message).rstrip("!.?")

    replies = {
        "hi": "Hi! How can I help you today?",
        "hello": "Hello! What can I help you with?",
        "hey": "Hey! How can I help?",
        "how are you": "I'm doing well! How can I help you?",
        "good morning": "Good morning! What can I help you with?",
        "good afternoon": "Good afternoon! How can I help?",
        "good evening": "Good evening! How can I assist you?",
        "thank you": "You're welcome!",
        "thanks": "You're welcome!",
        "bye": "Goodbye! Have a great day.",
        "who are you": (
            "I'm your Recruitment Intelligence Assistant. "
            "I can search candidates, analyze skills, find jobs, "
            "review resume information and answer Gmail analytics questions."
        ),
        "what can you do": (
            "I can search candidates by name, skills, job title, "
            "experience, location and resume keywords. I can also "
            "show jobs and answer Gmail analytics questions."
        ),
    }

    if q in replies:
        return replies[q]

    key = os.getenv("GEMINI_API_KEY", "").strip()

    if key:
        try:
            client = genai.Client(api_key=key)

            result = client.models.generate_content(
                model=os.getenv(
                    "GEMINI_MODEL",
                    "gemini-2.5-flash",
                ),
                contents=(
                    "You are a friendly assistant inside a recruitment "
                    "application. Answer general questions naturally. "
                    "Never invent candidate, job or email database facts. "
                    "If the user asks for recruitment data, explain that "
                    "you can search the connected database.\n\n"
                    f"User: {message}"
                ),
            )

            if result.text:
                return result.text.strip()

        except Exception:
            pass

    return (
        "I can help you search candidates, review resumes, "
        "find jobs and check Gmail analytics. "
        "Try asking: Find Sagar Kolur, Find Python candidates, "
        "or Show available jobs."
    )


# ---------------------------------------------------------
# EMAIL ANALYTICS
# ---------------------------------------------------------

def is_count_question(message):
    return bool(re.search(
        r"\b(how many|count|total number|number of|total)\b",
        message,
        re.IGNORECASE,
    ))


def email_question_intent(message):
    q = normalize_text(message)

    email_terms = (
        r"\b(emails?|e-mails?|mails?|inbox|gmail messages?)\b"
    )

    resume_terms = (
        r"\b(resumes?|cv files?|curriculum vitae|resume attachments?)\b"
    )

    asks_today = bool(re.search(
        r"\b(today|todays|this day)\b",
        q,
    ))

    asks_count = is_count_question(q)

    asks_list = bool(re.search(
        r"\b(list|show|display|which|who|applicants?)\b",
        q,
    ))

    asks_skills = bool(re.search(
        r"\b(skills?|skill set|technologies)\b",
        q,
    ))

    if (
        asks_today
        and asks_skills
        and (
            asks_list
            or re.search(r"\b(candidate|applicant|resume)\b", q)
        )
    ):
        return "list_today_resumes"

    if (
        asks_today
        and re.search(r"\b(applicants?|candidates?)\b", q)
        and asks_list
    ):
        return "list_today_resumes"

    if re.search(resume_terms, q) and (asks_count or asks_today):
        return "count_today_resumes"

    if re.search(email_terms, q) and (asks_count or asks_today):
        return "count_today_emails"

    if (
        asks_today
        and asks_list
        and re.search(r"\b(emails?|mails?|inbox)\b", q)
    ):
        return "list_today_resumes"

    return None


def email_analytics_reply(intent):
    data = get_today_email_analytics()

    date_label = f"{data['date']} ({data['timezone']})"

    if intent == "count_today_emails":

        total = data["emails_received"]

        answer = (
            f"Today, {date_label}, I found "
            f"{total} email message(s) in the Gmail inbox."
        )

    elif intent == "count_today_resumes":

        total = data["resume_attachments_previewed"]

        answer = (
            f"Today, {date_label}, I successfully previewed "
            f"{total} PDF/DOCX resume attachment(s). "
            f"The inbox contained {data['emails_received']} email(s)."
        )

    else:

        previews = data.get("resumes", [])
        total = len(previews)

        if not previews:

            answer = (
                f"I couldn't find any successfully previewed "
                f"PDF/DOCX resume attachments in today's inbox "
                f"({date_label})."
            )

        else:

            lines = []

            for item in previews:

                name = (
                    item.get("name")
                    or item.get("full_name")
                    or "Name not detected"
                )

                skills = get_skills(item.get("skills"))

                email = item.get("email") or "Email not detected"

                subject = item.get("subject") or "No subject"

                skill_text = (
                    ", ".join(skills)
                    if skills
                    else "Skills not detected"
                )

                lines.append(
                    f"- {name} | Email: {email} | "
                    f"Skills: {skill_text} | Subject: {subject}"
                )

            answer = (
                f"Resume details previewed from today's emails "
                f"({date_label}):\n"
                + "\n".join(lines)
            )

    if data.get("errors"):
        answer += (
            f"\nNote: {len(data['errors'])} message or attachment "
            "error(s) occurred. Results may be incomplete."
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


# ---------------------------------------------------------
# QUERY UNDERSTANDING
# ---------------------------------------------------------

KNOWN_SKILLS = [
    "python",
    "sql",
    "mysql",
    "postgresql",
    "power bi",
    "powerbi",
    "excel",
    "advanced excel",
    "tableau",
    "pandas",
    "numpy",
    "aws",
    "azure",
    "java",
    "javascript",
    "c",
    "c++",
    "machine learning",
    "deep learning",
    "data analysis",
    "data analytics",
    "data engineering",
    "fastapi",
    "streamlit",
    "communication",
    "dax",
    "power apps",
    "snowflake",
    "redshift",
    "etl",
    "statistics",
    "matplotlib",
    "seaborn",
    "html",
    "css",
    "react",
    "node.js",
    "git",
    "docker",
]


CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "mysore": "Mysuru",
    "mysuru": "Mysuru",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "mumbai": "Mumbai",
    "delhi": "Delhi",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "noida": "Noida",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
}


def extract_skills(message):
    q = normalize_text(message)

    found = []

    for skill in sorted(KNOWN_SKILLS, key=len, reverse=True):

        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"

        if re.search(pattern, q):
            normalized = skill

            if skill == "powerbi":
                normalized = "power bi"

            if normalized not in found:
                found.append(normalized)

    return found


def extract_city(message):
    q = normalize_text(message)

    for alias, city in CITY_ALIASES.items():

        if re.search(
            r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])",
            q,
        ):
            return city

    return None


def extract_experience(message):
    q = normalize_text(message)

    minimum = None
    maximum = None

    between = re.search(
        r"\b(?:between|from)\s+(\d+(?:\.\d+)?)\s+"
        r"(?:and|to|-)\s+(\d+(?:\.\d+)?)\s+"
        r"(?:years?|yrs?)\b",
        q,
    )

    if between:
        minimum = float(between.group(1))
        maximum = float(between.group(2))

        return minimum, maximum

    minimum_match = re.search(
        r"\b(?:at least|minimum|min|more than|over|above|"
        r"atleast)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b",
        q,
    )

    maximum_match = re.search(
        r"\b(?:at most|maximum|max|less than|below|under|"
        r"up to|upto)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b",
        q,
    )

    exact_match = re.search(
        r"\b(?:exactly|with)\s*(\d+(?:\.\d+)?)\s*"
        r"(?:years?|yrs?)\b",
        q,
    )

    if minimum_match:
        minimum = float(minimum_match.group(1))

    if maximum_match:
        maximum = float(maximum_match.group(1))

    if exact_match and minimum is None and maximum is None:
        minimum = float(exact_match.group(1))
        maximum = minimum

    return minimum, maximum


def extract_title(message):
    q = normalize_text(message)

    titles = [
        "data analyst",
        "senior data analyst",
        "junior data analyst",
        "business analyst",
        "data engineer",
        "senior data engineer",
        "python developer",
        "software developer",
        "software engineer",
        "web developer",
        "frontend developer",
        "backend developer",
        "full stack developer",
        "machine learning engineer",
        "ai engineer",
        "project manager",
        "hr executive",
        "recruiter",
        "data scientist",
        "power bi developer",
        "sql developer",
        "accountant",
        "marketing executive",
    ]

    for title in sorted(titles, key=len, reverse=True):

        if title in q:
            return title

    return None


def extract_name_hint(message):
    """
    Extract a possible name phrase from natural-language queries.
    Actual matching is validated against names in the database.
    """

    q = normalize_text(message)

    patterns = [
        r"\b(?:find|search|show|display|open|view|get|"
        r"fetch|look up|lookup|details for|profile of|"
        r"resume of|resume for)\s+(?:me\s+)?(.+)",
        r"\b(?:tell me about|who is|what about)\s+(.+)",
    ]

    for pattern in patterns:

        match = re.search(pattern, q)

        if match:
            value = match.group(1)

            value = re.sub(
                r"\b(candidate|candidates|profile|resume|"
                r"details|information|please|with|having|"
                r"who has|skills|skill|experience)\b",
                " ",
                value,
            )

            value = re.sub(
                r"\b(?:in|at|from)\s+"
                r"(?:bangalore|bengaluru|hyderabad|pune|"
                r"mumbai|delhi|chennai)\b",
                " ",
                value,
            )

            return re.sub(r"\s+", " ", value).strip()

    return None


def is_general_greeting(message):
    q = normalize_text(message)

    patterns = [
        r"^(hi|hello|hey)$",
        r"^how are you$",
        r"^good (morning|afternoon|evening)$",
        r"^(thanks|thank you)$",
        r"^bye$",
        r"^who are you$",
        r"^what can you do$",
    ]

    return any(re.match(pattern, q) for pattern in patterns)


def filters_for(message):
    """
    Understand natural-language recruitment queries.

    Gemini provides optional query interpretation.
    Local extraction remains available if Gemini is unavailable.
    """

    q = normalize_text(message)

    filters = {
        "intent": "search_candidates",
        "candidate_name": extract_name_hint(q),
        "city": extract_city(q),
        "min_experience": None,
        "max_experience": None,
        "skills": extract_skills(q),
        "job_title": extract_title(q),
        "keywords": [],
    }

    minimum, maximum = extract_experience(q)

    filters["min_experience"] = minimum
    filters["max_experience"] = maximum

    if is_count_question(q):

        if re.search(
            r"\b(jobs?|openings?|positions?|vacancies)\b",
            q,
        ):
            filters["intent"] = "count_jobs"
            return filters

        if re.search(
            r"\b(candidates?|applicants?|people|resumes?)\b",
            q,
        ):
            filters["intent"] = "count_candidates"
            return filters

    if re.search(
        r"\b(list|show|display|available|all)\b",
        q,
    ) and re.search(
        r"\b(jobs?|openings?|positions?|vacancies)\b",
        q,
    ):
        filters["intent"] = "list_jobs"
        return filters

    # Optional Gemini interpretation for less predictable phrasing.
    key = os.getenv("GEMINI_API_KEY", "").strip()

    if key:

        try:
            client = genai.Client(api_key=key)

            prompt = f"""
You are an intent and filter extraction engine for a recruitment system.

Read the user's question and return valid JSON only.

Allowed fields:
{{
  "intent": "search_candidates | count_candidates | count_jobs | list_jobs",
  "candidate_name": "string or null",
  "city": "string or null",
  "min_experience": "number or null",
  "max_experience": "number or null",
  "skills": ["skill names"],
  "job_title": "string or null",
  "keywords": ["search terms"]
}}

Rules:
- Never generate SQL.
- Never invent a candidate name.
- Extract a name only if the user is asking about a person.
- Preserve the user's actual filters.
- Do not assume missing experience or location.
- Use an empty array when no skills or keywords are specified.
- If the question is about finding candidates, use search_candidates.
- Do not return candidate data.

User question: {message}
"""

            result = client.models.generate_content(
                model=os.getenv(
                    "GEMINI_MODEL",
                    "gemini-2.5-flash",
                ),
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                },
            )

            data = json.loads(result.text)

            allowed_intents = {
                "search_candidates",
                "count_candidates",
                "count_jobs",
                "list_jobs",
            }

            if data.get("intent") in allowed_intents:

                # Keep local extraction as a fallback.
                for field in [
                    "candidate_name",
                    "city",
                    "min_experience",
                    "max_experience",
                    "job_title",
                ]:
                    if data.get(field):
                        filters[field] = data[field]

                if data.get("skills"):
                    filters["skills"] = data["skills"][:15]

                if data.get("keywords"):
                    filters["keywords"] = data["keywords"][:15]

                filters["intent"] = data["intent"]

        except Exception:
            pass

    return filters


# ---------------------------------------------------------
# CANDIDATE NAME MATCHING AND RELEVANCE
# ---------------------------------------------------------

def match_candidate_name(row, message):
    """
    Match a name against the actual candidate name.

    Returns a score:
    100 = exact full name
    90  = full name included in query
    80  = exact first/last name
    0   = no name match
    """

    full_name = normalize_text(candidate_name(row))
    q = normalize_text(message)

    if not full_name:
        return 0

    if full_name == q:
        return 100

    if re.search(
        r"(?<![a-z0-9])" + re.escape(full_name) + r"(?![a-z0-9])",
        q,
    ):
        return 100

    # Only allow single-name matching when the query clearly
    # asks to find or view a person.
    asks_for_person = bool(re.search(
        r"\b(find|search|show|display|open|view|get|fetch|"
        r"lookup|look up|who is|tell me about|profile of|"
        r"resume of|resume for)\b",
        q,
    ))

    if asks_for_person:

        name_parts = full_name.split()

        for part in name_parts:

            if len(part) < 3:
                continue

            if re.search(
                r"(?<![a-z0-9])" + re.escape(part) + r"(?![a-z0-9])",
                q,
            ):
                return 80

    return 0


def score_candidate(row, message, filters):
    """Rank candidate results using available database information."""

    score = 0

    name_score = match_candidate_name(row, message)

    if name_score:
        score += name_score

    skills = [
        normalize_text(skill)
        for skill in get_skills(row.get("skills"))
    ]

    title = normalize_text(row.get("current_title"))
    city = normalize_text(row.get("city"))
    resume_text = normalize_text(row.get("resume_text"))

    search_text = get_candidate_search_text(row)

    for skill in filters.get("skills", []):

        skill = normalize_text(skill)

        if not skill:
            continue

        if any(skill == item or skill in item for item in skills):
            score += 20

        elif skill in resume_text:
            score += 12

    requested_title = normalize_text(filters.get("job_title"))

    if requested_title:

        if requested_title == title:
            score += 30

        elif requested_title in title or title in requested_title:
            score += 20

        elif requested_title in resume_text:
            score += 10

    requested_city = normalize_text(filters.get("city"))

    if requested_city and requested_city == city:
        score += 15

    for keyword in filters.get("keywords", []):

        keyword = normalize_text(keyword)

        if keyword and keyword in search_text:
            score += 5

    return score


def candidate_matches_filters(row, filters):
    """Apply strict user-requested filters."""

    skills = [
        normalize_text(skill)
        for skill in get_skills(row.get("skills"))
    ]

    resume_text = normalize_text(row.get("resume_text"))

    search_text = get_candidate_search_text(row)

    requested_skills = [
        normalize_text(skill)
        for skill in filters.get("skills", [])
        if skill
    ]

    # Every requested skill must match a stored skill or resume text.
    for skill in requested_skills:

        if not (
            any(skill == item or skill in item for item in skills)
            or skill in resume_text
        ):
            return False

    city = normalize_text(row.get("city"))
    requested_city = normalize_text(filters.get("city"))

    if requested_city and requested_city not in city:
        return False

    experience = safe_float(row.get("years_experience"))

    minimum = safe_float(filters.get("min_experience"))
    maximum = safe_float(filters.get("max_experience"))

    if minimum is not None:
        if experience is None or experience < minimum:
            return False

    if maximum is not None:
        if experience is None or experience > maximum:
            return False

    title = normalize_text(row.get("current_title"))
    requested_title = normalize_text(filters.get("job_title"))

    if requested_title:

        title_matches = (
            requested_title in title
            or title in requested_title
            or requested_title in resume_text
        )

        if not title_matches:
            return False

    for keyword in filters.get("keywords", []):

        keyword = normalize_text(keyword)

        if keyword and keyword not in search_text:
            return False

    return True


# ---------------------------------------------------------
# DATABASE CANDIDATE SEARCH
# ---------------------------------------------------------

def public_candidate_record(row):
    """
    Return candidate fields without exposing full resume_text.
    No database writes are performed here.
    """

    return {
        "candidate_id": row.get("candidate_id"),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "email": row.get("email"),
        "city": row.get("city"),
        "current_title": row.get("current_title"),
        "years_experience": row.get("years_experience"),
        "skills": get_skills(row.get("skills")),
    }


def search_candidates(cur, message, filters):
    """
    Search existing candidates using the current database schema.
    Exact or partial name searches never fall back to unrelated candidates.
    """

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
            resume_text
        FROM candidates
        ORDER BY candidate_id DESC
        LIMIT 2000
        """
    )

    all_rows = cur.fetchall()

    if not all_rows:
        return [], "No candidates are currently available in the database."

    requested_name = normalize_text(
        filters.get("candidate_name")
    )

    # Search for the requested candidate name first.
    name_matches = []

    if requested_name:
        for row in all_rows:
            score = match_candidate_name(row, message)

            if score > 0:
                name_matches.append((score, row))

        # CRITICAL FIX:
        # Never return unrelated candidates when a name was requested.
        if not name_matches:
            return [], (
                f"I couldn't find a candidate named "
                f"'{filters.get('candidate_name')}' in this database. "
                "Check the spelling or try another name."
            )

        highest_score = max(
            score for score, _ in name_matches
        )

        name_matches = [
            (score, row)
            for score, row in name_matches
            if score == highest_score
        ]

        rows = [row for _, row in name_matches]

    else:
        rows = all_rows

    # Apply additional filters.
    rows = [
        row
        for row in rows
        if candidate_matches_filters(row, filters)
    ]

    if not rows:
        return [], (
            "I found the requested candidate name, but the candidate "
            "does not match all the additional filters you specified."
        )

    # Rank candidates.
    ranked = []

    for row in rows:
        score = score_candidate(row, message, filters)
        ranked.append((score, row))

    ranked.sort(
        key=lambda item: (
            item[0],
            safe_float(item[1].get("years_experience")) or 0,
        ),
        reverse=True,
    )

    ranked = ranked[:100]

    results = [
        public_candidate_record(row)
        for _, row in ranked
    ]

    lines = []

    for row in results:

        name = candidate_name(row) or "Name not listed"

        skills = ", ".join(
            get_skills(row.get("skills"))
        ) or "Not listed"

        title = row.get("current_title") or "Title not listed"

        experience = (
            row.get("years_experience")
            if row.get("years_experience") is not None
            else "Not listed"
        )

        city = row.get("city") or "Not listed"

        lines.append(
            f"- {name}: {title}; "
            f"Skills: {skills}; "
            f"Experience: {experience} years; "
            f"Location: {city}"
        )

    answer = (
        f"Found {len(results)} matching candidate(s):\n"
        + "\n".join(lines)
    )

    return results, answer


# ---------------------------------------------------------
# JOB SEARCH
# ---------------------------------------------------------

def get_jobs(cur):
    cur.execute(
        """
        SELECT job_id, title, description, source
        FROM jobs
        ORDER BY job_id DESC
        LIMIT 100
        """
    )

    return cur.fetchall()


# ---------------------------------------------------------
# MAIN CHATBOT FUNCTION
# ---------------------------------------------------------

def run_query(message):

    q = (message or "").strip()

    if not q:

        return {
            "answer": "Please enter a message so I can help.",
            "filters": {},
            "total": 0,
            "candidates": [],
        }

    # 1. Handle Gmail analytics first.
    email_intent = email_question_intent(q)

    if email_intent:

        try:
            return email_analytics_reply(email_intent)

        except Exception as exc:

            return {
                "answer": (
                    "I couldn't retrieve Gmail analytics. "
                    "Check Gmail authorization and configuration. "
                    f"Details: {type(exc).__name__}: {str(exc)[:200]}"
                ),
                "filters": {
                    "intent": email_intent,
                    "error": True,
                },
                "total": 0,
                "candidates": [],
            }

    # 2. Handle greetings.
    if is_general_greeting(q):

        return {
            "answer": general_reply(q),
            "filters": {"intent": "general"},
            "total": 0,
            "candidates": [],
        }

    # 3. Understand the recruitment query.
    filters = filters_for(q)

    intent = filters.get("intent")

    allowed_intents = {
        "search_candidates",
        "count_candidates",
        "count_jobs",
        "list_jobs",
    }

    if intent not in allowed_intents:

        return {
            "answer": general_reply(q),
            "filters": {"intent": "general"},
            "total": 0,
            "candidates": [],
        }

    # 4. Connect to the existing database.
    conn = connect()

    try:

        cur = conn.cursor(dictionary=True)

        # Count candidates.
        if intent == "count_candidates":

            cur.execute(
                "SELECT COUNT(*) AS total FROM candidates"
            )

            total = cur.fetchone()["total"]

            return {
                "answer": (
                    f"There are {total} candidates "
                    "in the database."
                ),
                "filters": filters,
                "total": total,
                "candidates": [],
            }

        # Count jobs.
        if intent == "count_jobs":

            cur.execute(
                "SELECT COUNT(*) AS total FROM jobs"
            )

            total = cur.fetchone()["total"]

            return {
                "answer": (
                    f"There are {total} jobs "
                    "in the database."
                ),
                "filters": filters,
                "total": total,
                "jobs": [],
                "candidates": [],
            }

        # List jobs.
        if intent == "list_jobs":

            jobs = get_jobs(cur)

            if not jobs:

                answer = "There are no jobs in the database yet."

            else:

                lines = [
                    f"{index}. {job.get('title') or 'Untitled job'} "
                    f"(Job ID: {job.get('job_id')})"
                    for index, job in enumerate(jobs, start=1)
                ]

                answer = (
                    f"Found {len(jobs)} job(s):\n"
                    + "\n".join(lines)
                )

            return {
                "answer": answer,
                "filters": filters,
                "total": len(jobs),
                "jobs": jobs,
                "candidates": [],
            }

        # Search candidates.
        results, answer = search_candidates(
            cur,
            q,
            filters,
        )

        return {
            "answer": answer,
            "filters": filters,
            "total": len(results),
            "candidates": results,
        }

    except Exception as exc:

        return {
            "answer": (
                "An error occurred while searching the recruitment "
                "database. "
                f"Details: {type(exc).__name__}: {str(exc)[:250]}"
            ),
            "filters": filters,
            "total": 0,
            "candidates": [],
        }

    finally:

        conn.close()
