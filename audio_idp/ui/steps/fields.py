import streamlit as st
from audio_idp.ui.common import action
from audio_idp.ui.steps.classes import editor

def render(w,batch):
    st.subheader('Choose what matters')
    st.caption('Up to 10 suggested fields per class. Accept any subset; those definitions apply to every recording in that class.')
    classes=w.classes()
    if not classes:
        st.info('Accept classes and classify recordings first.')
        return
    class_id=st.selectbox('Class',[c['id'] for c in classes],format_func=lambda id:next(c['data']['name'] for c in classes if c['id']==id))
    count=sum(a['data']['class_id']==class_id for a in w.store.list('classification'))
    st.caption(f'{count} recordings share this class and field schema.')
    action('Suggest / refresh fields',lambda:w.suggest_fields(class_id,batch),disabled=count==0)
    for f in w.store.list('field',parent=class_id): editor(w,f,'field',class_id)
    with st.expander('Add a field manually'):
        with st.form('new-field-'+class_id):
            name=st.text_input('Field name')
            desc=st.text_area('Field description')
            if st.form_submit_button('Create accepted field'):
                try:
                    w.definition('field',name,desc,True,parent=class_id)
                    st.rerun()
                except ValueError as exc: st.error(str(exc))
    action('Extract accepted fields →',lambda:w.extract_batch(batch),primary=True,next_step=5,disabled=not any(w.fields(c['id']) for c in classes))
