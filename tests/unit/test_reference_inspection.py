import hashlib
import io
import json
from copy import deepcopy
import pytest
from PIL import Image
from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.store import Store
from hdrp_agent.domain import AgentError
from hdrp_agent.reference_inspection import inspection_targets,read_inspection,append_inspection_boards


def setup_capture(tmp_path):
    artifacts=ArtifactStore(tmp_path/'artifacts',Store(tmp_path/'state.sqlite3'))
    image=Image.new('RGB',(1280,720),(100,120,150));out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue()
    pose=dict(key='detail-0',position_m=[0,2,-3],rotation_deg=[20,0,0],fov_deg=38)
    detail=dict(key='detail-0',object_key='bottle',angle='top',calibration=pose,artifact_hash=artifacts.put(raw,'image/png'),acquisition='native_camera_closeup')
    view=dict(pose,object_key='bottle',angle='top')
    request=dict(ordinal=1,version='v1',scene_path='candidate.unity',views=[view],objects=[])
    directory=tmp_path/'inspection';directory.mkdir();(directory/'request.json').write_text(json.dumps(request));(directory/'frame.png').write_bytes(raw)
    result=dict(status='complete',mode='editor_hdrp_probe',version='v1',scene_path='candidate.unity',width=1280,height=720,warmup_frames=32,performance_qualified=False,gizmos_in_images=False,request_sha256=hashlib.sha256((directory/'request.json').read_bytes()).hexdigest(),frames=[dict(file='frame.png',view=view,sha256=hashlib.sha256(raw).hexdigest())])
    (directory/'result.json').write_text(json.dumps(result))
    return directory,request,[detail],artifacts,result


def test_inspection_provenance_and_image_budget(tmp_path):
    directory,request,details,artifacts,result=setup_capture(tmp_path)
    pairs=read_inspection(directory,request,details,artifacts)
    assert pairs[0]['candidate']['version']=='v1'
    images=[b'preserved']*12;metadata=[dict(image_index=i) for i in range(12)]
    images,metadata=append_inspection_boards(artifacts,images,metadata,pairs)
    assert len(images)==12 and images[:4]==[b'preserved']*4
    assert metadata[-1]['kind']=='active_editor_closeups' and metadata[-1]['rows'][0]['camera']==details[0]['calibration']
    (directory/'frame.png').write_bytes(b'tampered')
    with pytest.raises(AgentError):read_inspection(directory,request,details,artifacts)


@pytest.mark.parametrize('change',[{'version':'other'},{'mode':'gameview'},{'performance_qualified':True},{'gizmos_in_images':True},{'frames':[]}])
def test_editor_images_cannot_impersonate_runtime_or_other_version(tmp_path,change):
    directory,request,details,artifacts,result=setup_capture(tmp_path);result.update(change);(directory/'result.json').write_text(json.dumps(result))
    with pytest.raises(AgentError):read_inspection(directory,request,details,artifacts)


def test_worst_objects_and_coverage_choose_real_new_camera_observations():
    analysis=dict(objects=[dict(key=str(i)) for i in range(10)])
    details=[dict(key=f'{i}-{angle}',object_key=str(i),angle=angle,acquisition='native_camera_closeup',calibration=dict(key=f'{i}-{angle}',position_m=[i,2,-3],rotation_deg=[0,0,0],fov_deg=38)) for i in range(10) for angle in ['top','front','back']]
    metrics=dict(per_object={str(i):dict(priority_rgb_mae=1-i/10) for i in range(10)})
    first=inspection_targets(analysis,details,metrics);second=inspection_targets(analysis,details,metrics,[first])
    assert len(first)==8 and {v['object_key'] for v in first}=={'0','1','2','3'}
    assert {v['object_key'] for v in second}=={'0','1','4','5'}
    assert any(v['angle']=='back' for v in second) and all(v['position_m'][0]==int(v['object_key']) for v in second)
    assert inspection_targets(analysis,[dict(d,acquisition='original_resolution_crop') for d in details],metrics)==[]


def test_planner_sends_active_observations_as_images_not_only_metadata(tmp_path):
    from hdrp_agent.reference_planner import ReferencePlanner
    from hdrp_agent.providers.fake import FakeProvider
    directory,request,details,artifacts,result=setup_capture(tmp_path)
    pairs=read_inspection(directory,request,details,artifacts)
    frame=dict(key='work-top-front',artifact_hash=details[0]['artifact_hash'],calibration=dict(details[0]['calibration'],key='work-top-front'),model_size=[1280,720])
    catalogue=[dict(asset_id='asset-bottle',name='Bottle',bounds_center_m=[0,.2,0],bounds_size_m=[.1,.4,.1])]
    analysis=dict(summary='Bottle',inspected_view_keys=['work-top-front'],objects=[dict(key='bottle',label='bottle',asset_id='asset-bottle',primitive=None,support_key=None,view_boxes=[dict(view_key='work-top-front',bbox_xyxy=[.4,.2,.6,.8])])],limits=[])
    plan=dict(objects=[dict(key='bottle',asset_id='asset-bottle',primitive=None,position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1],base_color_rgba=None)],lights=[],estimated_views=None,exposure_ev=0,sky_color_rgb=[.1,.1,.1],fog_mean_free_path_m=None,notes=[])
    fake=FakeProvider([plan])
    ReferencePlanner(fake,artifacts).layout(analysis,[frame],catalogue,[],'Rebuild',plan,[frame],inspection_pairs=pairs)
    content=fake.calls[0]['request']['input'][0]['content'];context=json.loads(content[0]['text'].split('Untrusted observations:\n')[1])
    boards=context['paired_comparison_images'];active=next(b for b in boards if b['kind']=='active_editor_closeups')
    assert content[active['image_index']+1]['type']=='input_image'
    assert boards[0]['side']=='REFERENCE' and boards[1]['side']=='CANDIDATE'
    assert active['rows'][0]['candidate_version']=='v1' and len(content)<=13


def test_room_sweep_is_full_circle_with_advancing_closeups():
    from hdrp_agent.reference_inspection import room_inspection_targets
    catalogue=[dict(asset_id='floor',name='Floor_A',bounds_center_m=[0,0,0],bounds_size_m=[6,.1,4]),dict(asset_id='wall',name='WallOut_3x',bounds_center_m=[-1.5,1.5,0],bounds_size_m=[3,3,0])]
    plan=dict(objects=[dict(key='floor',asset_id='floor',position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1])]+[dict(key=f'wall-{i}',asset_id='wall',position_m=[1.5,0,z],rotation_deg=[0,0,0],scale=[1,1,1]) for i,z in enumerate([-2,2])])
    views=room_inspection_targets(plan,catalogue)
    assert [v['rotation_deg'][1] for v in views[:8]]==list(range(0,360,45))
    assert all(v['position_m']==[0,1.5,0] for v in views[:8])
    assert all(abs(v['position_m'][2])==1 for v in views[8:])


def test_candidate_only_survey_keeps_provenance_and_never_invents_reference(tmp_path):
    directory,request,details,artifacts,result=setup_capture(tmp_path)
    request['views'][0]['angle']='room_sweep'
    result['frames'][0]['view']=request['views'][0]
    result['architecture']={'walls':[{'object_key':'wall','outward_axis_points_to_observer':True}]}
    (directory/'request.json').write_text(json.dumps(request));result['request_sha256']=hashlib.sha256((directory/'request.json').read_bytes()).hexdigest()
    (directory/'result.json').write_text(json.dumps(result))
    pairs=read_inspection(directory,request,[],artifacts)
    assert pairs[0]['reference'] is None
    images,metadata=append_inspection_boards(artifacts,[b'keep']*12,[{}]*12,pairs)
    assert len(images)==12 and metadata[-1]['kind']=='candidate_interior_survey'
    assert 'CANDIDATE ONLY' in metadata[-1]['layout']
    assert metadata[-1]['architecture']['walls'][0]['outward_axis_points_to_observer']
    assert metadata[-1]['views'][0]['camera']['position_m']==request['views'][0]['position_m']


def test_architecture_regression_cannot_be_hidden_by_better_overhead_score():
    from hdrp_agent.reference_inspection import architecture_findings
    from hdrp_agent.reference_worker import accept_external_candidate
    missing=[dict(architecture=dict(walls=[dict(object_key='south',surfaces=[],outward_axis_points_to_observer=False)]))]
    findings=architecture_findings(missing)
    assert findings['defects']==[dict(object_key='south',kind='missing_interior_prefab')]
    best=dict(metrics=dict(score=.3,contacts=dict(checks=[]),architecture=dict(qualified=True,defect_count=0)))
    broken=dict(metrics=dict(score=.1,contacts=dict(checks=[]),architecture=findings))
    assert not accept_external_candidate(broken,best)
    assert not architecture_findings([])['qualified']


def test_model_can_choose_closeup_pose_but_not_unknown_object_or_outside_room(tmp_path):
    from hdrp_agent.reference_inspection import choose_room_closeups
    from hdrp_agent.providers.fake import FakeProvider
    directory,request,details,artifacts,result=setup_capture(tmp_path)
    plan=dict(objects=[dict(key='floor',asset_id='floor',position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1])])
    catalogue=[dict(asset_id='floor',name='Floor_A',bounds_center_m=[0,0,0],bounds_size_m=[6,.1,4])]
    view=dict(object_key='floor',position_m=[1,1.4,-1],rotation_deg=[20,45,0],fov_deg=40)
    provider=FakeProvider([dict(views=[view],reason='Inspect seam')])
    selected,response=choose_room_closeups(provider,artifacts,plan,catalogue,[],[details[0]])
    assert selected[0]['position_m']==view['position_m'] and selected[0]['angle']=='interior_detail'
    assert response['value']['reason']=='Inspect seam'
    provider=FakeProvider([dict(views=[dict(view,position_m=[99,1,1])],reason='Outside')])
    with pytest.raises(AgentError,match='outside the room'):choose_room_closeups(provider,artifacts,plan,catalogue,[],[details[0]])


def test_cached_sam_masks_are_remapped_to_current_walls_and_drawn_as_evidence(tmp_path,monkeypatch):
    from hdrp_agent.reference_inspection import segment_room_observations
    directory,request,details,artifacts,result=setup_capture(tmp_path)
    mask=Image.new('L',(1280,720));mask.paste(255,(100,100,900,600));out=io.BytesIO();mask.save(out,format='PNG');mask_hash=artifacts.put(out.getvalue(),'image/png')
    class CachedSegmenter:
        def __init__(self,*args):pass
        def segment(self,*args):return dict(source='sam-3.1',regions=[dict(mask_hash=mask_hash,bbox_xyxy=[0,0,1,1],candidates=[dict(target_id='stale-tv')])])
    monkeypatch.setattr('hdrp_agent.segmentation.Segmenter',CachedSegmenter)
    observation=dict(angle='room_sweep',object_key='floor',reference=None,candidate=dict(details[0],version='v1'),architecture=dict(walls=[dict(object_key='current-wall')]),projected_objects=[dict(target_id='current-wall',bbox_xyxy=[0,0,1,1]),dict(target_id='tv',bbox_xyxy=[0,0,1,1])],limitation='Candidate only')
    pairs=segment_room_observations([observation],None,artifacts)
    assert [c['target_id'] for c in pairs[0]['segmentation']['regions'][0]['candidates']]==['current-wall']
    images,metadata=append_inspection_boards(artifacts,[],[],pairs)
    assert metadata[0]['views'][0]['sam_contour_mask_hashes']==[mask_hash]
    with Image.open(io.BytesIO(images[0])) as board:assert board.size==(1280,720)
