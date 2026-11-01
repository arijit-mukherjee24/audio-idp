"""Job history and controls for the batch currently being edited."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from audio_idp.ui.common import action, name_of


@st.fragment(run_every=2)
def render(w,batch):
    if not batch or not w.store.get(batch):
        st.info('Open a saved batch to view its jobs.')
        return
    st.title('Batch jobs')
    st.caption(name_of(w.store,batch)+' · Processing history for this batch')
    if st.button('← Back to batch'):
        st.session_state['navigate']={'batch':batch,'view':'Pipeline'}
        st.rerun()
    all_jobs=w.store.jobs(batch)
    a,b,c=st.columns(3)
    a.metric('Total jobs',len(all_jobs))
    b.metric('Active jobs',sum(j['status'] in ('queued','running') for j in all_jobs))
    c.metric('Jobs needing attention',sum(j['status'] in ('failed','interrupted') for j in all_jobs))
    left,right=st.columns([3,1])
    status=left.selectbox('Job status',['All','queued','running','completed','failed','interrupted','cancelled','superseded'],key='job-status-'+batch)
    matching=[j for j in all_jobs if status=='All' or j['status']==status]
    pages=max(1,(len(matching)+24)//25)
    page_key='job-page-'+batch+'-'+status
    if st.session_state.get(page_key,1)>pages:st.session_state[page_key]=pages
    page=int(right.number_input('Job page',min_value=1,max_value=pages,value=1,step=1,key=page_key))
    st.caption(f'{len(matching)} jobs · Page {page} of {pages}')
    current=matching[(page-1)*25:page*25]
    if not current:
        st.info('No jobs match this status.' if all_jobs else 'No processing jobs yet for this batch.')
        return
    rows=[]
    for job in current:
        rows.append({'Item':name_of(w.store,job['target'],'Batch operation'),
                     'Operation':job['kind'].title(),'Status':job['status'].title(),
                     'AI response':('Cached' if job.get('cache_hit') else 'Fresh') if job.get('request_hash') else '—',
                     'Updated (Asia/Kolkata)':datetime.fromtimestamp(job['updated'],ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S'),
                     'Details':job['error']})
    st.dataframe(rows,hide_index=True,width='stretch')
    by_id={j['id']:j for j in current}
    selected_key='job-detail-'+batch
    if st.session_state.get(selected_key) not in by_id:st.session_state[selected_key]=current[0]['id']
    with st.expander('Job details and actions'):
        selected=st.selectbox('Select job on this page',list(by_id),key=selected_key,
            format_func=lambda id:by_id[id]['kind'].title()+' · '+name_of(w.store,by_id[id]['target'],'Batch operation')+' · '+id[:8])
        job=by_id[selected]
        st.write(job['kind'].title()+' · '+job['status'])
        if job['error']:st.warning(job['error'])
        if job['status'] in ('queued','running'):
            action('Cancel job',lambda:w.store.job_status(job['id'],'cancelled'),key='cancel-'+job['id'])
        else:
            def delete():
                with w.store.connection() as db:db.execute('DELETE FROM jobs WHERE id=? AND batch=?',(job['id'],batch))
            action('Delete job history',delete,key='delete-job-'+job['id'])
