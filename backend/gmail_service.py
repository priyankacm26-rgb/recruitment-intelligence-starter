import base64,os
from pathlib import Path
from email.utils import parseaddr
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from .db import connect
from .resume_service import save_resume
load_dotenv()
SCOPES=['https://www.googleapis.com/auth/gmail.readonly']
def service():
    token=Path(os.getenv('GMAIL_TOKEN_FILE','token.json')); credfile=Path(os.getenv('GMAIL_CREDENTIALS_FILE','credentials.json')); creds=None
    if token.exists(): creds=Credentials.from_authorized_user_file(str(token),SCOPES)
    if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
    if not creds or not creds.valid:
        if not credfile.exists(): raise RuntimeError('credentials.json missing; follow docs/gmail_setup.md')
        flow=InstalledAppFlow.from_client_secrets_file(str(credfile),SCOPES); creds=flow.run_local_server(port=0); token.write_text(creds.to_json())
    return build('gmail','v1',credentials=creds,cache_discovery=False)
def decode(data): return base64.urlsafe_b64decode(data+'='*(-len(data)%4))
def log(mid,sender,subject,name,status,cid=None,error=None):
    c=connect()
    try:
        cur=c.cursor(); cur.execute("""INSERT INTO email_ingestion_logs(provider,provider_message_id,sender,subject,attachment_name,status,candidate_id,error_message,received_at)
        VALUES('gmail',%s,%s,%s,%s,%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE status=VALUES(status),candidate_id=VALUES(candidate_id),error_message=VALUES(error_message)""",(mid,sender,subject,name,status,cid,error)); c.commit()
    finally: c.close()
def poll_gmail():
    api=service(); query=os.getenv('GMAIL_QUERY','has:attachment newer_than:7d')
    msgs=api.users().messages().list(userId='me',q=query,maxResults=25).execute().get('messages',[])
    out={'scanned':len(msgs),'processed':0,'duplicates':0,'failed':0}
    for ref in msgs:
        mid=ref['id']; msg=api.users().messages().get(userId='me',id=mid,format='full').execute()
        headers={h['name'].lower():h['value'] for h in msg.get('payload',{}).get('headers',[])}
        sender=parseaddr(headers.get('from',''))[1]; subject=headers.get('subject',''); parts=[]
        def walk(p):
            if p.get('filename'): parts.append(p)
            for child in p.get('parts',[]) or []: walk(child)
        walk(msg.get('payload',{}))
        resumes=[p for p in parts if Path(p['filename']).suffix.lower() in ('.pdf','.docx')]
        if not resumes:
            log(mid,sender,subject,None,'skipped',error='No supported resume attachment'); continue
        for p in resumes:
            name=p['filename']; c=connect()
            try:
                cur=c.cursor(); cur.execute('SELECT ingestion_id FROM email_ingestion_logs WHERE provider=%s AND provider_message_id=%s AND attachment_name=%s',('gmail',mid,name))
                if cur.fetchone(): out['duplicates']+=1; continue
            finally: c.close()
            try:
                body=p.get('body',{})
                if body.get('attachmentId'):
                    att=api.users().messages().attachments().get(userId='me',messageId=mid,id=body['attachmentId']).execute(); raw=decode(att['data'])
                else: raw=decode(body.get('data',''))
                saved=save_resume(name,raw,'gmail'); log(mid,sender,subject,name,'processed',saved['candidate_id']); out['processed']+=1
            except Exception as e:
                log(mid,sender,subject,name,'failed',error=str(e)[:800]); out['failed']+=1
    return out
