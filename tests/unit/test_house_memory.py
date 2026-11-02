import json
from hdrp_agent.house_memory import HouseMemory


def test_compaction_retains_every_pending_need_and_archives_evidence(tmp_path):
    memory=HouseMemory(tmp_path,'a'*32)
    defect=dict(scope_id='office',severity='blocking',gate='lighting',message='Task area dark',evidence_ids=['large-hash']*50)
    context=dict(brief='Office without bed',room={'id':'office'},pending_requirements=[dict(id=str(i),description='need '+str(i),role='Lamp_table_work',quantity=1,reason='Unqualified',status='pending',priority='mandatory',evidence_ids=['evidence']) for i in range(80)],defects=[defect,defect],rejected_attempts=[dict(scope_id='office',patch={'kind':'transform_group','rejection':'Blocked door'},receipt_hash='receipt')])
    result=memory.compact('office',context)
    doc=result['markdown'];data=json.loads(doc.split('```json\n')[1].split('\n```')[0])
    assert len(data['pending_requirements'])==80 and len(data['defects'])==1
    assert data['brief']=='Office without bed'
    assert all(r['role']=='Lamp_table_work' and r['quantity']==1 and r['reason']=='Unqualified' for r in data['pending_requirements'])
    assert data['rejected_attempts'][0]['patch']['rejection']=='Blocked door'
    assert json.loads((memory.root/data['source_archive']).read_text())==context
    assert (memory.root/result['memory_file']).read_text()==doc


def test_model_notes_and_state_survive_new_memory_instance(tmp_path):
    memory=HouseMemory(tmp_path,'a'*32);name=memory.note('inspect-1',{'unresolved':['missing lamp']})
    memory.state(dict(stage='inspection',message='Review',scene_path='House 3.unity'))
    restored=HouseMemory(tmp_path,'a'*32)
    assert 'missing lamp' in (restored.root/name).read_text()
    assert 'House 3.unity' in (restored.root/'STATE.md').read_text()
