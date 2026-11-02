from hdrp_agent.house_zones import assemble,batches


def item(id,group,support=None):return dict(id=id,group_id=group,room_id='room',support_id=support)
def proof(m,defects=()):return dict(source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in m['instances']],captures=[dict(room_id='room',usable=True)],defects=list(defects))


def test_zones_keep_supported_props_with_parent():
    groups=batches([item('desk','work'),item('book','details','desk'),item('bed','sleep')])
    assert [[i['id'] for i in xs] for _,xs in groups]==[['desk','book'],['bed']]


def test_zone_is_checked_before_next_and_native_regression_rolls_back():
    calls=[];events=[]
    def build(m):
        ids=[i['id'] for i in m['instances']];calls.append(ids)
        return {},proof(m,[dict(kind='support')] if 'bad' in ids else [])
    m=dict(instances=[item('desk','work'),item('bad','sleep'),item('plant','green')],access=[])
    result=assemble(m,build=build,inspect=lambda *args:[],repair=lambda m,r,p,o,*args:(m,r,p,o),record=lambda r,z,s,p:events.append((z,s)),guard=lambda:None)
    assert calls==[['desk'],['desk','bad'],['desk','plant']]
    assert [i['id'] for i in result[0]['instances']]==['desk','plant']
    assert ('sleep','unresolved') in events


def test_visual_fault_invokes_repair_before_zone_acceptance():
    events=[];repairs=[]
    def repair(m,r,p,obs,*args):repairs.append(obs);return m,r,p,[]
    m=dict(instances=[item('desk','work')],access=[])
    assemble(m,build=lambda m:({},proof(m)),inspect=lambda *a:[dict(kind='collision')],repair=repair,record=lambda r,z,s,p:events.append(s),guard=lambda:None)
    assert repairs and events==['building','accepted']


def test_native_support_failure_is_repaired_before_next_zone():
    from copy import deepcopy
    calls=[];events=[]
    def build(m):
        calls.append([i['id'] for i in m['instances']])
        bad=[dict(kind='support',instance_id='bed',message='No supporting surface')]
        p=proof(m,bad if any(i['id']=='bed' and not i.get('fixed') for i in m['instances']) else [])
        return {'details_artifact_hash':'native-receipt'},p
    def repair(m,r,p,obs,*args):
        assert obs[0]['kind']=='support' and obs[0]['instance_id']=='bed'
        assert obs[0]['suggested_action']=='none' and obs[0]['evidence_ids']==['native-receipt']
        fixed=deepcopy(m);fixed['instances'][0]['fixed']=True
        receipt,evidence=build(fixed)
        return fixed,receipt,evidence,[]
    m=dict(instances=[item('bed','sleep'),item('desk','work')],access=[])
    result=assemble(m,build=build,inspect=lambda *a:[],repair=repair,record=lambda r,z,s,p:events.append((z,s)),guard=lambda:None)
    assert calls==[['bed'],['bed'],['bed','desk']]
    assert result[0]['instances'][0]['fixed']
    assert events==[('sleep','building'),('sleep','accepted'),('work','building'),('work','accepted')]


def test_isolation_identity_and_coverage_failures_never_enter_layout_repair():
    from copy import deepcopy
    from hdrp_agent.house_zones import repairable_native
    base=proof(dict(instances=[item('bed','sleep')]),[dict(kind='support',instance_id='bed')])
    assert repairable_native(base)
    for field in ('connected','native_scale'):
        p=deepcopy(base);p['instances'][0][field]=False
        assert not repairable_native(p)
    p=deepcopy(base);p['source_scene_unchanged']=False
    assert not repairable_native(p)
    p=deepcopy(base);p['captures'][0]['usable']=False
    assert not repairable_native(p)


def test_native_observations_keep_scope_and_do_not_invent_a_delta():
    from hdrp_agent.house_zones import native_observations
    p=proof(dict(instances=[item('bed','sleep')]),[
        dict(kind='passage',target=dict(room_id='room'),message='Disconnected path'),
        dict(kind='support',room_id='other',instance_id='other-bed',message='Missing support')])
    p['instances'][0]['support_passed']=False
    obs=native_observations(p,{'details_artifact_hash':'receipt'},'room')
    assert [o['kind'] for o in obs]==['passage','support']
    assert all(o['room_id']=='room' and o['translation_m']==[0,0,0] for o in obs)
