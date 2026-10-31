import numpy as np
from hdrp_agent.reference_metrics import appearance_regions,assess_appearance


def measurements():
    target=np.full((32,32,3),.5);previous=target+.2;candidate=target.copy();region=np.zeros((32,32),bool);region[4:12,4:12]=True
    return target,previous,candidate,{'object':region}


def test_local_saturation_vetoes_better_global_appearance():
    target,previous,candidate,regions=measurements();candidate[regions['object']]=1
    before=appearance_regions(target,previous,regions);after=appearance_regions(target,candidate,regions)
    assert after['global_metrics']['luminance_mae']<before['global_metrics']['luminance_mae']
    accepted,issues=assess_appearance(before,after,reference_protocol='same',candidate_protocol='same',controls={'control':{'before':.1,'after':.1}},noise_bound=.001)
    assert not accepted and any(i['kind']=='appearance_region_regression' for i in issues)


def test_control_regression_and_unqualified_protocol_refuse_gain():
    target,previous,candidate,regions=measurements();before=appearance_regions(target,previous,regions);after=appearance_regions(target,candidate,regions)
    accepted,issues=assess_appearance(before,after,reference_protocol='game',candidate_protocol='editor',controls={},noise_bound=None)
    assert not accepted and {i['kind'] for i in issues}=={'capture_protocol_unqualified','missing_control_views','capture_noise_unqualified'}
    assert not assess_appearance(before,after,reference_protocol='same',candidate_protocol='same',controls={'hidden':{'before':.1,'after':.3}},noise_bound=.001)[0]
    assert assess_appearance(before,after,reference_protocol='same',candidate_protocol='same',controls={'hidden':{'before':.1,'after':.1}},noise_bound=.001)[0]


def test_missing_region_stays_unknown_and_images_are_not_mutated():
    target,previous,candidate,regions=measurements();regions['tiny']=np.zeros((32,32),bool)
    measured=appearance_regions(target,previous,regions)
    assert not measured['regions']['tiny']['measured']
    assert np.all(target==.5) and np.all(previous==.7)


def test_control_measurements_stay_out_of_model_context():
    import json
    from hdrp_agent.reference_memory import prompt_metrics
    result=prompt_metrics(dict(per_view={'work-front':{'score':.2},'control-private-sentinel':{'score':.9}}))
    assert 'work-front' in result['per_view']
    assert 'private-sentinel' not in json.dumps(result)


def test_lighting_subexperiments_freeze_object_poses_and_other_light_parameters():
    from copy import deepcopy
    from hdrp_agent.reference_memory import constrain_proposal,appearance_step
    from hdrp_agent.domain import fingerprint
    original=dict(objects=[dict(key='prop',position_m=[0,1,0],scale=[1,1,1])],lights=[dict(type='spot',position_m=[0,3,0],rotation_deg=[90,0,0],spot_angle_deg=45,intensity=100,color_rgb=[1,1,1])],exposure_ev=0,sky_color_rgb=[.1]*3,fog_mean_free_path_m=20,notes=[])
    proposed=deepcopy(original);proposed['objects'][0]['position_m']=[1,2,3];proposed['lights'][0].update(position_m=[1,4,2],intensity=200);proposed.update(exposure_ev=2,sky_color_rgb=[.4]*3,fog_mean_free_path_m=40)
    for step in ['light_geometry','photometry','atmosphere']:
        result=constrain_proposal(proposed,original,'appearance',step)
        assert fingerprint(result['objects'])==fingerprint(original['objects'])
        if step=='light_geometry':assert result['lights'][0]['intensity']==100 and result['exposure_ev']==0 and result['lights'][0]['position_m']==[1,4,2]
        if step=='photometry':assert result['lights'][0]['position_m']==[0,3,0] and result['lights'][0]['intensity']==200 and result['exposure_ev']==2
        if step=='atmosphere':assert result['lights']==original['lights'] and result['exposure_ev']==0 and result['fog_mean_free_path_m']==40
    assert appearance_step({'history':[]})=='light_geometry'
    assert appearance_step({'history':[{'phase':'appearance'}]})=='photometry'


def test_native_capture_protocol_and_control_frames_are_measured_separately(tmp_path):
    from PIL import Image
    from hdrp_agent.reference_appearance import measure_capture_pair,assess_capture_appearance
    protocol=dict(render_path='native_gameview',exposure_mode='Fixed',anti_aliasing='None',dynamic_resolution=False,physical_camera=True)
    def capture(name,work,control,proto):
        path=tmp_path/name;path.mkdir();Image.new('RGB',(32,32),(work,)*3).save(path/'work.png');Image.new('RGB',(32,32),(control,)*3).save(path/'control.png')
        return dict(directory=path,statics=[dict(camera_key='work-front',role='work',file='work.png'),dict(camera_key='control-private',role='control',file='control.png')],request=dict(version_id=name,conditions_hash='same',inspection_hash='same'),result=dict(render_protocol=proto))
    reference=capture('reference',128,128,protocol);before=capture('before',170,128,protocol);after=capture('after',128,128,protocol)
    noise=dict(conditions_hash='same',inspection_hash='same',noise_bound=.001)
    a=measure_capture_pair(reference,before,dict(objects=[]),noise=noise);b=measure_capture_pair(reference,after,dict(objects=[]),noise=noise)
    assert b['protocol_qualified'] and 'control-private' not in b['work_views']
    assert assess_capture_appearance(a,b)[0]
    after['result']['render_protocol']=None
    assert not measure_capture_pair(reference,after,dict(objects=[]),noise=noise)['protocol_qualified']


def test_private_control_veto_details_do_not_leak_through_history():
    import json
    from hdrp_agent.reference_memory import new_memory,prompt_memory
    memory=new_memory('evidence',dict(objects=[]))
    memory['history']=[dict(run_id='r',ordinal=1,phase='appearance',accepted=False,score=.1,appearance_experiment='photometry',regressions=[dict(kind='appearance_control_regression',view_key='control-private-sentinel',delta=.8),dict(kind='appearance_view_regression',view_key='work-front')])]
    context=prompt_memory(memory)
    assert 'private-sentinel' not in json.dumps(context)
    assert context['history'][0]['appearance_experiment']=='photometry'
    assert context['history'][0]['regressions']==[dict(kind='appearance_view_regression',view_key='work-front')]
