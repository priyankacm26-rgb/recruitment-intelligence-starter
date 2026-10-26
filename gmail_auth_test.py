from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

credentials_file = Path("credentials.json")
token_file = Path("token.json")

if not credentials_file.is_file():
    raise SystemExit("ERROR: credentials.json is missing.")

flow = InstalledAppFlow.from_client_secrets_file(
    str(credentials_file.resolve()), SCOPES
)

creds = flow.run_local_server(port=0)

service = build("gmail", "v1", credentials=creds)
profile = service.users().getProfile(userId="me").execute()

token_file.write_text(creds.to_json(), encoding="utf-8")

print("\nGMAIL AUTHORIZATION SUCCESSFUL")
print("Connected Gmail address:", profile.get("emailAddress", "Unknown"))
print("Total messages:", profile.get("messagesTotal", "Unknown"))
print("token.json created:", token_file.is_file())
