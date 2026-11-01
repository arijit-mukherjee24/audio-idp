"""Independent, simultaneously visible progress for every class in a batch."""
import html
import time
import streamlit as st

def snapshot(w, batch):
    assignments = w.store.list('classification', batch=batch)
    assigned_ids = {a['data']['class_id'] for a in assignments} - {None}
    catalog = w.classification_catalog(batch)
    classes = catalog + [c for c in w.classes() if c['id'] in assigned_ids and c['id'] not in {x['id'] for x in catalog}]
    batch_jobs = w.store.jobs(batch)
    classifying = any(j['kind']=='classify' and j['status'] in ('queued','running') for j in batch_jobs)
    jobs = w.store.jobs()
    output = []
    for c in classes:
        records = [w.store.get(a['parent']) for a in assignments if a['data']['class_id']==c['id']]
        names = [r['data']['name'] for r in records if r]
        job = next((j for j in jobs if j['kind']=='suggest fields' and j['target']==c['id']), None)
        fields = w.store.list('field', parent=c['id'])
        if classifying:
            state, label = 'waiting', 'Waiting for classification'
        elif not names:
            state, label = 'blocked', 'No assigned recordings'
        elif job:
            state = job['status']
            label = {'queued':'Queued','running':'Suggesting fields','completed':f'Ready · {len(fields)} fields',
                     'failed':'Suggestion failed','interrupted':'Interrupted','cancelled':'Cancelled — retry',
                     'superseded':'Waiting to retry'}.get(state,state.title())
        elif fields:
            state, label = 'completed', f'Ready · {len(fields)} saved fields'
        else:
            state, label = 'waiting', 'Waiting for suggestions'
        output.append({'class':c,'state':state,'label':label,'recordings':names,'job':job,'fields':fields})
    return output

@st.fragment(run_every=1)
def render(w, batch):
    statuses = snapshot(w,batch)
    ready = sum(s['state']=='completed' for s in statuses)
    running = sum(s['state']=='running' for s in statuses)
    queued = sum(s['state'] in ('queued','waiting') for s in statuses)
    st.caption(f'{len(statuses)} classes · {ready} ready · {running} suggesting · {queued} waiting')
    cards = []
    for s in statuses:
        names = ', '.join(s['recordings']) or 'Waiting for matching transcripts'
        elapsed = ''
        if s['state']=='running':
            elapsed = f" · {max(0,int(time.time()-s['job']['updated']))}s elapsed"
        cards.append(f'''<div class="class-progress-card {html.escape(s['state'])}">
          <h4>{html.escape(s['class']['data']['name'])}</h4>
          <span class="status">{html.escape(s['label']+elapsed)}</span>
          <div class="detail" title="{html.escape(names,quote=True)}">{len(s['recordings'])} recording(s) · {html.escape(names[:140])}</div>
          <div class="track"></div></div>''')
    st.markdown('<div class="class-progress-grid">'+''.join(cards)+'</div>',unsafe_allow_html=True)
