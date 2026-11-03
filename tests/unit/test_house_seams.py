import pytest
from hdrp_agent.house_seams import audit,seam_rays


def plane(reverse=False,**props):
    # A horizontal ceiling whose visible normal points down into the room.
    t=[[[0,2.8,0],[1,2.8,0],[1,2.8,1]],[[0,2.8,0],[1,2.8,1],[0,2.8,1]]]
    if reverse:t=[list(reversed(x)) for x in t]
    return dict(renderer_id='ceiling',triangles_world=t,opaque=True,casts_shadows=True,**props)


def ray(x=.5):return dict(origin=[x,2.79,.5],direction=[0,1,0])


def test_winding_distinguished_from_missing_geometry_without_claiming_lighting():
    front=audit([plane()],[ray()]);back=audit([plane(True)],[ray()]);gap=audit([plane()],[ray(1.01)])
    assert front['counts']=={'front_facing_geometry':1}
    assert back['counts']=={'back_facing_geometry_only':1}
    assert gap['counts']=={'open_geometry':1}
    assert not front['lighting_qualified']


def test_transparent_first_hit_does_not_hide_opaque_closure_behind_it():
    glass=plane();glass['opaque']=False
    for t in glass['triangles_world']:
        for v in t:v[1]=2.795
    result=audit([glass,plane()],[ray()])['samples_detail'][0]
    assert result['status']=='front_facing_geometry'
    assert result['nearest_hit']['opaque'] is False
    assert result['nearest_opaque_hit']['opaque'] is True


def test_material_and_shadow_uncertainty_are_not_certified_as_occlusion():
    for field in ('opaque','casts_shadows'):
        m=plane();m[field]=None
        assert audit([m],[ray()])['counts']=={'unqualified_material_or_shadow_state':1}
        m[field]=False
        assert audit([m],[ray()])['counts']=={'non_occluding_geometry_only':1}


def test_shared_wall_probes_each_rooms_side_and_narrow_top_band():
    wall=dict(id='partition',start=[1,0],end=[1,2],room_ids=['left','right'])
    rooms=[dict(id='left',polygon=[[0,0],[1,0],[1,2],[0,2]]),dict(id='right',polygon=[[1,0],[2,0],[2,2],[1,2]])]
    rays=seam_rays([wall],rooms)
    assert all(2.749<=r['origin'][1]<=2.795 for r in rays)
    assert all(abs(r['origin'][0]-1)>=.25 for r in rays)
    assert all((r['origin'][0]<1 and r['direction'][0]>0) if r['room_id']=='left' else (r['origin'][0]>1 and r['direction'][0]<0) for r in rays)
    assert {r['below_ceiling_m'] for r in rays}=={.005,.02,.05}
    assert any(r['origin'][2]<.01 for r in rays) and any(r['origin'][2]>1.99 for r in rays)


def test_bad_geometry_or_ray_is_rejected():
    with pytest.raises(ValueError):audit([plane()],[dict(origin=[0,0,0],direction=[0,0,0])])
    with pytest.raises(ValueError):audit([dict(renderer_id='bad',triangles_world=[[[float('nan'),0,0]]])],[])


def test_geometry_layout_and_source_preservation_require_matching_native_receipt():
    from hdrp_agent.house_seams import validate_source
    from hdrp_agent.domain import fingerprint,canonical
    m=dict(run_id='run',building={})
    g=dict(method='editor_read_only_submesh_triangles_world_metres',meshes=[plane()],scene_sha256='hash',scene_path='candidate')
    p=dict(run_id='run',manifest_hash=fingerprint(m),scene_version='hash',scene_path='candidate',source_scene_unchanged=True)
    validate_source(g,canonical(m).encode(),p)
    for changed in (dict(scene_version='other'),dict(manifest_hash='other'),dict(source_scene_unchanged=False),dict(run_id='other')):
        with pytest.raises(ValueError):validate_source(g,canonical(m).encode(),dict(p,**changed))


def test_manifest_provenance_uses_exact_artifact_bytes_not_reserialization():
    import json,hashlib
    from hdrp_agent.house_seams import validate_source
    m=dict(run_id='run',building={});raw=json.dumps(m,indent=2).encode()
    g=dict(method='editor_read_only_submesh_triangles_world_metres',meshes=[plane()],scene_sha256='hash',scene_path='candidate')
    p=dict(run_id='run',manifest_hash=hashlib.sha256(raw).hexdigest(),scene_version='hash',scene_path='candidate',source_scene_unchanged=True)
    assert validate_source(g,raw,p)==m
    with pytest.raises(ValueError):validate_source(g,json.dumps(m).encode(),p)
