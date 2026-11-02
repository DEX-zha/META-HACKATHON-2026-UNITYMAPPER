import hashlib
import io
import json
import pytest
from PIL import Image
from hdrp_agent.domain import AgentError
from hdrp_agent.house_visual_catalogue import load_previews, pages


def fixture(tmp_path):
    stream=io.BytesIO();Image.new('RGB',(1280,640),'red').save(stream,format='PNG')
    data=stream.getvalue();(tmp_path/'chair.png').write_bytes(data)
    record=dict(prefab_guid='chair-guid',dependency_hash='version-1',path='Assets/Pack/Prefabs/Chairs/Chair.prefab',file='chair.png',sha256=hashlib.sha256(data).hexdigest(),status='ready')
    (tmp_path/'manifest.json').write_text(json.dumps([record]))
    assets={'Chair':dict(prefab_guid='chair-guid',dependency_hash='version-1',prefab_path=record['path'],bounds_size=[1,2,1])}
    return assets,record


def test_stale_dependency_not_presented_as_current(tmp_path):
    assets,_=fixture(tmp_path)
    assets['Chair']['dependency_hash']='version-2'
    assert load_previews(tmp_path,assets)==({},['Chair'])


def test_tampered_preview_rejected(tmp_path):
    assets,_=fixture(tmp_path);(tmp_path/'chair.png').write_bytes(b'changed')
    with pytest.raises(AgentError,match='hash changed'):load_previews(tmp_path,assets)


def test_pages_preserve_every_identity_and_do_not_qualify_semantics(tmp_path):
    assets,_=fixture(tmp_path);ready,missing=load_previews(tmp_path,assets)
    assert not missing
    many={f'Chair {i}':ready['Chair'] for i in range(19)}
    result=list(pages(many))
    assert len(result)==5
    assert [r['asset_id'] for p in result for r in p['assets']]==sorted(many)
    assert len({r['key'] for p in result for r in p['assets']})==19
    assert all(not p['semantic_qualified'] for p in result)
    assert Image.open(io.BytesIO(result[0]['image'])).size==(1280,720)
    from hdrp_agent.providers.meta_responses import spark_request
    spark_request('Review catalogue', [result[0]['image']], 'ModelHouseCatalogueChoice')


def test_preview_path_escape_rejected(tmp_path):
    assets,record=fixture(tmp_path);record['file']='../chair.png'
    (tmp_path/'manifest.json').write_text(json.dumps([record]))
    with pytest.raises(AgentError,match='owned regular'):load_previews(tmp_path,assets)


def test_room_browsing_sends_real_image_and_rejects_unseen_choice(tmp_path):
    from types import SimpleNamespace
    from hdrp_agent.house_service import HouseService
    directory=tmp_path/'house/visual-catalogue';directory.mkdir(parents=True)
    assets,_=fixture(directory)
    service=HouseService.__new__(HouseService)
    service.settings=SimpleNamespace(state=tmp_path)
    service.guard=lambda row:None
    calls=[]
    def ask(row,key,text,schema,images=()):
        calls.append((key,images))
        return dict(selected=['Chairs'] if len(calls)==1 else ['Unseen chair'],summary='Choose a chair')
    service.ask=ask
    with pytest.raises(AgentError,match='leaves inspected page'):
        service.browse_assets({'run_id':'test'},dict(id='bedroom'),'Bedroom',assets)
    assert len(calls)==2 and len(calls[1][1])==1
    assert Image.open(io.BytesIO(calls[1][1][0])).size==(1280,720)


def test_room_browsing_retains_visual_decisions_and_provenance(tmp_path):
    from types import SimpleNamespace
    from hdrp_agent.house_service import HouseService
    directory=tmp_path/'house/visual-catalogue';directory.mkdir(parents=True)
    assets,record=fixture(directory)
    service=HouseService.__new__(HouseService);service.settings=SimpleNamespace(state=tmp_path);service.guard=lambda row:None
    calls=[]
    def ask(row,key,text,schema,images=()):
        calls.append(key)
        return dict(selected=['Chairs'] if len(calls)==1 else ['Chair'],summary='Compact wooden chair matches the desk')
    service.ask=ask
    result=service.browse_assets({'run_id':'a'*32},dict(id='bedroom'),'Bedroom',assets)
    assert result['selected_assets']==['Chair']
    assert result['preview_evidence'][0]['image_sha256']==record['sha256']
    assert not result['semantic_qualified']
    assert list((tmp_path/'house/runs'/('a'*32)/'memory').glob('analysis-*.md'))


def test_transport_batches_cover_all_pages():
    from hdrp_agent.house_visual_catalogue import batches
    result=list(batches(iter(range(29))))
    assert [len(b) for b in result]==[12,12,5]
    assert sum(result,[])==list(range(29))


def test_asset_review_rejects_unmeasured_support_before_writing(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hdrp_agent.house_service import HouseService
    directory=tmp_path/'house/visual-catalogue';directory.mkdir(parents=True)
    assets,_=fixture(directory)
    assets['Chair'].update(front_status='unknown',bounds_center=[0,1,0],surfaces=[])
    service=HouseService.__new__(HouseService);service.settings=SimpleNamespace(state=tmp_path);service.houses=object()
    writes=[]
    monkeypatch.setattr('hdrp_agent.house_service.Catalogue',lambda _:SimpleNamespace(qualify_support=lambda *args:writes.append(args),qualify_front=lambda *args,**kwargs:writes.append(args)))
    service.ask=lambda *args,**kwargs:dict(front='not_applicable',supports=['invented-surface'],summary='Looks flat')
    with pytest.raises(AgentError,match='unmeasured patch'):
        service.review_selected_assets({},dict(id='bedroom'),dict(groups=[dict(items=[dict(asset='Chair')])],detail_assets=[]),assets)
    assert not writes
