"""Workspace landing page: saved batches only."""
import streamlit as st
from audio_idp.ui.common import delete_dialog
from audio_idp.ui.guided import stage_of
from audio_idp.ui.batch_json import render as view_json

def navigate(batch=None):
    st.session_state['navigate']={'batch':batch,'view':'Pipeline'}
    st.rerun()

@st.fragment(run_every=2)
def render(w):
    left,right=st.columns([3,1])
    with left:
        st.title('Your audio workspace.')
        st.caption('Open a batch to edit recordings, review results or view its processing jobs.')
    with right:
        if st.button('Create new batch',type='primary',width='stretch'):navigate()
    batches=w.store.list('batch')
    w.snapshots.sync()
    if w.snapshots.error:
        st.warning(w.snapshots.error)
        if st.button('Retry JSON backup'):w.snapshots.sync();st.rerun()
    st.subheader('Saved batches')
    if not batches:st.info('Create your first batch to upload recordings and start the guided flow.')
    for batch in reversed(batches):
        with st.container(border=True):
            title,summary,actions=st.columns([2,2,3])
            with title:
                st.write(batch['data']['name'])
                st.caption('Step '+str(stage_of(batch['data'])+1)+' of 4')
            with summary:
                recordings=w.store.list('recording',batch=batch['id'])
                done=w.store.list('extraction',batch=batch['id'])
                st.caption(f'{len(recordings)} recordings · {len(done)} extracted')
                st.caption('JSON backup needs attention' if w.snapshots.error else 'JSON backup saved automatically')
            with actions:
                open_column,view_column,json_column,delete_column=st.columns(4)
                if open_column.button('Open',key='open-batch-'+batch['id'],width='stretch'):navigate(batch['id'])
                if view_column.button('View JSON',key='view-json-'+batch['id'],width='stretch'):view_json(w,batch['id'])
                path=w.snapshots.path(batch['id'])
                if path.exists():
                    json_column.download_button('Download',path.read_bytes(),batch['id']+'.json','application/json',key='snapshot-'+batch['id'],width='stretch')
                if delete_column.button('Delete',key='dashboard-delete-'+batch['id'],width='stretch'):delete_dialog(w,batch['id'])
