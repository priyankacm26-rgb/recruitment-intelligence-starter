
import os
import json
import requests
import streamlit as st

from dotenv import load_dotenv
from datetime import datetime


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

API = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


st.set_page_config(
    page_title="Recruitment Intelligence",
    page_icon="🧭",
    layout="wide",
)


# --------------------------------------------------
# Main heading
# --------------------------------------------------

st.title("🧭 Recruitment Intelligence")
st.caption("AI-powered recruitment assistant")


# --------------------------------------------------
# Utility functions
# --------------------------------------------------

def api_request(method, endpoint, **kwargs):
    """Send API request and handle errors."""

    url = f"{API}{endpoint}"

    try:
        response = requests.request(
            method=method,
            url=url,
            timeout=kwargs.pop("timeout", 30),
            **kwargs,
        )

        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return None

        return response.json()

    except requests.exceptions.Timeout:
        st.error("Backend request timed out. Please try again.")

    except requests.exceptions.ConnectionError:
        st.error(
            "Cannot connect to the backend. "
            "Check whether FastAPI is running."
        )

    except requests.exceptions.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else "unknown"
        )

        detail = ""

        if exc.response is not None:
            try:
                detail = exc.response.json().get("detail", "")
            except (ValueError, AttributeError):
                detail = exc.response.text[:500]

        st.error(
            f"API request failed ({status}): "
            f"{detail or str(exc)}"
        )

    except (
        ValueError,
        requests.exceptions.RequestException,
    ) as exc:
        st.error(f"Request failed: {exc}")

    return None


def parse_json_value(value, default=None):
    """Parse JSON stored as a string in MySQL."""

    if default is None:
        default = []

    if value is None:
        return default

    if isinstance(value, (list, dict)):
        return value

    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def format_datetime(value):
    """Format API datetime values for display."""

    if not value:
        return "Date unavailable"

    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        return value.strftime("%d %b %Y, %I:%M %p")

    except (ValueError, TypeError, AttributeError):
        return str(value)


def format_file_size(size):
    """Convert bytes into readable file size."""

    try:
        size = int(size or 0)

        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"

        if size >= 1024:
            return f"{size / 1024:.2f} KB"

        return f"{size} Bytes"

    except (ValueError, TypeError):
        return "Size unavailable"


def fetch_gmail_messages(folder="all", search=""):
    """Retrieve synchronized Gmail messages."""

    return api_request(
        "GET",
        "/email/gmail/messages",
        params={
            "folder": folder,
            "search": search,
            "limit": 100,
            "offset": 0,
        },
        timeout=60,
    )


# --------------------------------------------------
# Sidebar - Backend status
# --------------------------------------------------

with st.sidebar:

    st.subheader("Backend status")

    if st.button("Check connection", use_container_width=True):

        health = api_request(
            "GET",
            "/health",
            timeout=30,
        )

        if health:
            st.success("Backend is responding.")
            st.json(health)

    st.divider()

    st.caption("Backend API")
    st.code(API)


# --------------------------------------------------
# Main application tabs
# --------------------------------------------------

chat_tab, candidates_tab, resume_tab, email_tab = st.tabs(
    [
        "💬 Recruitment Chat",
        "👥 Candidates",
        "📄 Upload Resume",
        "📧 Email & Gmail Inbox",
    ]
)


# ==================================================
# 1. RECRUITMENT CHAT
# ==================================================

with chat_tab:

    st.subheader("Recruitment Chat")

    st.caption(
        "Example: Find Python candidates in Bengaluru "
        "with at least 3 years of experience."
    )

    if "history" not in st.session_state:
        st.session_state.history = []

    for message in st.session_state.history:

        with st.chat_message(message["role"]):

            st.write(message["content"])

            if message.get("rows"):
                st.dataframe(
                    message["rows"],
                    use_container_width=True,
                    hide_index=True,
                )

    question = st.chat_input(
        "Ask a recruitment question"
    )

    if question:

        st.session_state.history.append(
            {
                "role": "user",
                "content": question,
            }
        )

        with st.chat_message("user"):
            st.write(question)

        with st.chat_message("assistant"):

            with st.spinner(
                "Checking recruitment data..."
            ):

                result = api_request(
                    "POST",
                    "/chat",
                    json={
                        "message": question,
                        "session_id": "streamlit-session",
                    },
                    timeout=60,
                )

            if result is not None:

                answer = result.get(
                    "answer",
                    "No answer returned.",
                )

                candidate_rows = result.get(
                    "candidates",
                    [],
                )

                st.write(answer)

                if candidate_rows:

                    st.dataframe(
                        candidate_rows,
                        use_container_width=True,
                        hide_index=True,
                    )

                if result.get("filters") is not None:
                    st.caption(
                        f"Filters: {result['filters']}"
                    )

                st.session_state.history.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "rows": candidate_rows,
                    }
                )

    if st.button("Clear chat history"):

        st.session_state.history = []
        st.rerun()


# ==================================================
# 2. CANDIDATES
# ==================================================

with candidates_tab:

    st.subheader("Candidates")

    st.caption(
        "View candidate records available through the backend."
    )

    if st.button("Refresh candidates"):

        with st.spinner("Loading candidates..."):

            candidates_data = api_request(
                "GET",
                "/candidates",
                timeout=30,
            )

        if candidates_data is not None:

            if isinstance(candidates_data, list):

                if candidates_data:

                    st.dataframe(
                        candidates_data,
                        use_container_width=True,
                        hide_index=True,
                    )

                else:
                    st.info(
                        "No candidate records were returned."
                    )

            else:
                st.json(candidates_data)


# ==================================================
# 3. MANUAL RESUME UPLOAD
# ==================================================

with resume_tab:

    st.subheader("Upload Resume")

    st.caption(
        "Supported file types: PDF and DOCX."
    )

    uploaded_file = st.file_uploader(
        "Choose a resume",
        type=["pdf", "docx"],
        key="manual_resume_upload",
    )

    if uploaded_file is not None:

        st.write(
            f"Selected file: {uploaded_file.name}"
        )

        if st.button("Parse and save resume"):

            with st.spinner("Uploading resume..."):

                result = api_request(
                    "POST",
                    "/resumes/upload",
                    files={
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                            uploaded_file.type
                            or "application/octet-stream",
                        )
                    },
                    timeout=120,
                )

            if result is not None:

                st.success(
                    "Resume upload request completed."
                )

                st.json(result)


# ==================================================
# 4. EMAIL AND GMAIL INBOX
# ==================================================

with email_tab:

    st.subheader("📧 Gmail Inbox")

    st.caption(
        "View synchronized Gmail messages and review "
        "resume attachments before importing candidates."
    )

    # --------------------------------------------------
    # Gmail connection and synchronization
    # --------------------------------------------------

    st.markdown("### Gmail synchronization")

    sync_col, preview_col, logs_col = st.columns(3)

    with sync_col:

        if st.button(
            "🔄 Sync Gmail",
            use_container_width=True,
        ):

            with st.spinner(
                "Synchronizing Gmail messages..."
            ):

                sync_result = api_request(
                    "POST",
                    "/email/gmail/sync",
                    timeout=180,
                )

            if sync_result is not None:

                st.success(
                    "Gmail synchronization completed."
                )

                st.json(sync_result)

                st.session_state["gmail_force_refresh"] = True

    with preview_col:

        if st.button(
            "Preview Gmail",
            use_container_width=True,
        ):

            with st.spinner(
                "Loading Gmail preview..."
            ):

                preview = api_request(
                    "POST",
                    "/email/gmail/preview",
                    timeout=120,
                )

            if preview is not None:

                st.success(
                    "Gmail preview completed. "
                    "This action does not modify the database."
                )

                st.json(preview)

    with logs_col:

        if st.button(
            "Refresh Email Logs",
            use_container_width=True,
        ):

            with st.spinner(
                "Loading email logs..."
            ):

                logs = api_request(
                    "GET",
                    "/email/logs",
                    timeout=30,
                )

            if logs is not None:

                if isinstance(logs, list) and logs:

                    st.dataframe(
                        logs,
                        use_container_width=True,
                        hide_index=True,
                    )

                else:
                    st.info("No email logs available.")

    st.divider()

    # --------------------------------------------------
    # Inbox filters
    # --------------------------------------------------

    st.markdown("### Inbox")

    filter_col, search_col = st.columns([1, 2])

    with filter_col:

        folder_label = st.selectbox(
            "Email folder",
            [
                "All Emails",
                "Received",
                "Sent",
            ],
            key="gmail_folder_filter",
        )

    folder_mapping = {
        "All Emails": "all",
        "Received": "received",
        "Sent": "sent",
    }

    folder = folder_mapping[folder_label]

    with search_col:

        search_text = st.text_input(
            "Search emails",
            placeholder="Search sender, recipient or subject...",
            key="gmail_search",
        )

    # --------------------------------------------------
    # Load emails
    # --------------------------------------------------

    if st.button(
        "📥 Load / Refresh Inbox",
        use_container_width=True,
    ):

        st.session_state["gmail_force_refresh"] = True

    if (
        "gmail_messages_data" not in st.session_state
        or st.session_state.pop(
            "gmail_force_refresh",
            False,
        )
    ):

        with st.spinner("Loading Gmail messages..."):

            inbox_result = fetch_gmail_messages(
                folder=folder,
                search=search_text,
            )

        if inbox_result is not None:

            st.session_state["gmail_messages_data"] = (
                inbox_result
            )

            st.session_state["gmail_loaded_folder"] = folder

            st.session_state["gmail_loaded_search"] = (
                search_text
            )

    # Reload when filters change.
    if (
        st.session_state.get("gmail_loaded_folder") != folder
        or st.session_state.get("gmail_loaded_search") != search_text
    ):

        with st.spinner("Applying email filters..."):

            inbox_result = fetch_gmail_messages(
                folder=folder,
                search=search_text,
            )

        if inbox_result is not None:

            st.session_state["gmail_messages_data"] = (
                inbox_result
            )

            st.session_state["gmail_loaded_folder"] = folder

            st.session_state["gmail_loaded_search"] = (
                search_text
            )

    # --------------------------------------------------
    # Display inbox
    # --------------------------------------------------

    inbox_data = st.session_state.get(
        "gmail_messages_data"
    )

    if inbox_data is not None:

        messages = inbox_data.get("messages", [])

        total = inbox_data.get("total", 0)

        st.markdown("### Inbox Summary")

        metric1, metric2, metric3 = st.columns(3)

        with metric1:
            st.metric(
                "Total matching emails",
                total,
            )

        with metric2:

            received_count = sum(
                1 for message in messages
                if message.get("is_received")
            )

            st.metric(
                "Received on this page",
                received_count,
            )

        with metric3:

            sent_count = sum(
                1 for message in messages
                if message.get("is_sent")
            )

            st.metric(
                "Sent on this page",
                sent_count,
            )

        st.divider()

        if not messages:

            st.info(
                "No emails found for the selected filter."
            )

        else:

            st.markdown(
                f"### Emails ({len(messages)} displayed)"
            )

            for index, message in enumerate(messages):

                sender_name = (
                    message.get("sender_name")
                    or "Unknown sender"
                )

                sender_email = (
                    message.get("sender_email")
                    or "Unknown email"
                )

                subject = (
                    message.get("subject")
                    or "(No subject)"
                )

                message_id = message.get(
                    "gmail_message_id",
                    "",
                )

                if message.get("is_sent"):

                    email_type = "SENT"

                elif message.get("is_received"):

                    email_type = "RECEIVED"

                else:

                    email_type = "OTHER"

                attachments = message.get(
                    "attachments",
                    [],
                ) or []

                attachment_count = len(attachments)

                header = (
                    f"{'📤' if email_type == 'SENT' else '📩'} "
                    f"{subject} "
                    f"| {sender_name} "
                    f"| {email_type}"
                )

                with st.expander(
                    header,
                    expanded=False,
                ):

                    # Email information
                    st.markdown("#### Email details")

                    detail_col1, detail_col2 = st.columns(2)

                    with detail_col1:

                        st.write(
                            f"**Sender:** {sender_name}"
                        )

                        st.write(
                            f"**Email:** {sender_email}"
                        )

                        st.write(
                            f"**Subject:** {subject}"
                        )

                    with detail_col2:

                        st.write(
                            f"**Date:** "
                            f"{format_datetime(message.get('received_at'))}"
                        )

                        st.write(
                            f"**Direction:** {email_type}"
                        )

                        st.write(
                            f"**Attachments:** {attachment_count}"
                        )

                    # Recipients
                    recipients = parse_json_value(
                        message.get("recipients"),
                        [],
                    )

                    if recipients:

                        recipient_text = ", ".join(
                            [
                                (
                                    recipient.get("name", "")
                                    + " "
                                    + recipient.get("email", "")
                                ).strip()
                                for recipient in recipients
                                if isinstance(recipient, dict)
                            ]
                        )

                        st.write(
                            f"**Recipients:** {recipient_text}"
                        )

                    # Email snippet
                    st.markdown("#### Email snippet")

                    st.write(
                        message.get("snippet")
                        or "No message snippet available."
                    )

                    # Gmail labels
                    labels = parse_json_value(
                        message.get("labels"),
                        [],
                    )

                    if labels:

                        st.caption(
                            "Gmail labels: "
                            + ", ".join(labels)
                        )

                    st.divider()

                    # Attachments
                    st.markdown("#### 📎 Attachments")

                    if not attachments:

                        st.info(
                            "This email has no attachments."
                        )

                    else:

                        for attachment_index, attachment in enumerate(
                            attachments
                        ):

                            filename = attachment.get(
                                "filename",
                                "Unknown file",
                            )

                            mime_type = attachment.get(
                                "mime_type",
                                "Unknown type",
                            )

                            size = format_file_size(
                                attachment.get("size_bytes")
                            )

                            is_resume = bool(
                                attachment.get("is_resume")
                            )

                            st.markdown(
                                f"**📄 {filename}**"
                            )

                            file_col1, file_col2, file_col3 = (
                                st.columns(3)
                            )

                            with file_col1:
                                st.caption(
                                    f"Type: {mime_type}"
                                )

                            with file_col2:
                                st.caption(
                                    f"Size: {size}"
                                )

                            with file_col3:
                                st.caption(
                                    "Resume attachment"
                                    if is_resume
                                    else "Other attachment"
                                )

                            if (
                                is_resume
                                and filename.lower().endswith(
                                    (".pdf", ".docx")
                                )
                            ):

                                approval_key = (
                                    f"approve_{message_id}_"
                                    f"{attachment_index}"
                                )

                                button_key = (
                                    f"import_{message_id}_"
                                    f"{attachment_index}"
                                )

                                confirmed = st.checkbox(
                                    "I approve importing this resume "
                                    "into the candidate database.",
                                    key=approval_key,
                                )

                                if st.button(
                                    "✅ Approve & Import Resume",
                                    key=button_key,
                                    disabled=not confirmed,
                                ):

                                    with st.spinner(
                                        f"Importing {filename}..."
                                    ):

                                        import_result = api_request(
                                            "POST",
                                            "/email/gmail/import-approved",
                                            json={
                                                "message_id": message_id,
                                                "filename": filename,
                                                "approved": True,
                                            },
                                            timeout=180,
                                        )

                                    if import_result is not None:

                                        st.success(
                                            "Resume import request completed."
                                        )

                                        st.json(import_result)

                                        st.info(
                                            "Refresh Candidates to verify "
                                            "the candidate record."
                                        )

                            else:

                                st.caption(
                                    "This file is not marked as a "
                                    "supported resume for import."
                                )

                            if attachment_index < len(attachments) - 1:
                                st.divider()

                    st.caption(
                        f"Gmail message ID: {message_id}"
                    )

    else:

        st.info(
            "Click 'Load / Refresh Inbox' to retrieve "
            "your synchronized Gmail messages."
        )

    st.divider()

    st.caption(
        "Resume imports require explicit approval. "
        "Opening emails and viewing attachment metadata "
        "does not create candidate records."
    )
