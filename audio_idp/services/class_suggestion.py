from audio_idp.providers.bedrock import request
from audio_idp.domain.validation import suggestions
from audio_idp.prompts import load

def suggest_classes(transcripts, existing):
    result = request(load('class_suggestion'),
                     {'recordings': transcripts, 'existing_classes': [{'name':c['name'],'description':c['description']} for c in existing]})
    rows = suggestions(result, 'classes', is_class=True, allow_empty=True)
    known = {t['id'] for t in transcripts}
    def sources(row):
        ids = row.get('source_ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(id,str) or id not in known for id in ids):
            raise ValueError('Class suggestions contain invalid or missing recording references. Retry suggestions.')
        return list(dict.fromkeys(ids))
    output = [dict(row, source_ids=sources(raw)) for row,raw in zip(rows,result['classes'])]
    matches = result.get('existing_matches',[])
    existing_by_name = {c['name']:c for c in existing}
    if not isinstance(matches,list) or len(matches)>len(existing):
        raise ValueError('Invalid existing-class matches.')
    for row in matches:
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or row['name'] not in existing_by_name:
            raise ValueError('Suggested match references an unknown existing class.')
        c=existing_by_name[row['name']]
        output.append(dict(name=c['name'],description=c['description'],source_ids=sources(row),existing=True))
    return output
