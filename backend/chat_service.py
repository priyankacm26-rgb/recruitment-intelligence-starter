import json

import os

import re

from dotenv import load_dotenv

from .db import connect

from .email_analytics import get_today_email_analytics

load_dotenv()

# =========================================================

# 1. GENERAL HELPERS

# =========================================================

def normalize_text(value):

    if value is None:

        return ""

    value = str(value).lower()

    value = value.replace("’", "'")

    value = re.sub(r"[^a-z0-9'@.+#\s-]", " ", value)

    return re.sub(r"\s+", " ", value).strip()

def get_skills(value):

    if not value:

        return []

    if isinstance(value, list):

        return [str(x).strip() for x in value if x]

    if isinstance(value, str):

        try:

            parsed = json.loads(value)

            if isinstance(parsed, list):

                return [str(x).strip() for x in parsed if x]

        except (json.JSONDecodeError, TypeError):

            pass

        return [

            x.strip()

            for x in re.split(r"[,;|]", value)

            if x.strip()

        ]

    return []

def candidate_name(row):

    return " ".join(

        str(x).strip()

        for x in (row.get("first_name"), row.get("last_name"))

        if x

    ).strip()

def safe_float(value):

    try:

        return float(value) if value is not None else None

    except (ValueError, TypeError):

        return None

def is_count_question(message):

    return bool(re.search(

        r"\b(how many|count|total number|number of|total)\b",

        normalize_text(message),

    ))

# =========================================================

# 2. PYTHON NATURAL LANGUAGE UNDERSTANDING

# =========================================================

def fallback_understanding(message):

    """Parse recruitment questions locally without an external LLM."""

    q = normalize_text(message)

    result = {

        "intent": "search_candidates",

        "candidate_name": None,

        "requested_fields": [],

        "skills": [],

        "job_title": None,

        "city": None,

        "min_experience": None,

        "max_experience": None,

        "min_experience_exclusive": False,

        "maximum_exclusive": False,

        "max_experience_exclusive": False,  # Backward-compatible alias

        "has_comparator": False,

        "keywords": [],

    }

    field_patterns = {

        "skills": r"\b(skills?|technologies|technical skills)\b",

        "experience": r"\b(experience|years? of experience|yrs? experience)\b",

        "email": r"\b(e-?mail)\b",

        "phone": r"\b(phone|mobile|contact number)\b",

        "title": r"\b(job title|designation|role|position)\b",

        "location": r"\b(location|city|address)\b",

        "resume": r"\b(resume|cv)\b",

        "profile": r"\b(profile|full details|complete details)\b",

    }

    for field, pattern in field_patterns.items():

        if re.search(pattern, q):

            result["requested_fields"].append(field)

    known_skills = [

        "machine learning",

        "power bi",

        "power apps",

        "advanced excel",

        "data analysis",

        "data analytics",

        "natural language processing",

        "postgresql",

        "javascript",

        "communication",

        "snowflake",

        "redshift",

        "streamlit",

        "fastapi",

        "tableau",

        "pandas",

        "numpy",

        "python",

        "mysql",

        "excel",

        "azure",

        "aws",

        "java",

        "dax",

        "react",

        "docker",

        "git",

        "sql",

        "c",

    ]

    for skill in sorted(known_skills, key=len, reverse=True):

        if re.search(

            r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])",

            q,

        ):

            result["skills"].append(skill)

    known_titles = [

        "senior data analyst",

        "junior data analyst",

        "machine learning engineer",

        "software engineer",

        "software developer",

        "python developer",

        "power bi developer",

        "business analyst",

        "data analyst",

        "data engineer",

        "data scientist",

        "ai engineer",

        "bi analyst",

        "hr executive",

        "recruiter",

    ]

    for title in sorted(known_titles, key=len, reverse=True):

        if re.search(

            r"(?<![a-z0-9])" + re.escape(title) + r"(?![a-z0-9])",

            q,

        ):

            result["job_title"] = title

            break

    cities = {

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

    for city, normalized_city in cities.items():

        if re.search(

            r"(?<![a-z])" + re.escape(city) + r"(?![a-z])",

            q,

        ):

            result["city"] = normalized_city

            break

    # Detect count and job-list intents before candidate-name extraction.

    if is_count_question(q):

        if re.search(r"\b(jobs?|openings?|vacancies)\b", q):

            result["intent"] = "count_jobs"

        elif re.search(r"\b(candidates?|applicants?|people)\b", q):

            result["intent"] = "count_candidates"

    elif (

        re.search(r"\b(show|list|display|available|find)\b", q)

        and re.search(r"\b(jobs?|openings?|vacancies)\b", q)

    ):

        result["intent"] = "list_jobs"

    # Experience comparisons.

    # More than / less than are strict.

    # At least / at most are inclusive.

    # Exact values and ranges include their boundaries.

    number = r"(\d+(?:\.\d+)?)"

    between = re.search(

        r"\b(?:between|from)\s+"

        + number

        + r"\s+(?:and|to|-)\s+"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    shorthand_range = re.search(

        r"\b"

        + number

        + r"\s*(?:-|to)\s*"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    min_strict = re.search(

        r"\b(?:more than|over|above|greater than)\s+"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    min_inclusive = re.search(

        r"\b(?:at least|minimum|min)\s+"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    max_strict = re.search(

        r"\b(?:less than|below|under)\s+"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    max_inclusive = re.search(

        r"\b(?:at most|maximum|max|up to)\s+"

        + number

        + r"\s*(?:years?|yrs?)\b",

        q,

    )

    plus = re.search(

        r"\b" + number + r"\s*\+\s*(?:years?|yrs?)\b",

        q,

    )

    has_comparator = any((

        min_strict,

        min_inclusive,

        max_strict,

        max_inclusive,

        plus,

    ))

    result["has_comparator"] = has_comparator

    exact = None

    if not has_comparator and not (between or shorthand_range):

        exact = re.search(

            r"\b(?:exactly\s+|with\s+|having\s+)?"

            + number

            + r"\s*(?:years?|yrs?)(?:\s+of)?(?:\s+experience)?\b",

            q,

        )

    if between or shorthand_range:

        match = between or shorthand_range

        result["min_experience"] = float(match.group(1))

        result["max_experience"] = float(match.group(2))

    elif exact:

        value = float(exact.group(1))

        result["min_experience"] = value

        result["max_experience"] = value

    else:

        if min_strict:

            result["min_experience"] = float(min_strict.group(1))

            result["min_experience_exclusive"] = True

        elif min_inclusive or plus:

            match = min_inclusive or plus

            result["min_experience"] = float(match.group(1))

        if max_strict:

            result["max_experience"] = float(max_strict.group(1))

            result["maximum_exclusive"] = True

            result["max_experience_exclusive"] = True

        elif max_inclusive:

            result["max_experience"] = float(max_inclusive.group(1))

    if (

        result["min_experience"] is not None

        or result["max_experience"] is not None

    ):

        if "experience" not in result["requested_fields"]:

            result["requested_fields"].append("experience")

    # Never interpret count/list questions as candidate names.

    if result["intent"] != "search_candidates":

        return result

    # Candidate-name extraction continues in Part 2.

    name_query = q

    # Remove numbered-list prefixes such as 1. or 2)
    name_query = re.sub(
        r"^\s*\d+\s*[.)-]\s*",
        "",
        name_query,
    )

    name_query = re.sub(
        r"^(?:please\s+)?(?:find|search for|search|show|display|view|get|fetch|open|"
        r"lookup|look up|give me|tell me about|who is|what about)\s+",
        "",
        name_query,
    )

    name_query = re.sub(

        r"^(?:please\s+)?(?:find|search for|search|show|display|view|get|fetch|open|"

        r"lookup|look up|give me|tell me about|who is|what about)\s+",

        "",

        name_query,

    )

    name_query = re.sub(

        r"\b(skills?|technologies|technical skills|experience|years? of experience|"

        r"email|e mail|phone|mobile|contact number|profile|details|information|"

        r"resume|cv|title|designation|role|position|location|city|address|please)\b",

        " ",

        name_query,

    )

    name_query = re.sub(r"\bs\b", " ", name_query)

    name_query = re.sub(
        r"\b(all|candidates?|applicants?|people|with|having|who have|who has|and|or|"
        r"in|at|from|for|the|years?|yrs?|of|more|than|least|minimum|less|count|"
        r"total|number|jobs?|openings?|vacancies|available|maximum|most|over|above|"
        r"below|under|up to|between|to|exactly|find|show|me|at most|at least)\b",
        " ",
        name_query,
    )

    for term in known_skills + known_titles:

        name_query = re.sub(

            r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])",

            " ",

            name_query,

        )

    for city in cities:

        name_query = re.sub(

            r"(?<![a-z])" + re.escape(city) + r"(?![a-z])",

            " ",

            name_query,

        )

    name_query = re.sub(r"\b\d+(?:\.\d+)?\b", " ", name_query)
    name_query = name_query.replace("+", " ")

    name_query = re.sub(r"\s+", " ", name_query).strip(" .,-")

    reserved = {

        "python",

        "sql",

        "excel",

        "power bi",

        "data analyst",

        "data engineer",

        "candidate",

        "candidates",

        "all",

        "how many",

        "many",

        "jobs",

        "available jobs",

        "list available jobs",

        "exactly",

    }

    if (

        name_query

        and name_query not in reserved

        and len(name_query.split()) <= 4

    ):

        result["candidate_name"] = name_query

    return result

def understand_query_with_gemini(message):

    """

    Backward-compatible function name.

    Uses the local Python parser; no Gemini API is called.

    """

    return fallback_understanding(message), "python"

# =========================================================

# 3. GMAIL ANALYTICS

# =========================================================

def email_question_intent(message):

    q = normalize_text(message)

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

        r"\b(skills?|technologies)\b",

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

    if (

        asks_count

        and asks_today

        and re.search(r"\b(resumes?|cv files?)\b", q)

    ):

        return "count_today_resumes"

    if (

        asks_count or asks_today

    ) and re.search(r"\b(emails?|mails?|inbox|gmail)\b", q):

        return "count_today_emails"

    return None

def email_analytics_reply(intent):

    data = get_today_email_analytics()

    date_label = f"{data['date']} ({data['timezone']})"

    if intent == "count_today_emails":

        total = data["emails_received"]

        answer = (

            f"Today, {date_label}, I found {total} "

            "email message(s) in the Gmail inbox."

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

                f"I couldn't find successfully previewed PDF/DOCX "

                f"resume attachments in today's inbox ({date_label})."

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

                lines.append(

                    f"- {name} | "

                    f"Email: {item.get('email') or 'Not detected'} | "

                    f"Skills: {', '.join(skills) or 'Not detected'} | "

                    f"Subject: {item.get('subject') or 'No subject'}"

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

# =========================================================

# 4. CANDIDATE MATCHING

# =========================================================

def name_matches(row, requested_name):

    """

    Match requested name against actual database name.

    Supports full names and partial names.

    """

    requested = normalize_text(requested_name)

    full_name = normalize_text(candidate_name(row))

    if not requested or not full_name:

        return False

    if requested == full_name:

        return True

    requested_parts = requested.split()

    actual_parts = full_name.split()

    return all(

        any(

            part == actual

            or (len(part) >= 3 and part in actual)

            for actual in actual_parts

        )

        for part in requested_parts

    )

def candidate_matches_filters(row, filters):

    skills = [

        normalize_text(x)

        for x in get_skills(row.get("skills"))

    ]

    resume_text = normalize_text(row.get("resume_text"))

    # All requested skills must match.

    for requested_skill in filters.get("skills", []):

        skill = normalize_text(requested_skill)

        if not skill:

            continue

        if not (

            any(skill in existing for existing in skills)

            or skill in resume_text

        ):

            return False

    # Location.

    city = normalize_text(row.get("city"))

    requested_city = normalize_text(filters.get("city"))

    if requested_city and requested_city not in city:

        return False

    # Experience.

    experience = safe_float(row.get("years_experience"))

    minimum = safe_float(filters.get("min_experience"))

    maximum = safe_float(filters.get("max_experience"))

    min_exclusive = filters.get("min_experience_exclusive", False)

    max_exclusive = (
        filters.get("maximum_exclusive", False)
        or filters.get("max_experience_exclusive", False)
    )

    if minimum is not None:

        if experience is None:

            return False

        if min_exclusive and experience <= minimum:

            return False

        if not min_exclusive and experience < minimum:

            return False

    if maximum is not None:

        if experience is None:

            return False

        if max_exclusive and experience >= maximum:

            return False

        if not max_exclusive and experience > maximum:

            return False

    # Job title.

    title = normalize_text(row.get("current_title"))

    requested_title = normalize_text(filters.get("job_title"))

    if requested_title:

        if not (

            requested_title in title

            or requested_title in resume_text

        ):

            return False

    # Additional keywords.

    searchable = normalize_text(" ".join([

        candidate_name(row),

        row.get("current_title") or "",

        row.get("city") or "",

        row.get("resume_text") or "",

        " ".join(get_skills(row.get("skills"))),

    ]))

    for keyword in filters.get("keywords", []):

        keyword = normalize_text(keyword)

        if keyword and keyword not in searchable:

            return False

    return True

# =========================================================

# 5. FORMAT CANDIDATE INFORMATION

# =========================================================

def public_candidate_record(row):

    return {

        "candidate_id": row.get("candidate_id"),

        "first_name": row.get("first_name"),

        "last_name": row.get("last_name"),

        "email": row.get("email"),

        "phone": row.get("phone"),

        "city": row.get("city"),

        "current_title": row.get("current_title"),

        "years_experience": row.get("years_experience"),

        "skills": get_skills(row.get("skills")),

    }

def format_candidate(row, requested_fields=None):

    requested_fields = requested_fields or []

    name = candidate_name(row) or "Name not listed"

    skills = get_skills(row.get("skills"))

    if "skills" in requested_fields and len(requested_fields) == 1:

        return (

            f"{name}'s skills:\n"

            + (

                "\n".join(f"- {skill}" for skill in skills)

                if skills

                else "No skills are currently listed in the database."

            )

        )

    if "email" in requested_fields and len(requested_fields) == 1:

        return f"{name}'s email: {row.get('email') or 'Not listed'}"

    if "phone" in requested_fields and len(requested_fields) == 1:

        return f"{name}'s phone: {row.get('phone') or 'Not listed'}"

    if "experience" in requested_fields and len(requested_fields) == 1:

        experience = row.get("years_experience")

        return (

            f"{name}'s experience: {experience} years"

            if experience is not None

            else f"{name}'s experience is not listed."

        )

    if "title" in requested_fields and len(requested_fields) == 1:

        return (

            f"{name}'s job title: "

            f"{row.get('current_title') or 'Not listed'}"

        )

    if "location" in requested_fields and len(requested_fields) == 1:

        return (

            f"{name}'s location: "

            f"{row.get('city') or 'Not listed'}"

        )

    lines = [

        f"Candidate: {name}",

        f"Job title: {row.get('current_title') or 'Not listed'}",

        f"Email: {row.get('email') or 'Not listed'}",

        f"Phone: {row.get('phone') or 'Not listed'}",

        f"Location: {row.get('city') or 'Not listed'}",

        (

            f"Experience: {row.get('years_experience')} years"

            if row.get("years_experience") is not None

            else "Experience: Not listed"

        ),

        f"Skills: {', '.join(skills) if skills else 'Not listed'}",

    ]

    return "\n".join(lines)

# =========================================================

# 6. SEARCH CANDIDATES

# =========================================================

def search_candidates(cur, message, filters):

    cur.execute(

        """

        SELECT

            candidate_id,

            first_name,

            last_name,

            email,

            phone,

            city,

            current_title,

            years_experience,

            skills,

            resume_text

        FROM candidates

        ORDER BY candidate_id DESC

        """

    )

    all_rows = cur.fetchall()

    if not all_rows:

        return [], "No candidates are currently available."

    requested_name = filters.get("candidate_name")

    if requested_name:

        rows = [

            row

            for row in all_rows

            if name_matches(row, requested_name)

        ]

        if not rows:

            return [], (

                f"I couldn't find a candidate named "

                f"'{requested_name}' in the database."

            )

    else:

        rows = all_rows

    # Apply all remaining filters.

    rows = [

        row

        for row in rows

        if candidate_matches_filters(row, filters)

    ]

    if not rows:

        return [], (

            "I found the requested candidate name, but the stored "

            "record does not match all the additional filters."

        )

    if requested_name:

        rows.sort(

            key=lambda row: (

                normalize_text(candidate_name(row))

                != normalize_text(requested_name)

            )

        )

    results = [

        public_candidate_record(row)

        for row in rows[:100]

    ]

    requested_fields = filters.get("requested_fields", [])

    lines = [

        format_candidate(row, requested_fields)

        for row in rows[:100]

    ]

    answer = "\n\n".join(lines)

    if not requested_name:

        answer = (

            f"Found {len(results)} matching candidate(s):\n\n"

            + answer

        )

    return results, answer

# =========================================================

# 7. JOB SEARCH

# =========================================================

def get_jobs(cur, filters=None):
    """Return jobs, optionally filtered by the parsed job title."""
    cur.execute(
        """
        SELECT job_id, title, description, source
        FROM jobs
        ORDER BY job_id DESC
        """
    )
    jobs = cur.fetchall()
    requested_title = normalize_text((filters or {}).get("job_title"))
    if requested_title:
        jobs = [
            job for job in jobs
            if requested_title in normalize_text(job.get("title"))
        ]
    return jobs


# =========================================================

# 8. GENERAL CHAT

# =========================================================

def general_reply(message):

    message = (message or "").strip().lower()

    replies = {

        "hi": "Hi! How can I help you today?",

        "hello": "Hello! What can I help you with?",

        "hey": "Hey! I'm here to help.",

        "how are you": "I'm doing well. How can I help?",

        "good morning": "Good morning! What can I help you with?",

        "good afternoon": "Good afternoon! What can I help?",

        "good evening": "Good evening! How can I assist you?",

        "thank you": "You're welcome!",

        "thanks": "You're welcome!",

        "bye": "Goodbye!",

        "who are you": (

            "I'm your Recruitment Intelligence Assistant. "

            "I can search candidates, review skills, find jobs "

            "and check Gmail recruitment analytics."

        ),

        "what can you do": (

            "I can search candidates by name, skills, experience, "

            "job title and location; list jobs; and check Gmail analytics."

        ),

    }

    message = message.rstrip("!.?")

    if message in replies:

        return replies[message]

    return (

        "I can help with recruitment searches. Try asking me to find "

        "a candidate, search by skills, filter by experience or location, "

        "list available jobs, or check Gmail analytics."

    )

# =========================================================

# 9. MAIN CHAT QUERY

# =========================================================

def run_query(message):

    message = (message or "").strip()

    if not message:

        return {

            "answer": "Please enter a message.",

            "filters": {},

            "total": 0,

            "candidates": [],

        }

    # Gmail analytics.

    email_intent = email_question_intent(message)

    if email_intent:

        try:

            return email_analytics_reply(email_intent)

        except Exception as exc:

            return {

                "answer": (

                    "Unable to retrieve Gmail analytics. "

                    f"{type(exc).__name__}: {str(exc)[:200]}"

                ),

                "filters": {"intent": email_intent},

                "total": 0,

                "candidates": [],

            }

    # Greetings and general messages.

    if normalize_text(message) in {

        "hi",

        "hello",

        "hey",

        "thanks",

        "thank you",

        "bye",

        "good morning",

        "good afternoon",

        "good evening",

    }:

        return {

            "answer": general_reply(message),

            "filters": {"intent": "general"},

            "total": 0,

            "candidates": [],

        }

    # Parse the query using Python.

    filters, understanding_source = understand_query_with_gemini(

        message

    )

    filters["understanding_source"] = understanding_source

    intent = filters.get("intent")

    allowed_intents = {

        "search_candidates",

        "count_candidates",

        "count_jobs",

        "list_jobs",

    }

    if intent not in allowed_intents:

        return {

            "answer": general_reply(message),

            "filters": {"intent": "general"},

            "total": 0,

            "candidates": [],

        }

    conn = connect()

    try:

        cur = conn.cursor(dictionary=True)

        # Count candidates.

        if intent == "count_candidates":
            cur.execute(
                """
                SELECT candidate_id, first_name, last_name, email, phone,
                       city, current_title, years_experience, skills, resume_text
                FROM candidates
                """
            )
            candidate_rows = cur.fetchall()
            matching_rows = [
                row for row in candidate_rows
                if candidate_matches_filters(row, filters)
            ]
            total = len(matching_rows)
            has_filters = bool(
                filters.get("skills")
                or filters.get("city")
                or filters.get("min_experience") is not None
                or filters.get("max_experience") is not None
                or filters.get("job_title")
            )
            qualifier = "matching " if has_filters else ""
            return {
                "answer": f"There are {total} {qualifier}candidates in the database.",
                "filters": filters,
                "total": total,
                "candidates": [],
            }

        # Count jobs.

        if intent == "count_jobs":
            jobs = get_jobs(cur, filters)
            total = len(jobs)
            qualifier = "matching " if filters.get("job_title") else ""
            return {
                "answer": f"There are {total} {qualifier}jobs in the database.",
                "filters": filters,
                "total": total,
                "jobs": [],
                "candidates": [],
            }

        # List jobs.

        if intent == "list_jobs":

            jobs = get_jobs(cur, filters)

            if jobs:

                lines = [

                    (

                        f"{i}. {job.get('title') or 'Untitled'} "

                        f"(Job ID: {job.get('job_id')})"

                    )

                    for i, job in enumerate(jobs, 1)

                ]

                answer = (

                    f"Found {len(jobs)} job(s):\n"

                    + "\n".join(lines)

                )

            else:

                answer = "There are no jobs in the database yet."

            return {

                "answer": answer,

                "filters": filters,

                "total": len(jobs),

                "jobs": jobs,

                "candidates": [],

            }

        # Candidate search.

        results, answer = search_candidates(

            cur,

            message,

            filters,

        )

        return {

            "answer": answer,

            "filters": filters,

            "total": len(results),

            "candidates": results,

        }

    except Exception as exc:

        print(

            "Recruitment chatbot error:",

            type(exc).__name__,

            str(exc)[:300],

        )

        return {

            "answer": (

                "An error occurred while searching the database. "

                f"{type(exc).__name__}: {str(exc)[:200]}"

            ),

            "filters": filters,

            "total": 0,

            "candidates": [],

        }

    finally:

        conn.close()