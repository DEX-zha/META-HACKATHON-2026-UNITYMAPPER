from datetime import date
from decimal import Decimal
import json

import httpx
import pytest

from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.budget import Budget, Pricing
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError
from hdrp_agent.providers.meta_responses import MetaResponses, spark_request
from hdrp_agent.store import Store


def provider(tmp_path,handler):
    settings=Settings(tmp_path,provider_mode='live',api_key='fixture-secret',token='fixture-local-token')
    store=Store(settings.db_path);budget=Budget(store,Pricing(date.today().isoformat(),verified=True));budget.reconcile(0,'fixture','2026-10-28T10:00:00Z')
    return MetaResponses(settings,budget,ArtifactStore(settings.state/'artifacts',store),client=httpx.Client(transport=httpx.MockTransport(handler))),budget


def response(text='not JSON',status='completed'):
    return dict(id='response-fixture',model='muse-spark-1.3-contributor',status=status,output=[dict(type='message',content=[dict(type='output_text',text=text)])],usage=dict(input_tokens=100,output_tokens=20,input_tokens_details={'cached_tokens':0},output_tokens_details={'reasoning_tokens':10},total_tokens=120))


def test_invalid_json_is_billed_without_double_counting_reasoning(tmp_path):
    p,b=provider(tmp_path,lambda request:httpx.Response(200,json=response()))
    with pytest.raises(AgentError,match='valid'):p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert b.state()['settled_usd_micro']==14
    assert b.state()['active_reserved_usd_micro']==0


def test_timeout_is_reserved_and_sent_once(tmp_path):
    sent=[]
    def timeout(request):sent.append(request);raise httpx.ReadTimeout('fixture timeout',request=request)
    p,b=provider(tmp_path,timeout)
    with pytest.raises(AgentError):p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert len(sent)==1
    assert b.state()['unknown_reserved_usd_micro']==314573


def test_transport_failure_records_safe_diagnostics_without_retry_or_exception_text(tmp_path):
    sent=[]
    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout('fixture-secret fixture-local-token private user prompt',request=request)
    p,b=provider(tmp_path,timeout)
    with pytest.raises(AgentError) as exc:p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert exc.value.code=='PROVIDER_OUTCOME_UNKNOWN' and len(sent)==1
    with b.store.tx() as c:
        events=c.execute("SELECT subject,body FROM events WHERE kind='provider_transport_error'").fetchall()
        call=c.execute('SELECT id,status FROM calls').fetchone()
    assert len(events)==1 and events[0]['subject']==call['id'] and call['status']=='unknown'
    detail=json.loads(events[0]['body'])
    assert detail['exception_type']=='ReadTimeout' and detail['retry_attempted'] is False
    assert detail['elapsed_seconds']>=0 and detail['response_received'] is False
    for secret in ['fixture-secret','fixture-local-token','private user prompt']:assert secret not in events[0]['body']
    assert b.state()['unknown_reserved_usd_micro']==314573


def test_request_forbids_tools_history_and_alternate_models(tmp_path):
    def forbidden(request):pytest.fail('Transport must not be invoked')
    p,b=provider(tmp_path,forbidden)
    request=spark_request('Inspect',[],'ModelDiagnosis');request['tools']=[{'type':'web_search'}]
    with pytest.raises(AgentError):p.send(request,'ModelDiagnosis')
    assert b.state()['active_reserved_usd_micro']==0


def test_missing_usage_keeps_full_reservation(tmp_path):
    data=response();data.pop('usage')
    p,b=provider(tmp_path,lambda request:httpx.Response(200,json=data))
    with pytest.raises(AgentError):p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert b.state()['unknown_reserved_usd_micro']==314573


def test_terminal_reasoning_item_is_ignored_and_paid_response_can_be_reprocessed(tmp_path):
    data=response(json.dumps(dict(scene_version='version',inspected_capture_ids=[],observations=[],hypotheses=[],unsupported_limits=[])))
    data['output'].insert(0,dict(type='reasoning',status='completed',summary=[]))
    transmitted=[]
    def transport(request):transmitted.append(request);return httpx.Response(200,json=data)
    p,b=provider(tmp_path,transport);request=spark_request('Inspect',[],'ModelDiagnosis')
    result=p.send(request,'ModelDiagnosis')
    recovered=p.recover_completed(result['call_id'],request,'ModelDiagnosis')
    assert recovered['value']==result['value']
    assert recovered['network_sent'] is False
    assert len(transmitted)==1
    assert b.state()['settled_usd_micro']==14


def test_only_root_id_constraints_can_narrow_the_provider_schema(tmp_path):
    from copy import deepcopy
    from hdrp_agent.providers.meta_responses import reviewed_format
    request=spark_request('Inspect',[],'ModelDiagnosis',{'scene_version':'version-exact'})
    assert reviewed_format('ModelDiagnosis',request['text'])
    changed=deepcopy(request['text']);changed['format']['schema']['properties']['observations']['maxItems']=999
    assert not reviewed_format('ModelDiagnosis',changed)
    with pytest.raises(AgentError):spark_request('Inspect',[],'ModelDiagnosis',{'execute_csharp':'forbidden'})
    p,b=provider(tmp_path,lambda req:httpx.Response(200,json=response(json.dumps(dict(scene_version='version-exact',inspected_capture_ids=[],observations=[],hypotheses=[],unsupported_limits=[])))))
    assert p.send(request,'ModelDiagnosis')['value']['scene_version']=='version-exact'


def test_nonterminal_message_is_rejected_even_when_outer_response_is_completed(tmp_path):
    data=response(json.dumps(dict(scene_version='version',inspected_capture_ids=[],observations=[],hypotheses=[],unsupported_limits=[])))
    data['output'][0]['status']='incomplete'
    p,b=provider(tmp_path,lambda request:httpx.Response(200,json=data))
    with pytest.raises(AgentError):p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert b.state()['settled_usd_micro']==14


def test_inspection_proposal_schema_binds_every_operation_to_grounded_targets():
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    from hdrp_agent.providers.meta_responses import reviewed_format
    bindings=dict(scene_version='version',hypothesis_key='hyp',operation_target_ids=['wall-a','wall-b'])
    request=spark_request('Repair grounded surfaces',[],'ModelProposal',bindings)
    schema=request['text']['format']['schema'];check=Draft202012Validator(schema)
    proposal=dict(scene_version='version',hypothesis_key='hyp',expected_effect='Improve baked surface',needs_bake=True,operations=[dict(op='set_bake',target_id='wall-a',indirect_samples=256)])
    assert check.is_valid(proposal) and reviewed_format('ModelProposal',request['text'])
    proposal['operations'][0]['target_id']='unrelated-light'
    assert not check.is_valid(proposal)
    changed=deepcopy(request['text']);changed['format']['schema']['properties']['operations']['items']['anyOf'][0]['properties']['target_id']['enum']=['unrelated-light']
    assert not reviewed_format('ModelProposal',changed)
    for invalid in [[],['wall','wall'],['wall',None]]:
        with pytest.raises(AgentError):spark_request('Inspect',[],'ModelProposal',dict(bindings,operation_target_ids=invalid))
    with pytest.raises(AgentError):spark_request('Inspect',[],'ModelDiagnosis',{'operation_target_ids':['wall']})


def test_diagnostic_evidence_can_only_cite_the_supplied_capture_frame_pairs():
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    from hdrp_agent.providers.meta_responses import reviewed_format
    frames=[dict(capture_id='still',frame_index=0),dict(capture_id='clip',frame_index=48)]
    request=spark_request('Inspect',[],'ModelDiagnosis',dict(scene_version='version',evidence_frames=frames))
    evidence=dict(capture_id='still',frame_index=0,bbox_xyxy=None,target_ids=[],description='Visible surface')
    value=dict(scene_version='version',inspected_capture_ids=['still','clip'],observations=[dict(key='obs',category='lighting',claim='Visible defect',evidence=[evidence])],hypotheses=[],unsupported_limits=[])
    check=Draft202012Validator(request['text']['format']['schema'])
    assert reviewed_format('ModelDiagnosis',request['text']) and check.is_valid(value)
    evidence['frame_index']=48
    assert not check.is_valid(value)  # Known index, wrong image.
    evidence['capture_id']='clip'
    assert check.is_valid(value)
    evidence['capture_id']='unseen'
    assert not check.is_valid(value)
    changed=deepcopy(request['text']);changed['format']['schema']['properties']['hypotheses']['items']['properties']['evidence']['items']['anyOf'][0]['properties']['frame_index']['const']=48
    assert not reviewed_format('ModelDiagnosis',changed)
    for invalid in [[],frames+[frames[0]],[dict(capture_id='still',frame_index=True)]]:
        with pytest.raises(AgentError):spark_request('Inspect',[],'ModelDiagnosis',{'evidence_frames':invalid})


def test_nonobject_provider_envelope_keeps_unknown_reservation(tmp_path):
    p,b=provider(tmp_path,lambda request:httpx.Response(200,json=[]))
    with pytest.raises(AgentError):p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert b.state()['unknown_reserved_usd_micro']==314573


def test_truncated_response_fixture_is_billed_and_never_accepted(tmp_path):
    from hdrp_agent.domain import WORKSPACE
    data=json.loads((WORKSPACE/'fixtures/provider-replies/incomplete-response.json').read_text())
    p,b=provider(tmp_path,lambda request:httpx.Response(200,json=data))
    with pytest.raises(AgentError) as exc:p.send(spark_request('Inspect',[],'ModelDiagnosis'),'ModelDiagnosis')
    assert exc.value.code=='MODEL_OUTPUT_TRUNCATED'
    assert b.state()['settled_usd_micro']==14 and b.state()['active_reserved_usd_micro']==0


def test_reference_analysis_has_room_for_reasoning_and_geometry(tmp_path):
    from hdrp_agent.providers.meta_responses import terminal_text
    request=spark_request('Inspect room',[],'ModelReferenceAnalysis')
    assert 'max_output_tokens' not in request
    assert spark_request('Chat',[],'ModelChatResponse')['max_output_tokens']==4096
    p,b=provider(tmp_path,lambda r:httpx.Response(200,json=response()))
    # Request passes admission and is billed even when fixture JSON is invalid.
    with pytest.raises(AgentError,match='valid reviewed JSON'):p.send(request,'ModelReferenceAnalysis')
    assert b.state()['settled_usd_micro']>0


def test_analysis_requests_do_not_send_client_output_caps():
    for name in ['ModelReferenceAnalysis','ModelReconstructionPlan','ModelDiagnosis']:
        assert 'max_output_tokens' not in spark_request('Analyse',[],name)
