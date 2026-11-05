"""Allowlisted per-job provenance: never store credentials or transcript text."""
from urllib.parse import urlsplit

PROVIDER_NAMES={'azure':'Azure Speech Fast','amazon':'Amazon Transcribe','whisper':'Whisper (local)','bedrock':'Amazon Bedrock','local':'Local processing'}
BEDROCK_OPERATIONS={'suggest class','suggest classes','suggest fields','classify','extract'}


def execution_metadata(kind,value):
    if kind!='transcribe' or not isinstance(value,dict):return {}
    result={}
    for source,target in {'azure_api_version':'api_version','azure_request_id':'request_id',
                          'azure_request_sent_at':'request_sent_at','aws_job_name':'remote_job_name'}.items():
        item=value.get(source)
        if isinstance(item,str) and item and len(item)<=256:result[target]=item
    if value.get('azure_http_status')==200:result['http_status']=200
    endpoint=value.get('azure_endpoint')
    if isinstance(endpoint,str):
        try:
            parsed=urlsplit(endpoint)
            if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
                result['endpoint']=endpoint
        except ValueError:pass
    return result


def provider_name(provider):
    return PROVIDER_NAMES.get(provider,'Not recorded')


def response_source(job):
    if job.get('request_hash'):
        return 'Cached response' if job.get('cache_hit') else 'Fresh API response'
    provider=job.get('provider')
    if job.get('status')!='completed':return 'Awaiting result' if job.get('status') in ('queued','running') else 'No completed result'
    if provider=='azure':
        status=job.get('execution',{}).get('http_status')
        return f'Azure API · HTTP {status}' if status else 'Azure transcription'
    if provider=='amazon':return 'Amazon Transcribe job'
    if provider=='whisper':return 'Local transcription'
    if provider=='local':return 'Local processing'
    return 'Not recorded (older job)'
