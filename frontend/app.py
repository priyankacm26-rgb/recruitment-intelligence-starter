import os,requests,streamlit as st
from dotenv import load_dotenv
load_dotenv()
API=os.getenv('API_BASE_URL','http://127.0.0.1:8000')
st.set_page_config(page_title='Recruitment Intelligence',page_icon='🧭',layout='wide')
st.title('Recruitment Intelligence')
st.caption('Local development starter')
chat,candidates,resume,email=st.tabs(['Recruitment Chat','Candidates','Upload Resume','Email Ingestion'])
with chat:
    if 'history' not in st.session_state: st.session_state.history=[]
    for m in st.session_state.history:
        with st.chat_message(m['role']): st.write(m['content'])
        if m.get('rows'): st.dataframe(m['rows'],use_container_width=True,hide_index=True)
    q=st.chat_input('Ask: Find Python candidates in Bengaluru with at least 3 years')
    if q:
        st.session_state.history.append({'role':'user','content':q})
        with st.chat_message('user'): st.write(q)
        with st.chat_message('assistant'):
            try:
                with st.spinner('Checking database...'):
                    r=requests.post(API+'/chat',json={'message':q,'session_id':'local-session'},timeout=60); r.raise_for_status(); d=r.json()
                st.write(d['answer'])
                if d.get('candidates'): st.dataframe(d['candidates'],use_container_width=True,hide_index=True)
                st.caption('Filters: '+str(d.get('filters')))
                st.session_state.history.append({'role':'assistant','content':d['answer'],'rows':d.get('candidates',[])})
            except Exception as e: st.error(f'Chat request failed: {e}')
with candidates:
    try:
        r=requests.get(API+'/candidates',timeout=15); r.raise_for_status(); st.dataframe(r.json(),use_container_width=True,hide_index=True)
    except Exception as e: st.error(f'API unavailable: {e}')
with resume:
    f=st.file_uploader('Choose PDF or DOCX resume',type=['pdf','docx'])
    if f and st.button('Parse and save'):
        try:
            r=requests.post(API+'/resumes/upload',files={'file':(f.name,f.getvalue(),f.type)},timeout=120); r.raise_for_status(); st.success('Processed'); st.json(r.json())
        except Exception as e: st.error(f'Upload failed: {e}')
with email:
    st.warning('Gmail OAuth must be configured first. Use a dedicated test mailbox.')
    if st.button('Poll Gmail'):
        try:
            with st.spinner('Checking Gmail...'):
                r=requests.post(API+'/email/gmail/poll',timeout=180); r.raise_for_status(); st.json(r.json())
        except Exception as e: st.error(f'Gmail poll failed: {e}')
    if st.button('Refresh email logs'):
        try:
            r=requests.get(API+'/email/logs',timeout=20); r.raise_for_status(); st.dataframe(r.json(),use_container_width=True,hide_index=True)
        except Exception as e: st.error(f'Could not load logs: {e}')
