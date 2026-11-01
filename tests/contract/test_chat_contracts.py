"""Closed chat tools and durable transport identities; these do not assert routes exist yet."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from hdrp_agent.domain import payload, DOMAIN
from hdrp_agent.providers.meta_responses import strict_schema


def action():
    return dict(schema_version='1.0',action_id='a1',project_id='p1',conversation_id='c1',message_id='m1',kind='reconstruct_reference',expected_scene_version='v1',artifact_hashes=['a'*64],parameters=dict(brief='Reproduis cette pièce',reference_hashes=['a'*64],building_policy='atmospheric-house',interior_style='B',ceiling_prefab='Ceiling_3x3'),idempotency_key='k1')


def test_typed_reconstruction_contract():
    value=action()
    assert payload('AppActionRequest',value)==value
    for change in [dict(kind='execute_script'),dict(parameters={**value['parameters'],'shell':'anything'}),dict(expected_scene_version=True),dict(artifact_hashes=['/tmp/image.png'])]:
        with pytest.raises((ValidationError,ValueError)):payload('AppActionRequest',{**value,**change})


def test_model_cannot_claim_native_execution_or_supply_operation_identity():
    proposal=dict(text='Je vais inspecter.',tools=[dict(kind='inspect_room',parameters=dict(mode='panorama',poses=[]))])
    assert payload('ModelChatResponse',proposal)==proposal
    for key in ['executed','session_id','operation_id','state']:
        invalid=deepcopy(proposal);invalid[key]='completed'
        with pytest.raises((ValidationError,ValueError)):payload('ModelChatResponse',invalid)
    invalid=deepcopy(proposal);invalid['tools']*=5
    with pytest.raises((ValidationError,ValueError)):payload('ModelChatResponse',invalid)


def test_chat_memory_requires_project_bound_transport_and_bounded_history():
    turn=dict(schema_version='1.0',turn_id='t1',project_id='p1',conversation_id='c1',message_id='m1',idempotency_key='k1',messages=[dict(role='user',text='inspecte')],artifact_hashes=[],memory=dict(revision=0,summary='',constraints=['WallIn_B','Ceiling_3x3'],scene_version='v1',parent_run_id=None))
    assert payload('ChatTurnRequest',turn)==turn
    turn['messages']*=25
    with pytest.raises((ValidationError,ValueError)):payload('ChatTurnRequest',turn)


def test_chat_provider_schema_is_expandable_and_closed():
    schema=strict_schema('ModelChatResponse')
    assert schema['additionalProperties'] is False
    assert '$ref' not in str(schema)
    assert {'$ref':'#/$defs/ChatToolGenerateHouse'} in DOMAIN['$defs']['ChatToolProposal']['anyOf']
    assert len(DOMAIN['$defs']['ChatToolProposal']['anyOf'])==7
