import streamlit as st

def action(label, callback, *, key=None, primary=False, disabled=False, next_step=None):
    if st.button(label, key=key, type='primary' if primary else 'secondary', disabled=disabled, width='stretch'):
        try:
            callback()
            if next_step is not None:
                from audio_idp.ui.layout import STEPS
                st.session_state['navigate'] = {'step': STEPS[next_step]}
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))

@st.dialog('Delete workspace item')
def delete_dialog(workspace, id):
    item = workspace.store.get(id)
    if not item:
        st.info('This item has already been deleted.')
        return
    st.write(f"Delete **{item['data'].get('name', item['kind'])}**?")
    effects = {
        'batch':'Its recordings, audio, transcripts, draft classes, results and job history will be removed. Shared accepted classes remain.',
        'recording':'The uploaded audio, transcript, assignment and extracted results will be removed.',
        'transcript':'The audio remains. Classification and extraction will be removed.',
        'class':'Its fields and related results will be removed. Recordings remain and become Unclassified.',
        'field':'Extraction for this class will need to be refreshed.',
        'classification':'The assignment and its extracted results will be removed.',
        'extraction':'The extraction result will be removed. The recording and transcript remain.'}
    st.warning(effects.get(item['kind'], 'This action permanently removes the selected item.'))
    action('Delete permanently', lambda: workspace.store.delete(id), key='confirm-'+id, primary=True)

def delete_button(workspace, item):
    if st.button('Delete', key='delete-'+item['id']):
        delete_dialog(workspace, item['id'])

def name_of(store, id, fallback='Unclassified'):
    item = store.get(id) if id else None
    return item['data'].get('name',fallback) if item else fallback

@st.dialog('Delete selected items')
def bulk_delete_dialog(workspace, ids):
    st.warning(f'Permanently delete {len(ids)} selected items and their dependent data?')
    def delete():
        from audio_idp.services.deletion import delete_entities
        delete_entities(workspace.store,ids)
    action('Delete selected permanently',delete,primary=True)
