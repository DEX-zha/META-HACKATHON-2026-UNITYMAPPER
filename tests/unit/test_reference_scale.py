from copy import deepcopy
from hdrp_agent.reference_scale import restore_origin_scale


def test_scale_origin_prevents_compounding_silhouette_growth():
    origin=dict(objects=[dict(key='prop',asset_id='a',primitive=None,scale=[1,1,1],position_m=[0,2,0])]);candidate=deepcopy(origin);candidate['objects'][0]['scale']=[1.13]*3
    restored,proof=restore_origin_scale(candidate,origin)
    assert restored==origin and candidate['objects'][0]['scale']==[1.13]*3
    assert proof['changes'] and not proof['source_transforms_used']
    candidate['objects'][0]['scale']=[1.3]*3
    unchanged,proof=restore_origin_scale(candidate,origin)
    assert unchanged==candidate and proof['unqualified'][0]['reason']=='scale_outside_origin_bound'


def test_scale_prior_cannot_cross_asset_identity():
    origin=dict(objects=[dict(key='prop',asset_id='old',primitive=None,scale=[1,1,1])]);candidate=deepcopy(origin);candidate['objects'][0].update(asset_id='new',scale=[1.1]*3)
    result,proof=restore_origin_scale(candidate,origin)
    assert result==candidate and not proof['changes']
