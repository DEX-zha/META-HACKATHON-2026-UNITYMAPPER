from copy import deepcopy
import numpy as np
import pytest
from hdrp_agent.domain import AgentError
from hdrp_agent.reference_metrics import mask_metrics,bind_measurements,appearance_metrics


def test_geometry_error_is_independent_of_rgb_and_unknown_is_not_zero():
    a=np.zeros((64,64),bool);a[20:40,20:40]=True;b=np.roll(a,5,axis=1)
    exact=mask_metrics(a,a);shifted=mask_metrics(a,b)
    assert exact['visible_iou']==1 and exact['contour_error_px']==0
    assert shifted['visible_iou']<.7 and shifted['centroid_error_px']==5
    assert mask_metrics(np.zeros_like(a),b)['missing_reason']=='empty_reference_mask'
    assert appearance_metrics(np.zeros((64,64,3)),np.ones((64,64,3)))['rgb_mae']==1


def test_measurement_cannot_describe_plan_before_native_contact():
    plan=dict(objects=[dict(key='a',position_m=[0,0,0])]);applied=deepcopy(plan);applied['objects'][0]['position_m'][1]=.2
    result=bind_measurements(applied,'v-final',{'per_object':{}})
    assert result['stage']=='after_native_contacts'
    with pytest.raises(AgentError):bind_measurements(plan,'v-before',result,expected_version='v-final')
