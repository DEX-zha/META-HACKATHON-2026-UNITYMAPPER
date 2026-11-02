from hdrp_agent.house_support_candidates import candidates


def surface(id,y):
    return dict(id=id,triangles=[[[0,y,0],[1,y,0],[1,y,1]],[[0,y,0],[1,y,1],[0,y,1]]])


def test_candidates_measure_overhead_without_asserting_semantic_approval():
    result=candidates(dict(surfaces=[surface('lower',.5),surface('upper',.8)]))
    assert len(result)==2
    assert abs(result[0]['overhead_clearance_m']-.3)<1e-8
    assert result[1]['overhead_clearance_m'] is None
    assert all(r['qualification']=='geometry_candidate' for r in result)


def test_missing_half_of_surface_not_usable():
    s=surface('hole',.5);s['triangles']=s['triangles'][:1]
    assert not candidates(dict(surfaces=[s]))


def test_duplicate_triangles_cannot_cover_a_hole():
    s=surface('overlap',.5);s['triangles']=[s['triangles'][0]]*2
    assert not candidates(dict(surfaces=[s]))
