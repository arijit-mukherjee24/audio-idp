"""Formatted, read-only JSON preview for a saved batch."""
import streamlit as st


@st.dialog('Batch JSON',width='large')
def render(w,batch):
    document=w.snapshots.document(batch)
    if document is None:
        st.info('This batch is no longer available.')
        return
    st.caption(document['batch']['name'])
    with st.container(height=520,border=False):
        st.json(document,expanded=2)
