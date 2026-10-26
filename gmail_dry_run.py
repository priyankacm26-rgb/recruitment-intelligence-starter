from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os

load_dotenv(Path(".env"))

token_path = Path(os.getenv("GMAIL_TOKEN_FILE", "token.json"))
if not token_path.is_absolute():
    token_path = Path.cwd() / token_path

if not token_path.is_file():
    raise SystemExit("ERROR: token.json not found.")

creds = Credentials.from_authorized_user_file(
    str(token_path),
    ["https://www.googleapis.com/auth/gmail.readonly"]
)

service = build("gmail", "v1", credentials=creds)

query = os.getenv("GMAIL_QUERY", "newer_than:30d")
result = service.users().messages().list(
    userId="me", q=query, maxResults=10
).execute()

messages = result.get("messages", [])
print("Gmail dry run — no database changes")
print("Search query:", query)
print("Messages found:", len(messages))

for item in messages:
    msg = service.users().messages().get(
        userId="me", id=item["id"], format="full"
    ).execute()

    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    print("\nSubject:", headers.get("subject", "(no subject)"))
    print("From:", headers.get("from", "(unknown sender)"))

    attachments = []
    def walk(part):
        filename = part.get("filename", "")
        if filename:
            attachments.append(filename)
        for child in part.get("parts", []):
            walk(child)

    walk(msg.get("payload", {}))
    print("Attachments:", ", ".join(attachments) if attachments else "None")

print("\nDry run complete.")
