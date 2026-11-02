"""Meta Responses, one transmission per reservation, no hidden tool loop."""
import base64
from copy import deepcopy
from decimal import Decimal
import io
import json

import httpx
from PIL import Image
from pydantic import ValidationError

from ..domain import AgentError, DOMAIN, canonical, payload, fingerprint, validator
from ..store import utc_now


def strict_schema(name,bindings=None):
    def expand(value):
        if isinstance(value,list):return [expand(v) for v in value]
        if not isinstance(value,dict):return value
        if '$ref' in value:return expand(deepcopy(DOMAIN['$defs'][value['$ref'].split('/')[-1]]))
        # Muse's strict output dialect rejects uniqueItems. Local payload
        # validation still enforces it before any downstream operation.
        return {('anyOf' if k=='oneOf' else k):expand(v) for k,v in value.items() if k!='uniqueItems'}
    schema=expand(DOMAIN['$defs'][name])
    if schema.get('type')!='object':raise AgentError('INVALID_SCHEMA','Provider root must be an object',422)
    for field,value in (bindings or {}).items():
        if field=='selected_ids':
            if name!='ModelHouseCatalogueChoice' or not isinstance(value,list) or not value or len(set(value))!=len(value) or any(not isinstance(item,str) or not item for item in value):raise AgentError('INVALID_SCHEMA','Visual choices require unique supplied identifiers',422)
            schema['properties']['selected']['items']['enum']=list(value)
            continue
        if field=='catalog_asset_ids':
            if name not in {'ModelReferenceAnalysis','ModelReconstructionPlan'} or not isinstance(value,list) or not 1<=len(value)<=1000 or len(set(value))!=len(value) or any(not validator('Id').is_valid(item) for item in value):raise AgentError('INVALID_SCHEMA','A unique bounded asset catalogue is required',422)
            if len(value)>250 and sum(len(item) for item in value)>15000:raise AgentError('INVALID_SCHEMA','Use compact job-local catalogue IDs within the provider enum character limit',422)
            schema['properties']['objects']['items']['properties']['asset_id']['anyOf'][0]['enum']=value
            continue
        if field=='evidence_frames':
            if name!='ModelDiagnosis' or not isinstance(value,list) or not 1<=len(value)<=12 or any(not isinstance(item,dict) or set(item)!={'capture_id','frame_index'} or not validator('Id').is_valid(item['capture_id']) or (item['frame_index'] is not None and (type(item['frame_index']) is not int or item['frame_index']<0)) for item in value) or len({item['capture_id'] for item in value})!=len(value):raise AgentError('INVALID_SCHEMA','Diagnostic evidence requires unique supplied image/frame pairs',422)
            for collection in ['observations','hypotheses']:
                evidence=schema['properties'][collection]['items']['properties']['evidence']
                branches=[]
                for frame in value:
                    branch=deepcopy(evidence['items'])
                    for key in ['capture_id','frame_index']:branch['properties'][key]['const']=frame[key]
                    branches.append(branch)
                evidence['items']={'anyOf':branches}
            inspected=schema['properties']['inspected_capture_ids'];inspected['items']['enum']=[item['capture_id'] for item in value];inspected['minItems']=inspected['maxItems']=len(value)
            continue
        if field=='operation_target_ids':
            if name!='ModelProposal' or not isinstance(value,list) or not 1<=len(value)<=20 or any(not validator('Id').is_valid(item) for item in value) or len(set(value))!=len(value):raise AgentError('INVALID_SCHEMA','Proposal targets must be a bounded unique list of existing opaque IDs',422)
            branches=schema['properties']['operations']['items']['anyOf']
            branches[:]=[branch for branch in branches if 'target_id' in branch['properties']]
            for branch in branches:branch['properties']['target_id']['enum']=list(value)
            continue
        if field not in {'scene_version','hypothesis_key'} or field not in schema['properties'] or not validator('Id').is_valid(value):raise AgentError('INVALID_SCHEMA','Only existing opaque root IDs may be bound',422)
        schema['properties'][field]['const']=value
    if name in {'ModelReferenceAnalysis','ModelReconstructionPlan'}:
        item=schema['properties']['objects']['items']
        prefab=deepcopy(item);primitive=deepcopy(item)
        prefab['properties']['asset_id']=deepcopy(item['properties']['asset_id']['anyOf'][0])
        prefab['properties']['primitive']={'type':'null'}
        primitive['properties']['asset_id']={'type':'null'}
        primitive['properties']['primitive']=deepcopy(item['properties']['primitive']['anyOf'][0])
        schema['properties']['objects']['items']={'anyOf':[prefab,primitive]}
    return schema


def reviewed_format(name,format_value):
    try:
        properties=format_value['format']['schema']['properties']
        bindings={key:properties[key]['const'] for key in ['scene_version','hypothesis_key'] if key in properties and 'const' in properties[key]}
        if name=='ModelHouseCatalogueChoice':
            ids=properties['selected']['items'].get('enum')
            if ids is not None:bindings['selected_ids']=ids
        if name=='ModelDiagnosis':
            evidence=properties['observations']['items']['properties']['evidence']['items']
            if 'anyOf' in evidence:bindings['evidence_frames']=[{key:branch['properties'][key]['const'] for key in ['capture_id','frame_index']} for branch in evidence['anyOf']]
        if name=='ModelProposal':
            branches=properties['operations']['items']['anyOf']
            targets=branches[0]['properties'].get('target_id',{}).get('enum')
            if targets is not None:bindings['operation_target_ids']=targets
        if name in {'ModelReferenceAnalysis','ModelReconstructionPlan'}:
            ids=properties['objects']['items']['anyOf'][0]['properties']['asset_id'].get('enum')
            if ids is not None:bindings['catalog_asset_ids']=ids
        return format_value=={'format':dict(type='json_schema',name='hdrp_'+name.lower(),strict=True,schema=strict_schema(name,bindings))}
    except (KeyError,TypeError,IndexError,AgentError):return False


def image_part(data):
    if len(data)>10_000_000:raise AgentError('PAYLOAD_TOO_LARGE','Image exceeds 10 MB',413)
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {'PNG','JPEG'} or image.width>1280 or image.height>720:raise AgentError('INVALID_MEDIA','Bounded PNG/JPEG required',422)
        media='image/png' if image.format=='PNG' else 'image/jpeg';image.verify()
    return {'type':'input_image','image_url':'data:'+media+';base64,'+base64.b64encode(data).decode('ascii')}


def spark_request(text,images,schema_name,bindings=None):
    if not isinstance(text,str) or not text.strip():raise AgentError('INVALID_INPUT','A non-empty text prompt is required',422)
    if len(images)>12:raise AgentError('IMAGE_BATCH_EXCEEDED','This request contains more than 12 images; split the observations into batches',422)
    request=dict(model='muse-spark-1.3-contributor',truncation='disabled',reasoning={'effort':'low'},input=[dict(role='user',content=[dict(type='input_text',text=text)]+[image_part(data) for data in images])],text={'format':dict(type='json_schema',name='hdrp_'+schema_name.lower(),strict=True,schema=strict_schema(schema_name,bindings))})

    if schema_name=='ModelChatResponse':request['max_output_tokens']=4096
    return request


def sam_request(concept,image):
    if not isinstance(concept,str) or not concept.strip() or len(concept)>100 or any(c in concept for c in [',',';','\n','<','>','+']):raise AgentError('INVALID_INPUT','One short concrete SAM concept required',422)
    return dict(model='sam-3.1',input=[dict(role='user',content=[dict(type='input_text',text=concept),image_part(image)])],stream=False,metadata={'include_confidence':'true','mask_encoding':'one_bit'})


def terminal_text(response):
    if response.get('status')=='incomplete' and (response.get('incomplete_details') or {}).get('reason')=='max_output_tokens':raise AgentError('MODEL_OUTPUT_TRUNCATED','Muse reached its output token limit before completing the response; partial geometry was not applied')
    if response.get('status')!='completed':raise AgentError('INVALID_MODEL_OUTPUT','Response is incomplete or refused')
    parts=[]
    if not isinstance(response.get('output'),list):raise AgentError('INVALID_MODEL_OUTPUT','Response output is not a terminal item list')
    for item in response['output']:
        if not isinstance(item,dict) or item.get('status') not in {None,'completed'}:raise AgentError('INVALID_MODEL_OUTPUT','Output item is not terminal')
        if item.get('type')=='reasoning':
            if item.get('status') not in {None,'completed'}:raise AgentError('INVALID_MODEL_OUTPUT','Reasoning envelope is not terminal')
            continue
        if item.get('type')!='message':raise AgentError('INVALID_MODEL_OUTPUT','Unexpected model tool or output item')
        if not isinstance(item.get('content'),list):raise AgentError('INVALID_MODEL_OUTPUT','Message content is not a terminal list')
        for part in item['content']:
            if not isinstance(part,dict):raise AgentError('INVALID_MODEL_OUTPUT','Malformed output content')
            if part.get('type')!='output_text' or not isinstance(part.get('text'),str):raise AgentError('INVALID_MODEL_OUTPUT','Unexpected response content')
            parts.append(part['text'])
    return ''.join(parts)


def usage_usd(model,response):
    usage=response.get('usage')
    if not isinstance(usage,dict):return None
    def integer(v):
        if type(v) is not int or v<0:raise ValueError()
        return v
    try:
        if model=='sam-3.1':
            if 'video_frames_processed' in usage:return Decimal(max(50,integer(usage['video_frames_processed'])))*Decimal('.0002')
            return Decimal(integer(usage['images_processed']))*Decimal('.0025')
        incoming=integer(usage['input_tokens']);outgoing=integer(usage['output_tokens']);cached=integer(usage['input_tokens_details']['cached_tokens'])
        if cached>incoming:raise ValueError()
        return (Decimal(incoming-cached)*Decimal('.10')+Decimal(cached)*Decimal('.002')+Decimal(outgoing)*Decimal('.20'))/1000000
    except (KeyError,TypeError,ValueError):return None


class MetaResponses:
    def __init__(self,settings,budget,artifacts,client=None):
        self.settings,self.budget,self.artifacts=settings,budget,artifacts
        self.client=client or httpx.Client(timeout=httpx.Timeout(120,connect=10),transport=httpx.HTTPTransport(retries=0),follow_redirects=False)

    def recover_completed(self,call_id,request,schema_name=None):
        with self.budget.store.tx() as c:
            call=c.execute('SELECT * FROM calls WHERE id=?',(call_id,)).fetchone()
            envelope=c.execute("SELECT body FROM events WHERE subject=? AND kind='provider_envelope' ORDER BY id DESC LIMIT 1",(call_id,)).fetchone()
            invoice=c.execute("SELECT body FROM budget_entries WHERE call_id=? AND kind='settlement'",(call_id,)).fetchone()
        if not call or call['status']!='settled' or call['payload_hash']!=fingerprint(request) or not envelope or not invoice:raise AgentError('RESPONSE_RECOVERY_REFUSED','Exact request and completed paid response are required')
        meta=json.loads(envelope[0]);data=json.loads(self.artifacts.read(meta['artifact_hash']))
        if meta['status']!=200:raise AgentError('RESPONSE_RECOVERY_REFUSED','Stored response was not successful')
        try:
            text=terminal_text(data)
            value=payload(schema_name,json.loads(text)) if schema_name else text
        except (ValueError,ValidationError):raise AgentError('INVALID_MODEL_OUTPUT','Stored model output is invalid')
        with self.budget.store.tx() as c:self.budget.store.event(c,call_id,'response_reprocessed',{'network_sent':False,'artifact_hash':meta['artifact_hash']})
        return dict(value=value,response_id=data['id'],call_id=call_id,artifact_hash=meta['artifact_hash'],usage=data['usage'],usd=json.loads(invoice[0])['usd'],reprocessed=True,network_sent=False)

    def send(self,request,schema_name=None):
        if self.settings.provider_mode!='live':raise AgentError('OFFLINE_MODE','Live provider transmission is disabled')
        if not self.settings.api_key:raise AgentError('KEY_MISSING','Meta API key is not configured')
        model=request.get('model')
        fields=({'model','truncation','reasoning','input','text'} | ({'max_output_tokens'} if schema_name=='ModelChatResponse' else set())) if model=='muse-spark-1.3-contributor' else {'model','input','stream','metadata'}
        if model not in {'muse-spark-1.3-contributor','sam-3.1'} or set(request)!=fields:raise AgentError('INVALID_PROVIDER_REQUEST','Only the reviewed fields and Meta models are allowed',422)
        expected_output=4096 if schema_name=='ModelChatResponse' else None
        if model=='muse-spark-1.3-contributor' and (request.get('max_output_tokens')!=expected_output or request['truncation']!='disabled' or request['reasoning']!={'effort':'low'} or schema_name is None or not reviewed_format(schema_name,request['text'])):raise AgentError('INVALID_PROVIDER_REQUEST','Strict reviewed schema, low reasoning effort and output bound required',422)
        image_count=0
        for message in request['input']:
            if set(message)!={'role','content'} or message['role']!='user':raise AgentError('INVALID_PROVIDER_REQUEST','Stateless user content required',422)
            for part in message['content']:
                if part.get('type')=='input_image':
                    image_count+=1
                    # Revalidate the actual bytes that will be sent, not a caller-declared count.
                    try:
                        checked=image_part(base64.b64decode(part['image_url'].split(',',1)[1],validate=True))
                        if part!=checked:raise ValueError('Unreviewed image part')
                    except Exception:raise AgentError('INVALID_MEDIA','Only bounded inline images are supported',422)
                elif set(part)!={'type','text'} or part['type']!='input_text' or not isinstance(part['text'],str):raise AgentError('COST_BOUND_UNKNOWN','Unreviewed media or content field')
        if image_count>12 or (model=='sam-3.1' and image_count!=1):raise AgentError('INVALID_PROVIDER_REQUEST','Unsupported image count',422)
        if model=='sam-3.1' and (request['stream'] is not False or request['metadata']!={'include_confidence':'true','mask_encoding':'one_bit'}):raise AgentError('INVALID_PROVIDER_REQUEST','Reviewed non-streaming SAM mode required',422)
        call=self.budget.reserve(model,request,images=image_count or 1)
        self.budget.mark_sent(call['id'])
        import time
        started=time.monotonic()
        try:
            response=self.client.post('https://api.meta.ai/v1/responses',headers={'Authorization':'Bearer '+self.settings.api_key},json=request)
        except httpx.HTTPError as error:
            self.budget.mark_unknown(call['id'])
            # Exception text and request objects may contain credentials or user
            # content. Record only classification and timing, never their repr.
            with self.budget.store.tx() as c:
                self.budget.store.event(c,call['id'],'provider_transport_error',dict(exception_type=type(error).__name__,elapsed_seconds=round(time.monotonic()-started,3),response_received=False,retry_attempted=False))
            raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Request outcome is unknown; reservation retained; no automatic retry') from None
        try:data=response.json()
        except ValueError:
            self.budget.mark_unknown(call['id']);raise AgentError('INVALID_MODEL_OUTPUT','Non-JSON provider envelope; reservation retained')
        if not isinstance(data,dict):
            self.budget.mark_unknown(call['id']);raise AgentError('INVALID_MODEL_OUTPUT','Provider envelope must be an object; usage unknown and reservation retained')
        clean=canonical(data)
        for secret in [self.settings.api_key,self.settings.token]:
            if secret:clean=clean.replace(secret,'[REDACTED]')
        digest=self.artifacts.put(clean.encode(),'application/json',metadata={'call_id':call['id'],'provider_mode':'live'})
        with self.budget.store.tx() as c:self.budget.store.event(c,call['id'],'provider_envelope',dict(response_id=data.get('id'),artifact_hash=digest,status=response.status_code))
        cost=usage_usd(model,data)
        if cost is None:
            self.budget.mark_unknown(call['id']);raise AgentError('PROVIDER_USAGE_UNKNOWN','Usage is missing or malformed (HTTP '+str(response.status_code)+'); reservation retained; envelope '+digest)
        self.budget.settle(call['id'],cost,data.get('id') or 'HTTP-'+str(response.status_code))
        with self.budget.store.tx() as c:self.budget.store.event(c,call['id'],'provider_response',dict(response_id=data.get('id'),artifact_hash=digest,usage=data.get('usage'),usd=str(cost),status=response.status_code))
        if response.status_code!=200:raise AgentError('PROVIDER_REJECTED','Provider rejected the request; known usage settled')
        text=terminal_text(data)
        if schema_name:
            try:result=payload(schema_name,json.loads(text))
            except (ValueError,ValidationError):raise AgentError('INVALID_MODEL_OUTPUT','Model output is not valid reviewed JSON; known usage settled')
        else:result=text
        return dict(value=result,response_id=data.get('id'),call_id=call['id'],artifact_hash=digest,usage=data['usage'],usd=str(cost))
