from copy import deepcopy
import numpy as np
import pytest
from hdrp_agent.domain import AgentError
from hdrp_agent.reference_support_graph import SupportGraph
from hdrp_agent.reference_geometry import rotation


def objects():return [dict(key=k,position_m=p,rotation_deg=[0,0,0],scale=[1,1,1]) for k,p in [('floor',[0,.8,0]),('table',[1,1,0]),('bottle',[1,2,0])]]

def test_group_translates_unknown_root_and_all_descendants_without_flattening():
    plan=dict(objects=objects());graph=SupportGraph(plan,[dict(object_key='table',support_key='floor'),dict(object_key='bottle',support_key='table')])
    moved=graph.transform_group(plan,'floor',[.1,.23,-.2])
    assert np.allclose(np.array([o['position_m'] for o in moved['objects']])-np.array([o['position_m'] for o in plan['objects']]),[.1,.23,-.2])
    assert plan['objects']==objects() and graph.roots==['floor']
    assert graph.relative_pose(plan,'bottle')['position_m']==[0,1,0]

def test_group_rotation_rotates_positions_and_orientations_about_support():
    plan=dict(objects=objects());g=SupportGraph(plan,[dict(object_key='table',support_key='floor'),dict(object_key='bottle',support_key='table')]);m=g.transform_group(plan,'floor',[0,0,0],yaw_deg=90)
    assert np.allclose(m['objects'][1]['position_m'],[0,1,-1],atol=1e-8)
    assert m['objects'][2]['rotation_deg']==[0,90,0]


def test_relative_frame_accounts_for_support_orientation_and_scale():
    plan=dict(objects=objects());parent=plan['objects'][1];child=plan['objects'][2]
    parent.update(rotation_deg=[12,35,-8],scale=[2,3,4])
    child['position_m']=(np.array(parent['position_m'])+rotation(parent['rotation_deg'])@np.array([.4,1.5,.8])).tolist()
    child['rotation_deg']=[21,-10,15];child['scale']=[.4,.6,.8]
    graph=SupportGraph(plan,[dict(object_key='bottle',support_key='table',contact_policy='offset_evidenced')])
    relative=graph.relative_pose(plan,'bottle')
    assert np.allclose(relative['position_m'],[.2,.5,.2])
    assert np.allclose(relative['scale'],[.2,.2,.2])
    assert np.allclose(rotation(parent['rotation_deg'])@rotation(relative['rotation_deg']),rotation(child['rotation_deg']))
    assert graph.policies['bottle']=='offset_evidenced'

@pytest.mark.parametrize('edges',[[('floor','bottle'),('bottle','floor')],[('ghost','floor')],[('table','unknown')],[('table','floor'),('table',None)]])
def test_invalid_support_graph_cannot_mutate(edges):
    with pytest.raises(AgentError):SupportGraph(dict(objects=objects()),[dict(object_key=k,support_key=p) for k,p in edges])


def test_tilted_group_composes_all_rotations_and_preserves_relative_pose():
    plan=dict(objects=objects());plan['objects'][1]['rotation_deg']=[12,31,-7]
    graph=SupportGraph(plan,[dict(object_key='table',support_key='floor'),dict(object_key='bottle',support_key='table')])
    before=graph.relative_pose(plan,'bottle')
    moved=graph.transform_group(plan,'floor',[.03,-.17,.02],rotation_deg=[4,7,-3])
    after=graph.relative_pose(moved,'bottle')
    assert np.allclose(before['position_m'],after['position_m'])
    assert np.allclose(rotation(before['rotation_deg']),rotation(after['rotation_deg']))
    assert moved['objects'][1]['scale']==plan['objects'][1]['scale']
