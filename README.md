# Recruitment Intelligence Starter

This creates a **new development database** and does not modify your uploaded `rcruiter_ai(2).sql` dump.

## Windows Setup

### 1. Create the development database

In MySQL Workbench, run:

```sql
sql/schema.sql
```

Make sure you open and execute the contents of `sql/schema.sql` from your project directory.

### 2. Set up Python

Open PowerShell and run:

```powershell
cd recruitment_intelligence_starter
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 3. Configure environment variables

Edit `.env` and enter your MySQL connection settings and Gemini API key.

Keep `.env` private and never commit it to Git.

### 4. Start the backend

Open Terminal 1 in the project root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

API documentation: http://127.0.0.1:8000/docs

### 5. Start the frontend

Open Terminal 2 in the same project root:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run frontend/app.py
```

Open the local Streamlit URL displayed in the terminal.

### 6. Test the application

Ask the chatbot:

`How many candidates?`

You can also open the API documentation to test the available endpoints.

### Gmail setup

Follow `docs/gmail_setup.md` to configure Gmail OAuth.

## Security and deployment

This is a development starter, not production-ready. Before exposing it publicly, add authentication and tenant authorization, file scanning, robust retries, and deployment secret management.