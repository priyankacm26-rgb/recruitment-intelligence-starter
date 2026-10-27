
import os
import requests
import streamlit as st
from dotenv import load_dotenv

# Load local .env values for development.
# On Streamlit Community Cloud, configure variables in App Settings.
load_dotenv()

# Use the deployed Render API by default.
API = os.getenv(
    "API_BASE_URL",
    "https://recruitment-intelligence-api.onrender.com",
).rstrip("/")

st.set_page_config(
    page_title="Recruitment Intelligence",
    page_icon="🧭",
    layout="wide",
)

st.title("🧭 Recruitment Intelligence")
st.caption("AI-powered recruitment assistant")

# Reusable API request helper
def api_request(method, endpoint, **kwargs):
    """Send a request to the backend and handle API errors."""
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
        st.error("The backend request timed out. Please try again.")
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend. Check the Render service.")
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        detail = ""

        if exc.response is not None:
            try:
                detail = exc.response.json().get("detail", "")
            except (ValueError, AttributeError):
                detail = exc.response.text[:500]

        st.error(f"API request failed ({status}): {detail or str(exc)}")
    except (ValueError, requests.exceptions.RequestException) as exc:
        st.error(f"Request failed: {exc}")

    return None


# Show backend health
with st.sidebar:
    st.subheader("Backend status")

    if st.button("Check connection"):
        health = api_request("GET", "/health", timeout=30)

        if health:
            st.success("Backend is responding.")
            st.json(health)

    st.caption(f"API URL: {API}")


chat_tab, candidates_tab, resume_tab, email_tab = st.tabs(
    [
        "Recruitment Chat",
        "Candidates",
        "Upload Resume",
        "Email Ingestion",
    ]
)


# --------------------------------------------------
# Recruitment Chat
# --------------------------------------------------
with chat_tab:
    st.subheader("Recruitment Chat")
    st.caption(
        "Example: Find Python candidates in Bengaluru with at least 3 years"
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

    question = st.chat_input("Ask a recruitment question")

    if question:
        st.session_state.history.append(
            {"role": "user", "content": question}
        )

        with st.chat_message("user"):
            st.write(question)

        with st.chat_message("assistant"):
            with st.spinner("Checking recruitment data..."):
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
                answer = result.get("answer", "No answer returned.")
                candidate_rows = result.get("candidates", [])

                st.write(answer)

                if candidate_rows:
                    st.dataframe(
                        candidate_rows,
                        use_container_width=True,
                        hide_index=True,
                    )

                if result.get("filters") is not None:
                    st.caption(f"Filters: {result['filters']}")

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


# --------------------------------------------------
# Candidates
# --------------------------------------------------
with candidates_tab:
    st.subheader("Candidates")
    st.caption("View candidate records available through the backend.")

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
                    st.info("No candidate records were returned.")
            else:
                st.json(candidates_data)


# --------------------------------------------------
# Resume Upload
# --------------------------------------------------
with resume_tab:
    st.subheader("Upload Resume")
    st.caption("Supported file types: PDF and DOCX.")

    uploaded_file = st.file_uploader(
        "Choose a resume",
        type=["pdf", "docx"],
    )

    if uploaded_file is not None:
        st.write(f"Selected file: {uploaded_file.name}")

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
                st.success("Resume upload request completed.")
                st.json(result)


# --------------------------------------------------
# Email Ingestion
# --------------------------------------------------
with email_tab:
    st.subheader("Email Ingestion")

    st.warning(
        "Configure and authorize Gmail OAuth with a dedicated test mailbox "
        "before polling or importing messages."
    )

    st.caption(
        "Use preview first. Only import messages after reviewing the "
        "preview and confirming that the backend supports the intended workflow."
    )

    st.divider()

    st.markdown("**Preview Gmail messages**")

    if st.button("Preview Gmail"):
        with st.spinner("Requesting Gmail preview..."):
            preview = api_request(
                "POST",
                "/email/gmail/preview",
                timeout=120,
            )

        if preview is not None:
            st.json(preview)

    st.divider()

    st.markdown("**Poll Gmail**")

    if st.button("Poll Gmail"):
        with st.spinner("Polling Gmail..."):
            result = api_request(
                "POST",
                "/email/gmail/poll",
                timeout=180,
            )

        if result is not None:
            st.json(result)

    st.divider()

    st.markdown("**Refresh email logs**")

    if st.button("Refresh email logs"):
        with st.spinner("Loading email logs..."):
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
                st.json(logs)
