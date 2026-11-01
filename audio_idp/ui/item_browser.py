"""Persistent list selection with one detail item rendered at a time."""
import streamlit as st
from audio_idp.ui.file_progress import snapshot

def select_file(w,batch,stage,successful=False):
    rows=snapshot(w,batch) if batch else []
    if successful:
        rows=[r for r in rows if w.store.get('tr-'+r['id'])]
    if not rows:
        st.info('No completed transcripts yet.' if successful else 'Upload recordings to begin.')
        return None,None
    field={'upload':'Transcription','classes':'Class suggestions','classification':'Classification','fields':'Field suggestions','results':'Extraction'}[stage]
    by_id={r['id']:r for r in rows}
    key=f'selected-file-{stage}-{batch}'
    if st.session_state.get(key) not in by_id:
        st.session_state[key]=rows[0]['id']
    st.caption(f'{len(rows)} files · Select one to review')
    with st.container(height=460,border=False):
        id=st.radio('Files',list(by_id),format_func=lambda id:by_id[id]['File']+' · '+by_id[id][field],key=key,label_visibility='collapsed')
    return w.store.get(id),by_id[id]

def select_item(label,items,key):
    by_id={i['id']:i for i in items}
    if not by_id: return None
    if st.session_state.get(key) not in by_id: st.session_state[key]=next(iter(by_id))
    id=st.radio(label,list(by_id),format_func=lambda id:by_id[id]['data']['name']+(' · Accepted' if by_id[id]['data'].get('accepted') else ' · Suggested'),key=key)
    return by_id[id]
