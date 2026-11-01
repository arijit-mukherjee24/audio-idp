"""One reusable primary class per transcript, ready for immediate assignment."""
from pathlib import Path
from audio_idp.providers.bedrock import request
from audio_idp.domain.validation import definition

def suggest_file_class(text,existing):
    prompt=(Path(__file__).parents[1]/'prompts'/'file_class_suggestion.txt').read_text(encoding='utf-8')
    result=request(prompt,{'transcript':text,'existing_classes':sorted(
        [{'name':c['name'],'description':c['description']} for c in existing],key=lambda c:c['name'].casefold())})
    if 'class' not in result or not isinstance(result.get('reason'),str):
        raise ValueError('Class suggestion must include a class or null and a reason.')
    if result['class'] is None:return {'class':None,'reason':result['reason'][:1000]}
    row=result['class']
    if not isinstance(row,dict) or not all(isinstance(row.get(k),str) for k in ('name','description')):
        raise ValueError('Invalid class suggestion: name and description must be text.')
    data=definition(row.get('name'),row.get('description'),is_class=True)
    prior=next((c for c in existing if c['name'].casefold()==data['name'].casefold()),None)
    if prior:data={'name':prior['name'],'description':prior['description']}
    return {'class':data,'reason':result['reason'][:1000]}
