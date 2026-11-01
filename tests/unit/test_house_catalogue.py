import pytest
from hdrp_agent.house_catalogue import Catalogue
from hdrp_agent.house_store import HouseStore
from hdrp_agent.store import Store
from hdrp_agent.domain import AgentError


def measured():
    return dict(prefab_guid='a'*32,dependency_hash='b'*32,prefab_path='Assets/Chair.prefab',bounds_center=[0,.5,0],bounds_size=[1,1,1],surfaces=[],measurement_evidence='native-geometry')


def test_native_bounds_do_not_qualify_a_facing_direction(tmp_path):
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')))
    c.import_measurements([measured()])
    assert c.get('a'*32,'b'*32)['front_status']=='unknown'
    with pytest.raises(AgentError):c.require_functional('a'*32,'b'*32)
    with pytest.raises(AgentError):c.qualify_front('a'*32,'b'*32,[0,0,1],[])
    c.qualify_front('a'*32,'b'*32,[0,0,-1],[dict(kind='reviewed_multiview',reference='atlas-view-1',reviewer='local-review')])
    assert c.require_functional('a'*32,'b'*32)['forward']==[0,0,-1]


def test_dependency_change_requires_new_semantics(tmp_path):
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')));c.import_measurements([measured()])
    with pytest.raises(AgentError):c.get('a'*32,'c'*32)
    changed=measured();changed['dependency_hash']='c'*32;c.import_measurements([changed]);assert c.get('a'*32,'c'*32)['front_status']=='unknown'


def test_reviewed_support_must_cover_real_triangles(tmp_path):
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')))
    row=measured();row['surfaces']=[dict(id='top',triangles=[[[0,1,0],[1,1,0],[0,1,1]]],qualification='geometry_candidate',supports_items=False)]
    c.import_measurements([row])
    evidence=[dict(kind='reviewed_multiview',reference='desk-top',reviewer='local-review')]
    with pytest.raises(AgentError):c.qualify_support('a'*32,'b'*32,'top',[0,0,1,1],['desktop'],evidence)
    c.qualify_support('a'*32,'b'*32,'top',[.05,.05,.2,.2],['desktop'],evidence)
    assert c.get('a'*32,'b'*32)['support_regions'][0]['roles']==['desktop']
    # Re-measurement preserves reviewed semantics without changing raw triangles.
    c.import_measurements([row])
    assert len(c.get('a'*32,'b'*32)['support_regions'])==1


def test_native_import_cannot_smuggle_semantic_qualifications(tmp_path):
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')))
    row=measured();row['support_regions']=[dict(surface_id='top')]
    with pytest.raises(AgentError):c.import_measurements([row])


def test_review_import_is_bound_to_exact_preview(tmp_path):
    import hashlib,json
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')));c.import_measurements([measured()])
    (tmp_path/'preview.png').write_bytes(b'reviewed-image')
    (tmp_path/'manifest.json').write_text(json.dumps([dict(prefab_guid='a'*32,dependency_hash='b'*32,file='preview.png')]))
    review=dict(schema_version='house-functional-reviews.v1',reviewer='operator',reviews=[dict(prefab_guid='a'*32,dependency_hash='b'*32,forward=[0,0,1],image_sha256=hashlib.sha256(b'reviewed-image').hexdigest(),note='Front inspected')])
    (tmp_path/'preview.png').write_bytes(b'changed')
    with pytest.raises(AgentError):c.import_reviews(review,tmp_path)
    assert c.get('a'*32,'b'*32)['front_status']=='unknown'
    (tmp_path/'preview.png').write_bytes(b'reviewed-image')
    assert c.import_reviews(review,tmp_path)==1


def test_symmetric_front_still_requires_explicit_review(tmp_path):
    c=Catalogue(HouseStore(Store(tmp_path/'s.db')));c.import_measurements([measured()])
    with pytest.raises(AgentError):c.qualify_front('a'*32,'b'*32,None,[],status='not_applicable')
    evidence=[dict(kind='reviewed_multiview',reference='symmetric-table',reviewer='operator')]
    result=c.qualify_front('a'*32,'b'*32,None,evidence,status='not_applicable')
    assert result['forward'] is None and result['front_status']=='not_applicable'
