import pytest
from hdrp_agent.store import Store
from hdrp_agent.house_store import HouseStore
from hdrp_agent.domain import AgentError
from test_house_domain import program


def test_durable_inventory_and_dependency_jobs(tmp_path):
    db=Store(tmp_path/'state.sqlite3');houses=HouseStore(db);houses.create(program())
    houses.add_jobs('run',[dict(id='analyse',scope_id='kitchen',kind='analyse',dependencies=[],input_hash='v1'),dict(id='decorate',scope_id='kitchen',kind='decorate',dependencies=['analyse'],input_hash='v1')])
    job=houses.claim('run');assert job['id']=='analyse'
    assert houses.claim('run') is None
    houses.complete('run','analyse','v1',dict(inventory_count=35))
    assert houses.claim('run')['id']=='decorate'
    reopened=HouseStore(Store(tmp_path/'state.sqlite3'))
    assert len(reopened.snapshot('run')['requirements'])==35
    assert reopened.snapshot('run')['quality_state']=='pending'
    assert (tmp_path/'state.sqlite3.house-v1-backup').exists()


def test_dependency_cycle_and_stale_completion_rejected(tmp_path):
    h=HouseStore(Store(tmp_path/'s.db'));h.create(program())
    with pytest.raises(AgentError):h.add_jobs('run',[dict(id='a',scope_id='kitchen',kind='analyse',dependencies=['b'],input_hash='v1'),dict(id='b',scope_id='kitchen',kind='analyse',dependencies=['a'],input_hash='v1')])
    assert h.snapshot('run')['jobs']==[]
    h.add_jobs('run',[dict(id='a',scope_id='kitchen',kind='analyse',dependencies=[],input_hash='v1')]);h.claim('run')
    with pytest.raises(AgentError):h.complete('run','a','other',{})
    assert h.snapshot('run')['jobs'][0]['state']=='running'


def test_partial_batch_never_erases_missing_requirements(tmp_path):
    h=HouseStore(Store(tmp_path/'s.db'));h.create(program())
    with pytest.raises(AgentError):h.reconcile_batch('run',['need-0','need-1'],[],['need-0'])
    assert len(h.snapshot('run')['requirements'])==35
    h.defect('run',dict(id='old-defect',scope_id='kitchen',severity='blocking',gate='support',message='TV unsupported',evidence_ids=[]))
    for i in range(30):h.defect('run',dict(id=f'issue-{i}',scope_id='kitchen',severity='warning',gate='detail',message='detail missing',evidence_ids=[]))
    assert len(h.snapshot('run')['defects'])==31
    assert h.snapshot('run')['quality_state']=='incomplete'


def test_finished_is_not_qualified_and_old_defects_remain_in_context(tmp_path):
    h=HouseStore(Store(tmp_path/'s.db'));h.create(program())
    for i in range(35):h.defect('run',dict(id=f'issue-{i}',scope_id='kitchen',severity='blocking',gate='support',message='Unsupported object',evidence_ids=[]))
    assert len(h.context('run','kitchen')['defects'])==35
    assert h.finish('run')=='incomplete'
    s=h.snapshot('run');assert s['execution_state']=='finished' and s['quality_state']=='incomplete'


def test_room_context_includes_groups_and_rejected_attempts(tmp_path):
    h=HouseStore(Store(tmp_path/'s.db'));p=program()
    p['rooms'][0]['group_ids']=['desk-group'];p['requirements'][0]['scope_id']='desk-group'
    h.create(p)
    h.defect('run',dict(id='desk-reversed',scope_id='desk-group',severity='warning',gate='orientation',message='Desk faces wall',evidence_ids=[]))
    attempt=dict(id='try-1',scope_id='desk-group',defect_ids=['desk-reversed'],input_hash='scene-v1',proposal=dict(kind='rotate_group',degrees=180),reason='Chair would block doorway',evidence_ids=[])
    h.record_rejected_attempt('run',attempt)
    h.record_rejected_attempt('run',attempt)
    reopened=HouseStore(Store(tmp_path/'s.db'))
    context=reopened.context('run','kitchen')
    assert any(r['scope_id']=='desk-group' for r in context['pending_requirements'])
    assert context['defects'][0]['id']=='desk-reversed'
    assert len(context['rejected_attempts'])==1
    with pytest.raises(AgentError):h.record_rejected_attempt('run',dict(attempt,reason='different'))
    with pytest.raises(AgentError):h.context('run','missing')


def test_defect_identity_cannot_move_between_scopes(tmp_path):
    h=HouseStore(Store(tmp_path/'s.db'));p=program();h.create(p)
    defect=dict(id='issue',scope_id='kitchen',severity='blocking',gate='support',message='No support',evidence_ids=[])
    h.defect('run',defect)
    with pytest.raises(AgentError):h.defect('run',dict(defect,scope_id=p['id']))
    assert h.snapshot('run')['defects'][0]['scope_id']=='kitchen'
