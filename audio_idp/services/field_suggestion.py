from audio_idp.providers.bedrock import request
from audio_idp.domain.validation import suggestions
from audio_idp.prompts import load

def suggest_fields(class_definition, transcripts, existing):
    result = request(load('field_suggestion'),
                     {'class': {k:class_definition[k] for k in ('name','description')}, 'recordings': transcripts,
                      'existing_fields': [{k:f[k] for k in ('name','description')} for f in existing]})
    return suggestions(result, 'fields', allow_empty=True)
