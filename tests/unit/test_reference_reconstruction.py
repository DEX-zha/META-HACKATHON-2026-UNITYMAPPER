from copy import deepcopy
import io
import json

import numpy as np
from PIL import Image
import pytest

from hdrp_agent.domain import AgentError
from hdrp_agent.reference_media import bounded_image,ingest
from hdrp_agent.reference_planner import ReferencePlanner,validate_analysis,validate_plan,catalogue_context
from hdrp_agent.reference_geometry import triangulate,rotation
from hdrp_agent.providers.fake import FakeProvider
from hdrp_agent.providers.meta_responses import spark_request,reviewed_format
from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.store import Store


def data(tmp_path):
    store=Store(tmp_path/'state.sqlite3');artifacts=ArtifactStore(tmp_path/'artifacts',store)
    image=io.BytesIO();Image.new('RGB',(640,480),'white').save(image,format='PNG');digest=artifacts.put(image.getvalue(),'image/png')
    frame=dict(key='front',artifact_hash=digest,calibration=dict(key='front',position_m=[0,1,-4],rotation_deg=[0,0,0],fov_deg=50),model_size=[640,480],timestamp_seconds=None)
    catalogue=[dict(asset_id='asset-chair',name='Chair',bounds_center_m=[0,.5,0],bounds_size_m=[1,1,1],source_object_position='MUST_NOT_ENTER_CONTEXT',source_lighting='PRIVATE_LIGHT_VALUE')]
    analysis=dict(summary='A chair',inspected_view_keys=['front'],objects=[dict(key='chair',label='chair',asset_id='asset-chair',primitive=None,view_boxes=[dict(view_key='front',bbox_xyxy=[.2,.2,.7,.8])],support_key=None)],limits=[])
    plan=dict(objects=[dict(key='chair',asset_id='asset-chair',primitive=None,position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1],base_color_rgba=None)],lights=[],estimated_views=None,exposure_ev=0,sky_color_rgb=[.1,.1,.1],fog_mean_free_path_m=None,notes=[])
    return artifacts,[frame],catalogue,analysis,plan


def test_reference_context_filters_source_transform_and_lighting(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path);fake=FakeProvider([analysis,plan]);p=ReferencePlanner(fake,artifacts)
    assert p.analyse(frames,catalogue,'Rebuild')['value']==analysis
    assert p.layout(analysis,frames,catalogue,[],'Rebuild')['value']==plan
    encoded=json.dumps(fake.calls)
    for private in ['MUST_NOT_ENTER_CONTEXT','PRIVATE_LIGHT_VALUE','source_object_position','source_lighting']:assert private not in encoded
    assert 'Chair' in encoded and 'input_image' in encoded


@pytest.mark.parametrize('fault',['missing_object','unknown_asset','camera_replaced','infinite','executable_field','negative_scale'])
def test_invalid_reconstruction_is_refused_before_native_mutation(tmp_path,fault):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    if fault=='missing_object':plan['objects']=[]
    if fault=='unknown_asset':plan['objects'][0]['asset_id']='asset-invented'
    if fault=='camera_replaced':plan['estimated_views']=[frames[0]['calibration']]
    if fault=='infinite':plan['objects'][0]['position_m'][0]=float('inf')
    if fault=='executable_field':plan['script']='unsafe'
    if fault=='negative_scale':plan['objects'][0]['scale'][0]=-1
    with pytest.raises((AgentError,ValueError)):validate_plan(plan,analysis,frames,catalogue)


def test_external_image_requires_explicit_camera_estimate(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path);frames[0]['calibration']=None
    with pytest.raises(AgentError):validate_plan(plan,analysis,frames,catalogue)
    plan['estimated_views']=[dict(key='front',position_m=[0,1,-4],rotation_deg=[0,0,0],fov_deg=50)]
    assert validate_plan(plan,analysis,frames,catalogue)==plan


def test_assets_are_narrowed_in_both_provider_schemas():
    for schema in ['ModelReferenceAnalysis','ModelReconstructionPlan']:
        request=spark_request('Rebuild',[],schema,dict(catalog_asset_ids=['asset-chair']))
        assert reviewed_format(schema,request['text'])
        enum=request['text']['format']['schema']['properties']['objects']['items']['anyOf'][0]['properties']['asset_id']['enum']
        assert enum==['asset-chair']
    with pytest.raises(AgentError):spark_request('Rebuild',[],'ModelReferenceAnalysis',dict(catalog_asset_ids=['asset-'+str(i).zfill(40) for i in range(668)]))


def test_all_reference_angles_are_required_and_candidate_correction_includes_back(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    keys=['work-front','work-front-right','work-back-right','work-back','work-back-left','work-front-left','work-top-front','work-top-back']
    frames=[dict(frames[0],key=key) for key in keys]
    analysis['objects'][0]['view_boxes'][0]['view_key']='work-front'
    analysis['inspected_view_keys']=keys[:-1]
    with pytest.raises(AgentError):validate_analysis(analysis,frames,catalogue)
    analysis['inspected_view_keys']=keys
    provider=FakeProvider([plan]);planner=ReferencePlanner(provider,artifacts)
    planner.layout(analysis,frames,catalogue,[],'Rebuild',previous=plan,candidate_frames=frames)
    content=provider.calls[0]['request']['input'][0]['content'];assert 1<=len([p for p in content if p['type']=='input_image'])<=12
    context=json.loads(content[0]['text'].split('Untrusted observations:\n')[1])
    assert 'work-back' in [frame['key'] for frame in context['candidate_frames']]
    assert len(context['reference_frames'])==8
    assert set(keys)=={key for board in context['paired_comparison_images'] for key in (board.get('view_keys',[]) or [board.get('view_key')]) if key}
    priority=context['paired_comparison_images'][:2]
    assert [board['side'] for board in priority]==['REFERENCE','CANDIDATE']
    assert all(board['kind']=='priority_full_frame' for board in priority)


def test_reference_import_preserves_aspect_and_original_digest(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    image=io.BytesIO();Image.new('RGB',(2000,1000),'red').save(image,format='PNG')
    original=image.getvalue();bounded,metadata=bounded_image(original)
    assert metadata['model_size']==[1280,640] and metadata['original_size']==[2000,1000]
    root=tmp_path/'reference';root.mkdir();(root/'input.png').write_bytes(original)
    imported=ingest(dict(kind='external',media_files=['input.png']),root,artifacts)
    assert imported[0]['calibration'] is None and imported[0]['timestamp_seconds'] is None
    assert (root/'input.png').read_bytes()==original
    with pytest.raises(AgentError):ingest(dict(kind='external',media_files=['../outside.png']),root,artifacts)


def test_multiview_triangulation_uses_only_calibration_and_visible_boxes():
    a=dict(position_m=[-1,0,0],rotation_deg=[0,0,0],fov_deg=90)
    b=dict(position_m=[1,0,0],rotation_deg=[0,0,0],fov_deg=90)
    point=triangulate([(a,[.55,.45,.65,.55],1),(b,[.35,.45,.45,.55],1)])
    assert np.allclose(point,[0,0,5])
    assert triangulate([(a,[.55,.45,.65,.55],1)]) is None
    assert triangulate([(a,[.55,.45,.65,.55],1),(a,[.55,.45,.65,.55],1)]) is None
    assert np.allclose(rotation([0,90,0])@np.array([0,0,1]),[1,0,0])


def test_sam_unavailability_preserves_progress_and_does_not_abort_layout(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path);calls=[]
    def unavailable(*args):calls.append(1);raise AgentError('PROVIDER_USAGE_UNKNOWN','HTTP 503; reservation retained')
    p=ReferencePlanner(type('Unavailable',(),{'send':staticmethod(unavailable)})(),artifacts)
    results=p.segment(analysis,frames)
    assert len(calls)==1 and results[0]['source']=='sam_unavailable'
    calls.clear();results=p.segment(analysis,frames,cached_only=True)
    assert calls==[] and results[0]['source']=='not_requested'


def test_visual_matching_uses_actual_previews_and_refuses_unknown_asset(tmp_path):
    from hdrp_agent.reference_assets import boards,select_assets
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    extra=dict(catalogue[0],asset_id='asset-other',name='Other Chair');group=dict(object_key='chair',label='chair',reference_boxes=analysis['objects'][0]['view_boxes'],candidates=[catalogue[0],extra])
    Image.new('RGB',(128,128),'white').save(tmp_path/'chair.png');Image.new('RGB',(128,128),'black').save(tmp_path/'other.png')
    sheets=boards([group],frames,[dict(asset_id='asset-chair',file='chair.png'),dict(asset_id='asset-other',file='other.png')],tmp_path,artifacts)
    fake=FakeProvider([dict(matches=[dict(object_key='chair',asset_id='asset-other')],limits=[])])
    effective,response=select_assets(fake,artifacts,analysis,frames,[group],sheets)
    assert effective['objects'][0]['asset_id']=='asset-other' and analysis['objects'][0]['asset_id']=='asset-chair'
    fake=FakeProvider([dict(matches=[dict(object_key='chair',asset_id='asset-outside')],limits=[])])
    with pytest.raises(AgentError):select_assets(fake,artifacts,analysis,frames,[group],sheets)


def test_layout_allows_only_explicit_simple_supports_in_addition_to_identified_objects(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    ground=dict(plan['objects'][0],key='support_ground',asset_id=None,primitive='cube')
    plan['objects'].append(ground);validate_plan(plan,analysis,frames,catalogue)
    ground['key']='invented_decoration'
    with pytest.raises(AgentError):validate_plan(plan,analysis,frames,catalogue)


def test_occluded_view_does_not_discard_three_consistent_camera_rays():
    from hdrp_agent.reference_geometry import robust_triangulate
    a=dict(position_m=[-1,0,0],rotation_deg=[0,0,0],fov_deg=90);b=dict(a,position_m=[1,0,0]);c=dict(a,position_m=[0,1,0]);d=dict(a,position_m=[-1,1,0])
    observations=[(a,[.55,.45,.65,.55],1),(b,[.35,.45,.45,.55],1),(c,[.45,.55,.55,.65],1),(d,[.85,.8,.95,.9],1)]
    assert np.allclose(robust_triangulate(observations),[0,0,5])


def test_object_crop_uses_original_pixels_before_model_resize(tmp_path):
    from hdrp_agent.reference_details import original_crops
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    raw=io.BytesIO();Image.new('RGB',(4000,2000),'red').save(raw,format='PNG')
    frames[0]['original_artifact_hash']=artifacts.put(raw.getvalue(),'image/png')
    analysis['objects'][0]['view_boxes'][0]['bbox_xyxy']=[.4,.4,.6,.6]
    details=original_crops(analysis,frames,artifacts)
    assert details[0]['original_size']==[800,400] and details[0]['model_size']==[800,400]
    assert details[0]['object_key']=='chair' and details[0]['source_pixels']==[1600,800,2400,1200]
    assert details[0]['acquisition']=='original_resolution_crop'


def test_detail_matching_sends_each_candidate_at_native_resolution(tmp_path):
    from hdrp_agent.reference_assets import select_assets
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    other=dict(catalogue[0],asset_id='asset-other',name='Other Chair')
    group=dict(object_key='chair',label='chair',reference_boxes=analysis['objects'][0]['view_boxes'],candidates=[catalogue[0],other])
    for name in ['a.png','b.png']:Image.new('RGB',(1280,640),'white').save(tmp_path/name)
    details=[dict(key='detail-000',object_key='chair',artifact_hash=frames[0]['artifact_hash'],acquisition='native_camera_closeup')]
    provider=FakeProvider([dict(matches=[dict(object_key='chair',asset_id='asset-other')],limits=[])])
    effective,response=select_assets(provider,artifacts,analysis,frames,[group],[],details=details,previews=[dict(asset_id='asset-chair',file='a.png'),dict(asset_id='asset-other',file='b.png')],directory=tmp_path)
    assert effective['objects'][0]['asset_id']=='asset-other' and analysis['objects'][0]['asset_id']=='asset-chair'
    content=provider.calls[0]['request']['input'][0]['content']
    assert len([part for part in content if part['type']=='input_image'])==4
    assert len(response['object_responses'])==1


def test_native_details_refuse_forged_object_or_wrong_source_version(tmp_path,monkeypatch):
    import hdrp_agent.reference_details as module
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    pose=frames[0]['calibration'];pose=dict(pose,key='detail-000')
    checked=dict(request=dict(version_id='source-v1',include_clip=False,plan=dict(work_views=[pose])),statics=[dict(camera_key='detail-000',file='detail-000.png')])
    monkeypatch.setattr(module,'read_capture',lambda root:checked)
    Image.new('RGB',(1280,720),'white').save(tmp_path/'detail-000.png')
    result=dict(captures=[dict(capture_directory=str(tmp_path),views=[dict(pose,object_key='chair',angle='front')])],limits=[])
    assert module.native_details(result,analysis,tmp_path,'source-v1',artifacts)[0]['object_key']=='chair'
    with pytest.raises(AgentError):module.native_details(result,analysis,tmp_path,'another-source',artifacts)
    result['captures'][0]['views'][0]['object_key']='invented'
    with pytest.raises(AgentError):module.native_details(result,analysis,tmp_path,'source-v1',artifacts)


def test_detail_matched_variant_is_frozen_during_layout(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    catalogue.append(dict(catalogue[0],asset_id='asset-other',name='Chair_other'))
    provider=FakeProvider([plan]);ReferencePlanner(provider,artifacts).layout(analysis,frames,catalogue,[],'Rebuild',matched_assets=True)
    context=json.loads(provider.calls[0]['request']['input'][0]['content'][0]['text'].split('Untrusted observations:\n')[1])
    assert context['allowed_asset_variants']==[]
    assert 'asset-other' not in json.dumps(context['catalogue'])
    plan['objects'][0]['asset_id']='asset-other'
    with pytest.raises(AgentError):ReferencePlanner(FakeProvider([plan]),artifacts).layout(analysis,frames,catalogue,[],'Rebuild',matched_assets=True)


def test_initial_intact_floor_does_not_exclude_broken_variants_from_detail_match(tmp_path):
    from hdrp_agent.reference_assets import candidate_groups
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    catalogue[0].update(name='Floor_3x3',bounds_size_m=[3,.1,3])
    catalogue.extend([dict(catalogue[0],asset_id='broken-a',name='Floor_3x3_broken_A'),dict(catalogue[0],asset_id='broken-b',name='Floor_3x3_broken_B'),dict(catalogue[0],asset_id='trim',name='Floor_trim_door')])
    groups=candidate_groups(analysis,catalogue)
    assert {a['asset_id'] for a in groups[0]['candidates']}=={'asset-chair','broken-a','broken-b'}


def test_last_object_family_is_not_silently_skipped(tmp_path):
    from hdrp_agent.reference_assets import candidate_groups
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    catalogue=[dict(catalogue[0],asset_id='a',name='Floor_3x3'),dict(catalogue[0],asset_id='b',name='Floor_3x3_broken_A')]
    analysis['objects']=[dict(analysis['objects'][0],key='object-'+str(i),asset_id='a') for i in range(20)]
    assert len(candidate_groups(analysis,catalogue))==20


def test_matching_can_reuse_verified_exact_response_without_sending(tmp_path):
    from hdrp_agent.reference_assets import select_assets
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    group=dict(object_key='chair',label='chair',reference_boxes=analysis['objects'][0]['view_boxes'],candidates=catalogue)
    Image.new('RGB',(1280,640),'white').save(tmp_path/'preview.png')
    seen=[];retained=[];provider=FakeProvider([])
    def recover(request):seen.append(request);return dict(value=dict(matches=[dict(object_key='chair',asset_id='asset-chair')],limits=[]),reprocessed=True,network_sent=False)
    effective,response=select_assets(provider,artifacts,analysis,frames,[group],[],details=[],previews=[dict(asset_id='asset-chair',file='preview.png')],directory=tmp_path,recover_exact=recover,on_response=retained.append)
    assert len(seen)==1 and len(retained)==1 and provider.calls==[] and response['object_responses'][0]['network_sent'] is False


def test_pose_boards_preserve_shared_crop_displacement_and_evidence(tmp_path):
    from hdrp_agent.reference_comparison import correction_boards
    from PIL import Image,ImageDraw
    import io
    class Artifacts:
        def __init__(self):self.data={}
        def read(self,key):return self.data[key]
        def put(self,data,mime):
            import hashlib
            key=hashlib.sha256(data).hexdigest();self.data[key]=data;return key
    artifacts=Artifacts();frames=[];candidates=[]
    for offset,collection in [(0,frames),(20,candidates)]:
        im=Image.new('RGB',(200,100),'black');ImageDraw.Draw(im).rectangle((70+offset,30,90+offset,70),fill='white');buf=io.BytesIO();im.save(buf,format='PNG')
        collection.append(dict(key='view',artifact_hash=artifacts.put(buf.getvalue(),'image/png'),model_size=[200,100],calibration=None))
    analysis=dict(objects=[dict(key='chair',view_boxes=[dict(view_key='view',bbox_xyxy=[.35,.3,.45,.7])])])
    plan=dict(objects=[dict(key='chair',asset_id=None)])
    images,metadata=correction_boards(artifacts,analysis,frames,candidates,plan,[])
    assert len(images)==2 and metadata[1]['rows'][0]['reference_hash']==frames[0]['artifact_hash']
    assert metadata[1]['rows'][0]['candidate_hash']==candidates[0]['artifact_hash']
    with Image.open(io.BytesIO(images[1])) as board:
        a=np.asarray(board);half=board.width//2
        assert not np.array_equal(a[:,:half],a[:,half:])


def test_multiview_sam_silhouettes_correct_a_wrong_quarter_turn():
    from hdrp_agent.reference_pose import fit_mask_poses
    from PIL import Image,ImageDraw
    import hashlib,io,math
    class Artifacts:
        def __init__(self):self.data={}
        def read(self,key):return self.data[key]
        def put(self,data):
            key=hashlib.sha256(data).hexdigest();self.data[key]=data;return key
    artifacts=Artifacts()
    vertices=np.array([[x,y,z] for x in [-.6,.6] for y in [-.5,.5] for z in [-.2,.2]])
    triangles=[0,1,3,0,3,2,4,6,7,4,7,5,0,4,5,0,5,1,2,3,7,2,7,6,0,2,6,0,6,4,1,5,7,1,7,3]
    geometry=[dict(asset_id='box',meshes=[dict(vertices=vertices.tolist(),triangles=triangles)])]
    frames=[];segments=[]
    for key,position,yaw in [('front',[0,0,-4],0),('side',[-4,0,0],90)]:
        view=dict(position_m=position,rotation_deg=[0,yaw,0],fov_deg=60);p=(vertices-position)@rotation(view['rotation_deg']);t=math.tan(math.radians(30));uv=np.column_stack([(.5+p[:,0]/p[:,2]/(2*t*320/180))*320,(.5-p[:,1]/p[:,2]/(2*t))*180])
        im=Image.new('L',(320,180));draw=ImageDraw.Draw(im)
        for tri in np.array(triangles).reshape(-1,3):draw.polygon([tuple(point) for point in uv[tri]],fill=255)
        bbox=im.getbbox();crop=im.crop(bbox);buf=io.BytesIO();crop.save(buf,format='PNG')
        frames.append(dict(key=key,calibration=view,model_size=[320,180]));segments.append(dict(object_key='object',view_key=key,selection=dict(confidence=1,bbox_xyxy=[v/d for v,d in zip(bbox,[320,180,320,180])],mask_hash=artifacts.put(buf.getvalue()))))
    plan=dict(objects=[dict(key='object',asset_id='box',position_m=[0,0,0],rotation_deg=[0,90,0],scale=[1,1,1])])
    fitted,report=fit_mask_poses(plan,frames,segments,geometry,artifacts)
    assert report[0]['accepted'] and report[0]['best_mean_iou']>.95
    assert fitted['objects'][0]['rotation_deg'][1] in [0,180]
    assert fitted['objects'][0]['position_m'][1]==0
    assert plan['objects'][0]['rotation_deg'][1]==90
    assert fit_mask_poses(plan,frames,segments[:1],geometry,artifacts)[1]==[]

    # Front/back-symmetric geometry must not reverse a visually chosen facing
    # merely to gain a few silhouette pixels while correcting translation.
    plan['objects'][0]['rotation_deg'][1]=0
    plan['objects'][0]['position_m'][0]=.12
    aligned,ambiguous=fit_mask_poses(plan,frames,segments,geometry,artifacts)
    assert aligned['objects'][0]['rotation_deg'][1]==0
    assert ambiguous[0]['orientation_ambiguous']


def test_comprehensive_segmentation_covers_small_objects_and_priority_closeups(tmp_path,monkeypatch):
    import hdrp_agent.reference_planner as module
    artifacts,frames,catalogue,analysis,plan=data(tmp_path);frames.append(dict(frames[0],key='work-top-front'))
    analysis['objects']=[dict(analysis['objects'][0],key=f'object-{i}') for i in range(10)]
    details=[dict(frames[0],key=f'detail-{i}-{angle}',object_key=f'object-{i}',angle=angle) for i in range(10) for angle in ['front','top']]
    observed=[]
    def segment(self,frame,label,**kwargs):observed.append(frame['key']);return dict(source='fixture',regions=[])
    monkeypatch.setattr(module.Segmenter,'segment',segment)
    results=ReferencePlanner(None,artifacts).segment(analysis,frames,details=details,comprehensive=True)
    assert {s['object_key'] for s in results}=={f'object-{i}' for i in range(10)}
    assert sum(key=='work-top-front' for key in observed)==10
    assert len(results)<=50 and all(any(s['object_key']==f'object-{i}' and s['view_key']==f'detail-{i}-top' for s in results) for i in range(10))


def test_prefab_shape_hint_is_reported_as_source_conflict(tmp_path):
    artifacts,frames,catalogue,analysis,plan=data(tmp_path)
    plan['objects'][0]['primitive']='cube'
    with pytest.raises(AgentError) as error:validate_plan(plan,analysis,frames,catalogue)
    assert error.value.code=='INVALID_OBJECT_SOURCE'
    assert 'chair' in error.value.message
