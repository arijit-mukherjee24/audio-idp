"""Stable assignment decisions separate from transient class/schema metadata."""
def semantic_class(c):
    return (c['id'],c['data']['name'],c['data']['description'],c['data']['accepted'])

def assignment_token(store,recording):
    a=store.get('cl-'+recording)
    return (a['revision'],a['data']) if a else None

def choice(store,recording):
    r=store.get(recording)
    t=store.get('tr-'+recording)
    b=store.get(r['batch']) if r else None
    selected=b['data'].get('file_class_choices',{}).get(recording) if b else None
    c=store.get(selected['class_id']) if selected else None
    if not t or not c or not c['data']['accepted'] or selected['transcript_revision']!=t['revision']:
        return None
    if selected.get('definition')!=[c['data']['name'],c['data']['description']]:return None
    return c
