import streamlit as st

def render(w,recording,*,expanded=False):
    with st.expander('Create or assign a class manually',expanded=expanded):
        st.caption('Use this when no class was suggested, the file is unclassified, or you want to choose a different class.')
        available=w.store.list('class')
        if available:
            by_id={c['id']:c for c in available}
            id=st.selectbox('Choose an existing class',list(by_id),format_func=lambda id:by_id[id]['data']['name'],key='manual-existing-'+recording['id'])
            if st.button('Assign selected class',key='manual-assign-'+recording['id']):
                try:
                    w.confirm_class(recording['id'],id)
                    st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))
        with st.form('create-assign-'+recording['id']):
            name=st.text_input('New class name',max_chars=80)
            description=st.text_area('New class description',max_chars=400)
            if st.form_submit_button('Create & assign class',type='primary'):
                try:
                    w.manual_class(recording['id'],name,description)
                    st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))
