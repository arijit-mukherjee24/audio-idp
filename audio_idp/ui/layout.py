import streamlit as st
from html import escape
from audio_idp.ui.common import action, delete_dialog, name_of
from audio_idp.services.deletion import reset_workspace

def style():
    st.markdown("""<style>
    .block-container {max-width:none;padding:4rem 2.5rem 2.5rem}
    @media(max-width:700px) {.block-container {padding:3.5rem 1rem 2rem}}
    h1,h1 * {font-weight:600!important;letter-spacing:-.04em;font-size:2.1rem!important}
    h2,h3 {font-weight:550!important;letter-spacing:-.02em}
    [data-testid="stSidebar"] {border-right:1px solid rgba(125,145,134,.25)}
    div.stButton>button {border-radius:9px;min-height:40px}
    [data-testid="stForm"] {border-color:rgba(125,145,134,.3);border-radius:12px}
    [data-testid="stRadio"] [role="radiogroup"] {gap:7px}
    [data-testid="stRadio"] label {border:1px solid rgba(125,145,134,.22);padding:11px 12px;border-radius:9px;width:100%;transition:background .15s}
    [data-testid="stRadio"] label:has(input:checked) {border-color:#6eab89;background:rgba(91,145,114,.13)}
    .journey-step {display:flex;align-items:center;gap:9px;opacity:.55;padding:10px 0;border-bottom:1px solid rgba(125,145,134,.3);margin-bottom:15px;font-size:.85rem}
    .journey-step span {border:1px solid rgba(125,145,134,.5);border-radius:50%;width:25px;height:25px;display:inline-flex;align-items:center;justify-content:center;font-size:.75rem}
    .journey-step.current {opacity:1;border-bottom:2px solid #6eab89}
    .journey-step.current span {background:rgba(91,145,114,.2);border-color:#6eab89}
    .journey-step.done {opacity:.85}
    .brand {font-size:.76rem;letter-spacing:.15em;opacity:.65;margin-bottom:10px}
    .batch-context {margin:0;font-size:.8rem;line-height:1.4;opacity:.7;overflow-wrap:anywhere}
    [data-testid="stMarkdownContainer"]:has(> .batch-context) {margin-bottom:0}
    mark {background:rgba(91,145,114,.3);color:inherit;border-radius:2px}
    .class-progress-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:8px 0 24px}
    .class-progress-card {border:1px solid rgba(125,145,134,.3);border-radius:10px;padding:16px;min-width:0}
    .class-progress-card h4 {font-size:1rem;margin:0 0 10px;overflow-wrap:anywhere}
    .class-progress-card .status {font-size:.8rem;display:inline-block;padding:3px 9px;border-radius:20px;background:rgba(91,145,114,.13)}
    .class-progress-card.running {border-color:#6eab89}
    .class-progress-card.failed {border-color:#bd8270}
    .class-progress-card .detail {font-size:.8rem;opacity:.7;margin-top:9px;overflow-wrap:anywhere}
    .class-progress-card .track {height:3px;background:rgba(125,145,134,.3);border-radius:4px;margin-top:12px;overflow:hidden}
    .class-progress-card.running .track:after {content:'';display:block;width:35%;height:100%;background:#6eab89;animation:field-work 1.8s infinite ease-in-out}
    .class-progress-card.completed .track {background:#6eab89}
    @keyframes field-work {0% {transform:translateX(-100%)} 100% {transform:translateX(400%)}}
    @media(prefers-reduced-motion:reduce) {.class-progress-card.running .track:after {animation:none}}
    </style>""",unsafe_allow_html=True)

@st.dialog('Delete all application data')
def reset_dialog(w):
    st.warning('Permanently delete all batches, audio, transcripts, classes, fields, results, jobs and search data.')
    st.write(f"{len(w.store.list('recording'))} recordings · {len(w.store.list('class'))} classes · {len(w.store.list('field'))} fields")
    models=st.checkbox('Also remove downloaded models (requires another download)')
    physically_running=any(not f.done() for f in w.jobs.futures)
    if models and physically_running:
        st.info('Wait for running operations to finish before removing model files.')
    confirm=st.text_input('Type DELETE ALL')
    def reset():
        reset_workspace(w,models)
        st.session_state.clear()
    action('Delete all data permanently',reset,primary=True,disabled=confirm!='DELETE ALL' or (models and physically_running))

def navigation(w):
    """Keep workspace navigation separate from the currently opened batch."""
    batch=st.session_state.get('batch')
    if batch and not w.store.get(batch):
        batch=None
        st.session_state['batch']=None
        st.session_state['view']='Dashboard'
    view=st.session_state.get('view','Dashboard')
    if view in ('Pipeline','Batch jobs'):
        back,context,actions=st.columns([1.5,3,1],vertical_alignment='center')
        with back:
            if st.button('← Back to dashboard',width='stretch'):
                st.session_state['navigate']={'batch':None,'view':'Dashboard'}
                st.rerun()
        title='EDITING BATCH / '+name_of(w.store,batch,'New batch') if batch else 'CREATE NEW BATCH'
        context.markdown(f'<p class="batch-context">{escape(title)}</p>',unsafe_allow_html=True)
        if batch:
            with actions.popover('Batch actions',width='stretch'):
                if st.button('Delete this batch',width='stretch'):delete_dialog(w,batch)
        views=['Pipeline']+(['Batch jobs'] if batch else [])
        if view not in views:st.session_state['view']='Pipeline'
    else:
        views=['Dashboard','Settings']
        if view not in views:st.session_state['view']='Dashboard'
    selected=st.radio('Workspace',views,key='view',horizontal=True,label_visibility='collapsed')
    return batch,selected

@st.fragment(run_every=1)
def progress(w,batch):
    jobs=w.store.jobs(batch)
    active=[j for j in jobs if j['status'] in ('queued','running')]
    signature=tuple((j['id'],j['status']) for j in jobs)
    key='job-signature-'+str(batch)
    previous=st.session_state.get(key,signature)
    st.session_state[key]=signature
    if active:
        st.caption(f'{len(active)} background jobs in progress · You can continue browsing')
    errors=[j for j in jobs if j['status'] in ('failed','interrupted')]
    if errors:
        with st.expander(f'{len(errors)} jobs need attention'):
            for job in errors[:10]: st.error(job['kind'].title()+': '+job['error'])
    w.advance(batch)
    if previous!=signature: st.rerun()

def render(w):
    if pending:=st.session_state.pop('navigate',None):
        for key,value in pending.items():
            st.session_state[key]=value
    if pending and 'guided_target' in pending and pending.get('batch'):
        b=w.store.get(pending['batch'])
        if b: w.store.save('batch',dict(b['data'],guided_stage=pending['guided_target'],flow_version=3),id=b['id'])
    style()
    batch,view=navigation(w)
    st.markdown('<div class="brand">AUDIO IDP / LISTEN. UNDERSTAND. EXTRACT.</div>',unsafe_allow_html=True)
    if view=='Dashboard':
        from audio_idp.ui.dashboard import render as dashboard
        dashboard(w)
        return
    if view=='Settings':
        st.subheader('Workspace settings')
        st.write('Manage the local AI response cache and workspace data.')
        stats=w.jobs.cache.stats()
        st.subheader('AI response cache')
        st.caption(f"{stats['entries']} saved responses · {stats['hits']} cache hits. Exact requests reuse validated responses across restarts.")
        if st.button('Clear AI response cache'):w.jobs.cache.clear();st.rerun()
        if st.button('Delete all application data',type='primary'): reset_dialog(w)
        return
    if view=='Batch jobs':
        from audio_idp.ui.batch_jobs import render as batch_jobs
        batch_jobs(w,batch)
        return
    if batch:
        progress(w,batch)
    from audio_idp.ui.guided import render as guided_render
    guided_render(w,batch)
