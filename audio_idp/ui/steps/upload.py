import streamlit as st
from audio_idp.services.transcription import FORMATS, LANGUAGES
from audio_idp.ui.common import action, delete_button, bulk_delete_dialog

def render(w, batch):
    st.subheader('Bring your conversations together')
    st.caption('Up to 10 recordings · 50 MB and 10 minutes each · English, Spanish and French')
    language = st.selectbox('Recording language', ['Auto-detect']+list(LANGUAGES))
    uploads = st.file_uploader('Drop audio files here', type=FORMATS, accept_multiple_files=True, key='uploads-'+batch)
    if uploads:
        def save():
            for file in uploads:
                w.upload(batch,file.name,file.getvalue(),language)
        action('Save recordings',save,primary=True)
    records = w.store.list('recording',batch=batch)
    if records:
        selected=st.multiselect('Select recordings for deletion',[r['id'] for r in records],format_func=lambda id:next(r['data']['name'] for r in records if r['id']==id))
        if selected and st.button('Delete selected recordings'): bulk_delete_dialog(w,selected)
    for r in records:
        with st.container(border=True):
            left,right=st.columns([5,1])
            left.write(r['data']['name'])
            left.caption(r['data']['language']+' · Saved locally')
            with right: delete_button(w,r)
    if records:
        action('Transcribe batch →',lambda:w.transcribe_batch(batch),primary=True,next_step=1)
