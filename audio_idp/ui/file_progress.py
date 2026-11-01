"""File-level projections of local jobs and shared class-level AI operations."""
import streamlit as st

def phase(job, ready=False, waiting='Not started'):
    if job and job['status'] in ('queued','running','failed','interrupted','cancelled'):
        return {'queued':'Queued','running':'Running','failed':'Failed','interrupted':'Interrupted','cancelled':'Cancelled'}[job['status']]
    return 'Complete' if ready else waiting

def snapshot(w,batch):
    jobs=w.store.jobs(batch)
    all_jobs=w.store.jobs()
    def latest(kind,target,shared=False):
        return next((j for j in (all_jobs if shared else jobs) if j['kind']==kind and j['target']==target),None)
    output=[]
    for r in w.store.list('recording',batch=batch):
        id=r['id']
        t=w.store.get('tr-'+id)
        assignment=w.store.get('cl-'+id)
        c=w.store.get(assignment['data']['class_id']) if assignment and assignment['data']['class_id'] else None
        result=w.store.get('ex-'+id)
        class_job=latest('suggest class',id) or latest('suggest classes',batch)
        transcription_job=latest('transcribe',id)
        classification_job=latest('classify',id)
        extraction_job=latest('extract',id)
        field_job=latest('suggest fields',c['id'],True) if c else None
        fields=w.store.list('field',parent=c['id']) if c else []
        accepted=[f for f in fields if f['data']['accepted']]
        discovery=phase(class_job, bool(assignment or (class_job and class_job['status']=='completed')), 'Waiting for suggestions') if t else 'Waiting for transcript'
        classification=phase(classification_job,assignment is not None,'Waiting for class assignment') if t else 'Waiting for transcript'
        if assignment and not c and classification=='Complete': classification='Unclassified — review'
        if c:
            field_state=phase(field_job,bool(fields) or bool(field_job and field_job['status']=='completed'),'Waiting for suggestions')
            if field_state=='Complete': field_state=f'Ready · {len(fields)} fields'
            field_state+=f" · {c['data']['name']} (shared)"
        else: field_state='Waiting for class assignment' if not assignment else 'Unclassified — review'
        if not t: extraction='Waiting for transcript'
        elif not c: extraction='Waiting for class assignment' if not assignment else 'Unclassified — skipped'
        elif not accepted and not extraction_job: extraction='Waiting for field approval'
        else: extraction=phase(extraction_job,result is not None,'Ready to extract' if accepted else 'Waiting for field approval')
        errors=[j['error'] for j in (transcription_job,class_job if t else None,classification_job,field_job,extraction_job) if j and j['status'] in ('failed','interrupted','cancelled') and j['error']]
        output.append({'id':id,'File':r['data']['name'],'Upload':'Saved','Transcription':phase(transcription_job,t is not None,'Ready to transcribe'),
                       'Class suggestions':discovery+(' · '+c['data']['name'] if c else ''),'Classification':classification,
                       'Assigned class':c['data']['name'] if c else '—','Field suggestions':field_state,'Extraction':extraction,
                       'Values':sum(v.get('value') is not None for v in result['data']['fields'].values()) if result else 0,'Details':' | '.join(dict.fromkeys(errors))})
    return output

@st.fragment(run_every=1)
def render(w,batch,stage='upload'):
    rows=snapshot(w,batch)
    if not rows: return
    columns={
        'upload':['File','Upload','Transcription'],
        'classes':['File','Transcription','Class suggestions'],
        'classification':['File','Classification','Assigned class'],
        'fields':['File','Assigned class','Field suggestions'],
        'extraction':['File','Assigned class','Extraction','Values'],
        'all':['File','Upload','Transcription','Class suggestions','Classification','Assigned class','Field suggestions','Extraction','Values']}
    selected=columns.get(stage,columns['all'])
    st.subheader('Every file, at a glance')
    if any(row['Details'] for row in rows): selected=selected+['Details']
    st.dataframe([{key:row[key] for key in selected} for row in rows],hide_index=True,width='stretch',height=min(440,40+36*len(rows)),
                 column_config={'File':st.column_config.TextColumn(width='medium'),'Details':st.column_config.TextColumn(width='large')})
    if stage=='fields': st.caption('Field discovery runs once per class. Files in the same class share that request and its progress.')
    elif stage=='classes': st.caption('Each file gets its own class suggestion and automatic assignment. Files can share the same class.')
