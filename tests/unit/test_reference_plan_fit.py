from copy import deepcopy
from PIL import Image
from hdrp_agent.reference_plan_fit import exposure_probe,fit_overhead_plan,luminance_stats


def test_exposure_bracket_uses_rejected_frames_and_freezes_lights():
    def attempt(ev,median,bright):return dict(applied_plan=dict(exposure_ev=ev,lights=[dict(intensity=8000)]),metrics=dict(plan_photometry=dict(reference=dict(median=.65,bright_fraction=.02),candidate=dict(median=median,bright_fraction=bright))))
    a=attempt(.5,.99,.8);assert exposure_probe([a])['exposure_ev']==2.5
    b=attempt(6.5,.03,0);proposal=exposure_probe([a,b]);assert proposal['exposure_ev']==3.5 and proposal['lights']==a['applied_plan']['lights']
    assert exposure_probe([attempt(3.5,.65,.03)]) is None
    assert luminance_stats(Image.new('RGB',(100,100),'white'),[.1,.1,.9,.9])['bright_fraction']==1


def test_overhead_regions_fit_centres_without_source_scene_poses():
    cat=[dict(asset_id='floor',name='Floor_6x3',bounds_center_m=[-3,0,1.5],bounds_size_m=[6,0,3]),dict(asset_id='table',name='Table_coffee',bounds_center_m=[0,.3,0],bounds_size_m=[1,.6,.5])]
    def obj(key,pos):return dict(key=key,asset_id=key,position_m=pos,rotation_deg=[0,0,0],scale=[1,1,1])
    plan=dict(objects=[obj('floor',[3,0,-1.5]),obj('table',[2,0,2])],estimated_views=[])
    analysis=dict(objects=[dict(key='floor',view_boxes=[dict(view_key='ref',bbox_xyxy=[.1,.2,.9,.8])]),dict(key='table',view_boxes=[dict(view_key='ref',bbox_xyxy=[.4,.4,.6,.6])])])
    original=deepcopy(plan);new,proof=fit_overhead_plan(plan,analysis,[dict(key='ref',calibration=None,model_size=[1600,900])],cat,[])
    assert plan==original and proof[0]['metric_dimensions_estimated']
    assert abs(new['objects'][1]['position_m'][0])<1e-6 and abs(new['objects'][1]['position_m'][2])<1e-6
    assert new['estimated_views'][0]['fov_deg']>=10
    from hdrp_agent.reference_worker import inspection_for
    from hdrp_agent.domain import payload
    payload('InspectionPlan',inspection_for([dict(key='ref',model_size=[1600,900])],new))
    assert fit_overhead_plan(plan,analysis,[dict(calibration={})],cat,[])==(plan,[])
