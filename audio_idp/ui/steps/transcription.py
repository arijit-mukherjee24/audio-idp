import streamlit as st
from audio_idp.ui.common import action, delete_button, name_of

def render(w,batch):
    st.subheader('Every conversation, in focus')
    st.caption('Recordings run concurrently. Completed transcripts are saved immediately.')
    action('Transcribe pending / retry failed',lambda:w.transcribe_batch(batch),primary=True,disabled=not w.store.list('recording',batch=batch))
    for t in w.transcripts(batch):
        with st.expander(name_of(w.store,t['parent'],'Recording'), expanded=t['parent']==st.session_state.get('focus')):
            text=st.text_area('Transcript',value=t['data']['text'],key='text-'+t['id']+str(t['revision']),height=220)
            left,right=st.columns([3,1])
            with left: action('Save transcript edits',lambda t=t,text=text:w.edit_transcript(t,text),key='save-'+t['id'])
            with right: delete_button(w,t)
            if t['data'].get('edited'): st.caption('Edited text; original segment times have not been realigned.')
    if w.transcripts(batch):
        action('Suggest classes →',lambda:w.suggest_classes(batch),primary=True,next_step=2)
