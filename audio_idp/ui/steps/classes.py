import streamlit as st
from audio_idp.ui.common import action, delete_button

def editor(w,item,kind,parent=None):
    data=item['data']
    with st.container(border=True):
        st.caption(('ACCEPTED' if data['accepted'] else 'SUGGESTED')+' · '+kind.upper())
        with st.form('definition-'+item['id']):
            name=st.text_input('Class name' if kind=='class' else 'Field name',data['name'],max_chars=80 if kind=='class' else None)
            description=st.text_area('Description',data['description'],max_chars=400 if kind=='class' else None,height=100)
            if kind=='class': st.caption(f'{len(name)}/80 name · {len(description)}/400 description')
            accepted=st.checkbox('Accepted for processing',value=data['accepted'])
            if st.form_submit_button('Save decision',type='primary'):
                try:
                    w.definition(kind,name,description,accepted,id=item['id'],parent=parent)
                    st.rerun()
                except ValueError as exc: st.error(str(exc))
        if data.get('sources'):
            names=[w.store.get(id) for id in data['sources']]
            st.caption('Sources: '+', '.join(r['data']['name'] for r in names if r))
        left,right=st.columns([4,1])
        with right: delete_button(w,item)
        if kind=='class':
            targets=[c for c in w.classes() if c['id']!=item['id']]
            if targets:
                with st.expander('Merge into another class'):
                    target=st.selectbox('Destination',[c['id'] for c in targets],format_func=lambda id:next(c['data']['name'] for c in targets if c['id']==id),key='merge-'+item['id'])
                    action('Merge class',lambda:w.merge(item['id'],target),key='do-merge-'+item['id'])

def render(w,batch):
    st.subheader('Give your recordings a shared vocabulary')
    st.caption('Review, edit or merge suggestions. Only accepted classes are used for classification.')
    action('Generate / refresh class suggestions',lambda:w.suggest_classes(batch),disabled=not w.transcripts(batch))
    rows=[c for c in w.store.list('class') if c['data']['accepted'] or c['batch']==batch]
    for item in rows: editor(w,item,'class')
    with st.expander('Create a class manually'):
        with st.form('new-class'):
            name=st.text_input('Class name',max_chars=80)
            desc=st.text_area('Class description',max_chars=400)
            if st.form_submit_button('Create accepted class'):
                try:
                    w.definition('class',name,desc,True)
                    st.rerun()
                except ValueError as exc: st.error(str(exc))
    if w.classes(): action('Classify with accepted classes →',lambda:w.classify_batch(batch),primary=True,next_step=3,disabled=not w.transcripts(batch))
