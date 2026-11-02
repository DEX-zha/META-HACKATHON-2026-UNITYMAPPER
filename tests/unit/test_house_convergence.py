from copy import deepcopy
from hdrp_agent.house_convergence import converge


def proof(manifest,defects=()):
    return dict(scene_path='generated',scene_version=str(manifest.get('exposure_ev',6)),source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in manifest['instances']],defects=list(defects),captures=[dict(mean_rgb=.98 if manifest.get('exposure_ev',6)<14 else .5)])


def test_convergence_continues_beyond_six_passes_without_quota():
    m=dict(instances=[],exposure_ev=6);events=[]
    def build(m):return {},proof(m)
    # Actual decreasing evidence, eight passes to reach the usable range.
    def render(m):
        p=proof(m);p['captures'][0]['mean_rgb']=.98-(m['exposure_ev']-6)*.025
        return {},p
    output=converge(m,{},proof(m),[],build=render,inspect=lambda *a:[],enrich=lambda *a:None,record=lambda n,s,*a:events.append((n,s)),guard=lambda:None)
    assert output[0]['exposure_ev']==14
    assert len([s for _,s in events if s=='accepted'])==8


def test_regression_preserves_selected_scene_and_does_not_retry_same_pose():
    m=dict(instances=[],exposure_ev=6);original=proof(m);events=[]
    def build(candidate):return {},proof(candidate,[dict(kind='support',instance_id='a')])
    result=converge(m,{},original,[],build=build,inspect=lambda *a:(_ for _ in ()).throw(AssertionError('Do not review native regression')),enrich=lambda *a:None,record=lambda n,s,*a:events.append(s),guard=lambda:None)
    assert result[0]==m and result[2]==original
    assert events==['proposed','rejected']


def test_enrichment_is_reinspected_and_preserves_previous_equipment():
    m=dict(instances=[dict(id='desk')],exposure_ev=14);events=[]
    def enrich(m,*args):
        if len(m['instances'])>1:return None
        n=deepcopy(m);n['instances'].append(dict(id='books'));return n,dict(kind='enrich_room')
    result=converge(m,{},proof(m),[],build=lambda m:({},proof(m)),inspect=lambda *a:[],enrich=enrich,record=lambda n,s,*a:events.append(s),guard=lambda:None)
    assert [i['id'] for i in result[0]['instances']]==['desk','books']
    assert events==['proposed','accepted']


def test_unusable_views_cannot_erase_visual_defects():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='desk')],exposure_ev=14))
    after=deepcopy(before);after['captures'][0]['usable']=False
    defect=dict(room_id='house',instance_id='desk',kind='composition',severity='blocking')
    passed,_=acceptable(before,after,[defect],[],dict(kind='transform_group'))
    assert not passed


def test_enrichment_cannot_upgrade_warning_to_blocking():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='desk')],exposure_ev=14));after=deepcopy(before);after['instances'].append(dict(id='book',connected=True,native_scale=True,support_passed=True))
    warning=dict(room_id='house',instance_id='desk',kind='passage',severity='warning')
    assert not acceptable(before,after,[warning],[dict(warning,severity='blocking')],dict(kind='enrich_room'))[0]


def test_rejected_candidate_triggers_fresh_reasoning_once_per_rejection():
    m=dict(instances=[],exposure_ev=6);reviews=[]
    def build(candidate):return {},proof(candidate,[dict(kind='support')])
    result=converge(m,{},proof(m),[],build=build,inspect=lambda *a:[],enrich=lambda *a:None,record=lambda *a:None,guard=lambda:None,reconsider=lambda *a:reviews.append('rethink') or [])
    assert reviews==['rethink'] and result[0]==m


def test_unactionable_initial_defect_replans_without_any_prior_rejection():
    m=dict(instances=[],exposure_ev=14);reviews=[]
    defect=dict(room_id='house',instance_id='',kind='lighting',severity='blocking',suggested_action='none')
    result=converge(m,{},proof(m),[defect],build=lambda m:({},proof(m)),inspect=lambda *a:[defect],enrich=lambda *a:None,record=lambda *a:None,guard=lambda:None,reconsider=lambda *a:reviews.append('repair') or [])
    assert reviews==['repair']
    assert result[3]==[defect]  # Planning cannot erase evidence.
