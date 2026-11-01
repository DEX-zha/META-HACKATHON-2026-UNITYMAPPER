import pytest
from hdrp_agent.house_supports import footprint_supported


def triangle(a,b,c):
    return [[a[0],.8,a[1]],[b[0],.8,b[1]],[c[0],.8,c[1]]]


def test_real_support_rejects_hole_and_overhang():
    # Four strips around a central sink hole. A bounding box would pass it.
    triangles=[]
    for x0,z0,x1,z1 in [(0,0,1,.3),(0,.7,1,1),(0,.3,.3,.7),(.7,.3,1,.7)]:
        triangles.extend([triangle((x0,z0),(x1,z0),(x1,z1)),triangle((x0,z0),(x1,z1),(x0,z1))])
    assert footprint_supported(triangles,[.05,.05,.25,.25])
    assert not footprint_supported(triangles,[.2,.2,.8,.8])
    assert not footprint_supported(triangles,[-.1,0,.1,.1])


def test_duplicate_triangles_do_not_hide_a_hole():
    half=triangle((0,0),(1,0),(0,1))
    assert not footprint_supported([half,half],[0,0,1,1])
    assert not footprint_supported([], [0,0,1,1])
    with pytest.raises(ValueError):footprint_supported([half],[0,0,0,1])
