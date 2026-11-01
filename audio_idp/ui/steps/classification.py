import streamlit as st
from audio_idp.ui.common import action, name_of, delete_button

def render(w,batch):
    st.subheader('The right class for every conversation')
    force=st.checkbox('Reclassify completed recordings')
    action('Classify pending / retry failed',lambda:w.classify_batch(batch,force),primary=True,disabled=not w.classes() or not w.transcripts(batch))
    classes=w.classes()
    options=[None]+[c['id'] for c in classes]
    for t in w.transcripts(batch):
        r=w.store.get(t['parent'])
        a=w.store.get('cl-'+t['parent'])
        with st.container(border=True):
            st.write(r['data']['name'])
            current=a['data']['class_id'] if a else None
            chosen=st.selectbox('Assigned class',options,index=options.index(current) if current in options else 0,
                format_func=lambda id:name_of(w.store,id),key='assignment-'+r['id']+str(a['revision'] if a else 0))
            if a: st.caption(a['data']['reason'])
            action('Save assignment',lambda r=r,chosen=chosen:w.assign(r['id'],chosen),key='assign-'+r['id'])
            if a: delete_button(w,a)
    for c in classes:
        if any(a['data']['class_id']==c['id'] for a in w.store.list('classification',batch=batch)):
            action('Suggest fields · '+c['data']['name'],lambda c=c:w.suggest_fields(c['id'],batch),key='suggest-'+c['id'],next_step=4)
