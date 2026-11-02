from copy import deepcopy
import pytest
from hdrp_agent.domain import payload
from hdrp_agent.house_planning import place_details, namespace_addition
from hdrp_agent.providers.meta_responses import spark_request, reviewed_format


def setup_supports():
    def triangles(y):return [[[0,y,0],[1,y,0],[1,y,1]],[[0,y,0],[1,y,1],[0,y,1]]]
    table=dict(prefab_guid='table',bounds_center=[.5,.5,.5],bounds_size=[1,1,1],surfaces=[dict(id='top',triangles=triangles(.5)),dict(id='upper',triangles=triangles(1.1))],support_regions=[dict(surface_id=s,rectangle_xz=[0,0,1,1],roles=['decor']) for s in ['top','upper']])
    prop=dict(prefab_guid='notebook',dependency_hash='a'*32,front_status='qualified',bounds_center=[0,.05,0],bounds_size=[.2,.1,.2])
    def instance(group,slot,x,room='bedroom'):return dict(id=room+'-'+group+'-'+slot,room_id=room,group_id=group,role=slot,prefab_guid='table',position=[x,0,0],center=[x+.5,.5,.5],bounds_size=[1,1,1],yaw=0,support_id=None)
    return {'Desk':table,'Notebook':prop},[instance('storage','dresser',3),instance('drawing','desk01',0),instance('drawing','desk01',10,'other')]


def target():return dict(asset='Notebook',support_group='drawing',support_slot='desk01',surface_id='upper')


def test_enrichment_keeps_new_and_existing_support_references_distinct():
    existing=dict(target(),support_group='existing')
    design=dict(groups=[dict(id='drawing')],detail_assets=[target(),existing,'Carpet_C'])
    original=deepcopy(design)
    result=namespace_addition(design,'extra-pass-')
    assert design==original
    assert result['groups'][0]['id']==result['detail_assets'][0]['support_group']=='extra-pass-drawing'
    assert result['detail_assets'][1]==existing
    assert result['detail_assets'][2]=='Carpet_C'


def test_enrichment_rejects_group_id_collisions_after_namespacing():
    from hdrp_agent.domain import AgentError
    with pytest.raises(AgentError):
        namespace_addition(dict(groups=[dict(id='a'*40+'1'),dict(id='a'*40+'2')]),'extra-')


def test_target_contract_and_strict_provider_format():
    design=dict(room_id='bedroom',groups=[],detail_assets=[target(),'Carpet_C'],unresolved=[])
    assert payload('ModelHouseRoomV2',design)==design
    request=spark_request('Place the notebook on the desk',[],'ModelHouseRoomV2')
    assert reviewed_format('ModelHouseRoomV2',request['text'])
    broken=deepcopy(design);del broken['detail_assets'][0]['support_slot']
    with pytest.raises(ValueError):payload('ModelHouseRoomV2',broken)


def test_target_selects_exact_room_group_slot_and_measured_surface():
    assets,instances=setup_supports();missing=[]
    place_details('bedroom',[target()],assets,instances,[],missing)
    assert not missing
    assert instances[-1]['support_id']=='bedroom-drawing-desk01'
    assert instances[-1]['position'][1]==pytest.approx(1.1)


@pytest.mark.parametrize('change',[{'support_slot':'absent'},{'surface_id':'unreviewed'}])
def test_unavailable_target_remains_missing_without_using_dresser(change):
    assets,instances=setup_supports();before=deepcopy(instances);missing=[]
    item=target();item.update(change)
    place_details('bedroom',[item],assets,instances,[],missing)
    assert instances==before
    assert missing[0]['support_target']==item


def test_oversized_detail_does_not_fall_back_to_other_furniture():
    assets,instances=setup_supports();item=target();assets['Notebook']['bounds_size']=[2,.1,2]
    missing=[];before=deepcopy(instances)
    place_details('bedroom',[item],assets,instances,[],missing)
    assert instances==before and missing[0]['support_target']==item


def test_occupied_named_shelf_does_not_fall_back_to_free_lower_shelf():
    assets,instances=setup_supports()
    assets['Blocker']=dict(prefab_guid='blocker',bounds_center=[0,.1,0],bounds_size=[1,.2,1])
    instances.append(dict(id='occupied',room_id='bedroom',group_id='drawing',role='detail',prefab_guid='blocker',position=[.5,1.1,.5],center=[.5,1.2,.5],bounds_size=[1,.2,1],yaw=0,support_id='bedroom-drawing-desk01'))
    before=deepcopy(instances);missing=[]
    place_details('bedroom',[target()],assets,instances,[],missing)
    assert instances==before and missing[0]['support_target']==target()
