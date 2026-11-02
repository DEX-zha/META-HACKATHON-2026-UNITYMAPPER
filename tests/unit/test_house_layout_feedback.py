from hdrp_agent.house_layout_feedback import feedback


def test_internal_overlap_is_distinguished_from_room_anchor_failure():
    assets={'wardrobe':dict(bounds_size=[1.7,2.3,.67]),'dresser':dict(bounds_size=[2.2,.86,.53])}
    group=dict(id='storage',items=[dict(slot='wardrobe',asset='wardrobe',offset_m=[0,0],yaw_deg=270,support_slot=None),dict(slot='dresser',asset='dresser',offset_m=[0,-1.5],yaw_deg=270,support_slot=None)])
    result=feedback(dict(groups=[group]),dict(missing=[dict(reason='No placement found')],instances=[]),assets)
    assert result['internal_group_collisions'][0]['slots']==['wardrobe','dresser']
    group['items'][1]['offset_m']=[0,-2.1]
    assert not feedback(dict(groups=[group]),dict(missing=[],instances=[]),assets)['internal_group_collisions']
