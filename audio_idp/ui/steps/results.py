import json
import streamlit as st
from audio_idp.ui.common import action, delete_button, name_of

def render(w,batch,guided=False):
    if not guided: st.subheader('Insights you can trace back')
    st.caption('Each populated value includes matching transcript evidence. Missing information remains empty.')
    with st.expander('Retry or refresh extraction',expanded=not guided):
        force=st.checkbox('Refresh completed extractions')
        action('Extract pending / retry failed',lambda:w.extract_batch(batch,force),primary=not guided)
    for result in w.store.list('extraction',batch=batch):
        with st.expander(name_of(w.store,result['parent'],'Recording'),expanded=True):
            left,right=st.columns([3,2])
            with left:
                st.dataframe([{'field':key,**value} for key,value in result['data']['fields'].items()],hide_index=True,width='stretch')
                delete_button(w,result)
                with st.expander('Remove an individual extracted value'):
                    field=st.selectbox('Field',list(result['data']['fields']),key='remove-value-'+result['id'])
                    def clear(result=result,field=field):
                        values=dict(result['data']['fields'])
                        values[field]={'value':None,'evidence':None,'warning':'Removed by user'}
                        w.store.save('extraction',{'fields':values},id=result['id'])
                    action('Clear selected value',clear,key='clear-'+result['id'])
            with right:
                t=w.store.get('tr-'+result['parent'])
                if t: st.text(t['data']['text'])
    data,csv=w.export(batch)
    a,b,c=st.columns(3)
    a.download_button('Download JSON',data,'audio-idp-results.json','application/json',width='stretch')
    b.download_button('Download CSV',csv,'audio-idp-fields.csv','text/csv',width='stretch')
    catalog=[dict(c['data'],fields=[f['data'] for f in w.fields(c['id'])]) for c in w.classes()]
    c.download_button('Download configuration',json.dumps(catalog,ensure_ascii=False,indent=2),'audio-idp-config.json','application/json',width='stretch')
