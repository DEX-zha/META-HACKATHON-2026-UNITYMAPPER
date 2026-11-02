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
    result=assemble(m,build=build,inspect=lambda *args:[],repair=lambda *args:None,record=lambda r,z,s,p:events.append((z,s)),guard=lambda:None)
    assert calls==[['desk'],['desk','bad'],['desk','plant']]
    assert [i['id'] for i in result[0]['instances']]==['desk','plant']
    assert ('sleep','rejected_native') in events


def test_visual_fault_invokes_repair_before_zone_acceptance():
    events=[];repairs=[]
    def repair(m,r,p,obs,*args):repairs.append(obs);return m,r,p,[]
    m=dict(instances=[item('desk','work')],access=[])
    assemble(m,build=lambda m:({},proof(m)),inspect=lambda *a:[dict(kind='collision')],repair=repair,record=lambda r,z,s,p:events.append(s),guard=lambda:None)
    assert repairs and events==['building','accepted']
