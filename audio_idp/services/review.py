"""File-specific class provenance and shared-schema review operations."""
def candidates(store,recording):
    t=store.get('tr-'+recording)
    if not t:return []
    return [c for c in store.list('class') if c['data'].get('mapped') and recording in c['data'].get('sources',[])
            and c['data'].get('source_revisions',{}).get(recording)==t['revision']]

def batch_candidates(store,batch):
    ids={r['id'] for r in store.list('recording',batch=batch)}
    valid={c['id'] for id in ids for c in candidates(store,id)}
    b=store.get(batch)
    selected=set(b['data'].get('class_ids',[])) if b else set()
    return [c for c in store.list('class') if c['id'] in valid|selected]

def link_manual(store,recording,class_id):
    c=store.get(class_id)
    t=store.get('tr-'+recording)
    if not c or not t:raise ValueError('Choose a class and a completed transcript.')
    data=dict(c['data'],mapped=True,sources=list(dict.fromkeys(c['data'].get('sources',[])+[recording])),
              manual_sources=list(dict.fromkeys(c['data'].get('manual_sources',[])+[recording])),
              source_revisions=dict(c['data'].get('source_revisions',{}),**{recording:t['revision']}))
    store.save('class',data,id=class_id)
