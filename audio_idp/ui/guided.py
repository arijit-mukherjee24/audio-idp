"""Four list/detail screens. Parallel work continues independently of selection."""
import hashlib
import streamlit as st
from audio_idp.services.transcription import LANGUAGES, FORMATS, MAX_BYTES
from audio_idp.services.review import candidates
from audio_idp.ui.item_browser import select_file, select_item
from audio_idp.ui.common import delete_button, name_of

STAGES=['Upload & transcribe','Classes & assignment','Fields','Results']

def move(w,batch,stage):
    b=w.store.get(batch)
    w.store.save('batch',dict(b['data'],guided_stage=stage),id=batch)
    st.rerun()

def call(callback):
    try:
        callback()
        st.rerun()
    except (ValueError,OSError) as exc:st.error(str(exc))

def busy(w,batch,kinds):
    return any(j['kind'] in kinds and j['status'] in ('queued','running') for j in w.store.jobs(batch))

def latest(w,batch,kind,target=None):
    return next((j for j in w.store.jobs(batch) if j['kind']==kind and (target is None or j['target']==target)),None)

def stepper(stage):
    for i,(column,name) in enumerate(zip(st.columns(4),STAGES)):
        with column:
            status='done' if i<stage else 'current' if i==stage else ''
            st.markdown(f'<div class="journey-step {status}"><span>{"✓" if i<stage else i+1}</span>{name}</div>',unsafe_allow_html=True)

def transcript(w,recording,editable=False):
    t=w.store.get('tr-'+recording['id'])
    if not t:
        st.info('The transcript will appear here when this file finishes processing.')
        return
    st.caption('TRANSCRIPT'+(' · Edited' if t['data'].get('edited') else ''))
    if editable:
        with st.form('transcript-'+t['id']+'-'+str(t['revision'])):
            text=st.text_area('Transcript text',t['data']['text'],height=370,label_visibility='collapsed')
            if st.form_submit_button('Save transcript edits'):
                call(lambda:w.edit_transcript(t,text))
    else:
        with st.container(height=360,border=True):st.text(t['data']['text'])

def file_header(recording,status,field):
    st.subheader(recording['data']['name'])
    st.caption(status[field])
    if status['Details']:st.warning(status['Details'])

def intake(w,batch):
    existing=w.store.list('recording',batch=batch) if batch else []
    with st.expander('Add recordings',expanded=not existing):
        name=st.text_input('Batch name',name_of(w.store,batch,'New recordings') if batch else 'New recordings')
        files=st.file_uploader('Upload audio files',type=FORMATS,accept_multiple_files=True,key='intake-'+str(batch))
        language=st.selectbox('Audio language',['Auto-detect']+list(LANGUAGES))
        st.caption('10 recordings per batch · 50 MB and 10 minutes each')
        if files:
            for f in files:st.caption(f.name+' · Received, ready to save')
        active=bool(batch and busy(w,batch,{'transcribe','suggest class'}))
        if st.button('Upload & transcribe',type='primary',width='stretch',disabled=(not files and not existing) or active):
            def start():
                content=[(f.name,f.getvalue()) for f in files]
                if not name.strip():raise ValueError('Enter a batch name.')
                hashes={r['data']['hash'] for r in existing}
                for filename,data in content:
                    if not data or len(data)>MAX_BYTES:raise ValueError(filename+': choose nonempty audio no larger than 50 MB.')
                    hashes.add(hashlib.sha256(data).hexdigest())
                if len(hashes)>10:raise ValueError('Choose no more than 10 different recordings.')
                id=batch or w.batch(name)
                with st.status('Saving recordings…',expanded=True) as status:
                    for filename,data in content:
                        w.upload(id,filename,data,language)
                        st.write(filename+' · Saved (identical audio reused)')
                    status.update(label='Recordings saved',state='complete')
                b=w.store.get(id)
                w.store.save('batch',dict(b['data'],name=name.strip(),guided_stage=0,flow_version=3),id=id)
                st.session_state['navigate']={'batch':id,'view':'Pipeline'}
                w.transcribe_batch(id)
            call(start)

def upload(w,batch):
    st.title('Listen to one conversation at a time.')
    st.caption('All files keep processing in the background. Choose a file to review its transcript.')
    left,right=st.columns([1,2.3],gap='large')
    with left:
        intake(w,batch)
        st.subheader('Recordings')
        r,status=select_file(w,batch,'upload')
    with right,st.container(border=True):
        if r:
            file_header(r,status,'Transcription')
            transcript(w,r,editable=True)
            with st.expander('File actions'):delete_button(w,r)
        else:st.info('Add your recordings to see the first file here.')
    if batch:
        ready=bool(w.transcripts(batch)) and not busy(w,batch,{'transcribe'})
        if st.button('Continue to class suggestions →',type='primary',disabled=not ready):move(w,batch,1)

def class_detail(w,c,batch,recording=None):
    with st.form('class-detail-'+c['id']+'-'+str(c['revision'])):
        name=st.text_input('Class name',c['data']['name'],max_chars=80)
        description=st.text_area('Class description',c['data']['description'],max_chars=400,height=190)
        st.caption('Maximum 80 characters for the name; 400 for the description.')
        confirmed=False
        if recording:
            assignment=w.store.get('cl-'+recording['id'])
            confirmed=st.checkbox('Assign this class to this file',value=bool(assignment and assignment['data']['class_id']==c['id']))
        if st.form_submit_button('Save class decision',type='primary'):
            def save():
                w.definition('class',name,description,True,id=c['id'])
                if confirmed:w.confirm_class(recording['id'],c['id'])
                elif recording:
                    assignment=w.store.get('cl-'+recording['id'])
                    if assignment and assignment['data']['class_id']==c['id']:w.assign(recording['id'],None)
            call(save)
    st.caption('Shared class · Changes apply to every recording using this definition.')
    with st.expander('Class actions'):
        delete_button(w,c)
        targets=[x for x in w.classes() if x['id']!=c['id']]
        if targets:
            target=st.selectbox('Merge into',[x['id'] for x in targets],format_func=lambda id:name_of(w.store,id),key='merge-detail-'+c['id'])
            if st.button('Merge classes',key='merge-action-'+c['id']):call(lambda:w.merge(c['id'],target))

def classes(w,batch):
    st.title('Find the right class for each file.')
    st.caption('Suggestions are assigned automatically. Review a file, refresh its suggestion, or choose a class yourself.')
    left,right=st.columns([1,2.3],gap='large')
    with left:
        st.subheader('Transcribed files')
        r,status=select_file(w,batch,'classes',successful=True)
    with right,st.container(border=True):
        if r:
            file_header(r,status,'Class suggestions')
            job=latest(w,batch,'suggest class',r['id'])
            running=bool(job and job['status'] in ('queued','running'))
            if running:st.info('Finding a class for this file… Its current assignment is kept until the new suggestion is ready.')
            assignment=w.store.get('cl-'+r['id'])
            assigned=w.store.get(assignment['data']['class_id']) if assignment and assignment['data']['class_id'] else None
            if assigned:st.success('Assigned: '+assigned['data']['name'])
            if assignment:st.caption(assignment['data']['reason'])
            if st.button('Refresh suggestion for this file',disabled=running,key='refresh-class-'+r['id']):
                call(lambda:w.suggest_file(r['id'],refresh=True))
            st.caption('Refresh asks AI again for this file and replaces its assignment when successful. Other files are unchanged.')
            rows=candidates(w.store,r['id'])
            if rows:
                choices,detail=st.columns([1,1.6],gap='medium')
                with choices:c=select_item('Suggested classes',rows,'selected-class-'+batch+'-'+r['id'])
                with detail:
                    manual=r['id'] in c['data'].get('manual_sources',[])
                    st.caption('Linked manually' if manual else 'Suggested for this recording')
                    class_detail(w,c,batch,r)
            else:
                st.info('No class suggested yet. Refresh this file or assign a class manually below.')
                assignment=w.store.get('cl-'+r['id'])
                prior=w.store.get(assignment['data']['class_id']) if assignment and assignment['data']['class_id'] else None
                if prior:
                    st.caption('Previously assigned class (not a new suggestion)')
                    class_detail(w,prior,batch,r)
            from audio_idp.ui.manual_class import render as manual_class
            manual_class(w,r,expanded=not rows)
            with st.expander('Selected transcript'):transcript(w,r)
        else:st.info('Complete a transcription before reviewing suggested classes.')
    a,b=st.columns([1,2])
    with a:
        if st.button('← Upload'):move(w,batch,0)
    with b:
        ready=any(a['data']['class_id'] for a in w.store.list('classification',batch=batch))
        if st.button('Continue to field suggestions →',type='primary',width='stretch',disabled=not ready or busy(w,batch,{'suggest class'})):
            move(w,batch,2)

def field_detail(w,f,class_id):
    with st.form('field-detail-'+f['id']+'-'+str(f['revision'])):
        name=st.text_input('Field name',f['data']['name'])
        description=st.text_area('Field description',f['data']['description'],height=190)
        accepted=st.checkbox('Accepted for extraction',value=f['data']['accepted'])
        if st.form_submit_button('Save field decision',type='primary'):
            call(lambda:w.definition('field',name,description,accepted,id=f['id'],parent=class_id))
    with st.expander('Field actions'):delete_button(w,f)

def fields(w,batch):
    st.title('Choose the details to extract.')
    st.caption('Select a file to review its class’s shared fields. Approve one field at a time.')
    left,right=st.columns([1,2.3],gap='large')
    with left:
        st.subheader('Transcribed files')
        r,status=select_file(w,batch,'fields',successful=True)
    with right,st.container(border=True):
        if r:
            file_header(r,status,'Field suggestions')
            a=w.store.get('cl-'+r['id'])
            c=w.store.get(a['data']['class_id']) if a and a['data']['class_id'] else None
            if c:
                st.caption('CLASS / '+c['data']['name'])
                st.write(c['data']['description'])
                st.caption('These definitions apply to all files in this class; each file gets its own extracted values.')
                items=w.store.list('field',parent=c['id'])
                if items:
                    choices,detail=st.columns([1,1.6],gap='medium')
                    with choices:f=select_item('Suggested fields',items,'selected-field-'+batch+'-'+c['id'])
                    with detail:field_detail(w,f,c['id'])
                else:st.info('Suggestions will appear here when this class finishes processing.')
                a1,b1=st.columns(2)
                with a1:
                    if st.button('Accept all fields in this class',disabled=not items):
                        def accept_all():
                            for f in items:
                                if not f['data']['accepted']:w.definition('field',f['data']['name'],f['data']['description'],True,id=f['id'],parent=c['id'])
                        call(accept_all)
                with b1:
                    running=any(j['kind']=='suggest fields' and j['target']==c['id'] and j['status'] in ('queued','running') for j in w.store.jobs())
                    if st.button('Refresh class fields',disabled=running):call(lambda:w.suggest_fields(c['id'],batch,refresh=True))
                with st.expander('Add a field'):
                    with st.form('manual-field-'+c['id']):
                        name=st.text_input('New field name')
                        description=st.text_area('New field description')
                        if st.form_submit_button('Add field'):call(lambda:w.definition('field',name,description,False,parent=c['id']))
            else:
                st.info('This file needs an assigned class before fields can be suggested.')
                from audio_idp.ui.manual_class import render as manual_class
                manual_class(w,r,expanded=True)
            with st.expander('Selected transcript'):transcript(w,r)
    a,b,c=st.columns([1,1,2])
    with a:
        if st.button('← Classes'):move(w,batch,1)
    with b:
        if st.button('Retry field suggestions',disabled=busy(w,batch,{'suggest fields'})):call(lambda:w.suggest_fields_batch(batch))
    with c:
        eligible=any(w.fields(a['data']['class_id']) for a in w.store.list('classification',batch=batch) if a['data']['class_id'])
        if st.button('Extract accepted fields →',type='primary',width='stretch',disabled=not eligible or busy(w,batch,{'suggest class','suggest fields'})):
            def extract():
                w.extract_batch(batch)
                move(w,batch,3)
            call(extract)

def results(w,batch):
    st.title('Your results, with the source.')
    st.caption('Choose a file. Only that file’s values and evidence are displayed.')
    left,right=st.columns([1,2.3],gap='large')
    with left:
        st.subheader('Recordings')
        r,status=select_file(w,batch,'results')
    with right,st.container(border=True):
        if r:
            file_header(r,status,'Extraction')
            result=w.store.get('ex-'+r['id'])
            if result:
                st.dataframe([{'Field':key,**value} for key,value in result['data']['fields'].items()],hide_index=True,width='stretch')
                with st.expander('Result actions'):
                    delete_button(w,result)
                    names=list(result['data']['fields'])
                    if names:
                        field=st.selectbox('Value to clear',names,key='clear-field-'+r['id'])
                        if st.button('Clear selected value'):
                            def clear():
                                values=dict(result['data']['fields'])
                                values[field]={'value':None,'evidence':None,'warning':'Removed by user'}
                                w.store.save('extraction',{'fields':values},id=result['id'])
                            call(clear)
            else:st.info('Extraction results will appear here when this file is ready. Check its status above for any action needed.')
            with st.expander('Selected transcript',expanded=True):transcript(w,r)
    a,b,c=st.columns([1,1,2])
    with a:
        if st.button('← Fields'):move(w,batch,2)
    with b:
        if st.button('Retry extraction',disabled=busy(w,batch,{'extract'})):call(lambda:w.extract_batch(batch))
    with c:
        data,csv=w.export(batch)
        d,e=st.columns(2)
        d.download_button('Download batch JSON',data,'audio-idp-results.json','application/json',width='stretch')
        e.download_button('Download batch CSV',csv,'audio-idp-fields.csv','text/csv',width='stretch')

def stage_of(data):
    stage=data.get('guided_stage',0)
    if data.get('flow_version',1)==2:stage={0:0,1:1,2:1,3:2,4:3}.get(stage,0)
    return max(0,min(3,stage))


def render(w,batch):
    b=w.store.get(batch) if batch else None
    if b and b['data'].get('flow_version',1)<3:
        w.store.save('batch',dict(b['data'],flow_version=3,guided_stage=stage_of(b['data'])),id=batch)
        b=w.store.get(batch)
    stage=stage_of(b['data']) if b else 0
    stepper(stage)
    [upload,classes,fields,results][stage](w,batch)
