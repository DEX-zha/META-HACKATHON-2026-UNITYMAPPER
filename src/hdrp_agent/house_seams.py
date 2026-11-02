"""Geometric closure diagnostics for narrow wall/ceiling seams.

This compares triangle winding with two-sided intersections. It does not simulate
HDRP shadow maps or certify lighting quality; matched native renders are required.
Input vertices must be measured in world metres, without changing mesh imports.
"""
from math import isfinite, sqrt
from .domain import fingerprint


def validate_source(geometry,manifest,proof):
    """Reject unrelated geometry, layouts and native receipts before sampling."""
    if geometry.get('method')!='editor_read_only_submesh_triangles_world_metres' or not geometry.get('meshes'):
        raise ValueError('Native read-only world geometry export required')
    if not geometry.get('scene_sha256') or geometry.get('scene_sha256')!=proof.get('scene_version') or geometry.get('scene_path')!=proof.get('scene_path'):
        raise ValueError('Geometry and native scene receipt differ')
    if fingerprint(manifest)!=proof.get('manifest_hash') or manifest.get('run_id')!=proof.get('run_id'):
        raise ValueError('Native receipt belongs to a different manifest')
    if proof.get('source_scene_unchanged') is not True:
        raise ValueError('Source preservation is unverified')


def vector(value):
    if len(value)!=3 or any(type(v) not in (int,float) or not isfinite(v) for v in value):
        raise ValueError('Finite three-component vector required')
    return tuple(value)


def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def unit(v):
    v=vector(v);length=sqrt(dot(v,v))
    if length<1e-10:raise ValueError('Nonzero ray direction required')
    return tuple(x/length for x in v)


def intersection(origin,direction,triangle):
    """Return distance and front-facing flag, or None; direction must be unit."""
    a,b,c=triangle;e1=sub(b,a);e2=sub(c,a);p=cross(direction,e2);det=dot(e1,p)
    if abs(det)<1e-10:return None
    relative=sub(origin,a);u=dot(relative,p)/det
    if u< -1e-8 or u>1+1e-8:return None
    q=cross(relative,e1);v=dot(direction,q)/det
    if v< -1e-8 or u+v>1+1e-8:return None
    distance=dot(e2,q)/det
    if distance<=1e-5:return None
    return distance,det>0


def seam_rays(boundaries,rooms,*,height=2.8,step=.15):
    """Probe within 5 cm of each room's upper perimeter, including both corners.

    Rays go outward and upward through the seam. Each room gets its own side of
    a shared boundary. World-space vertices/room polygons determine the side.
    """
    if not isfinite(height) or height<=.06 or not isfinite(step) or step<=0:
        raise ValueError('Positive seam height and spacing required')
    result=[];by_id={r['id']:r for r in rooms}
    for wall in boundaries:
        ax,az=wall['start'];bx,bz=wall['end'];delta=vector((bx-ax,0,bz-az));length=sqrt(dot(delta,delta))
        tangent=unit(delta)
        for room_id in wall['room_ids']:
            poly=by_id[room_id]['polygon'];centre=(sum(p[0] for p in poly)/len(poly),0,sum(p[1] for p in poly)/len(poly))
            inward=(-tangent[2],0,tangent[0])
            if dot(inward,sub(centre,((ax+bx)/2,0,(az+bz)/2)))<0:inward=tuple(-x for x in inward)
            count=max(1,int(length/step))
            for i in range(count+1):
                along=min(length-.005,max(.005,length*i/count))
                for below in (.005,.02,.05):
                    origin=(ax+tangent[0]*along+inward[0]*.02,height-below,az+tangent[2]*along+inward[2]*.02)
                    for rise in (.1,1,4):
                        result.append(dict(room_id=room_id,boundary_id=wall['id'],origin=list(origin),
                            direction=list(unit((-inward[0],rise,-inward[2]))),below_ceiling_m=below))
    return result


def audit(meshes,rays,*,distance_m=1):
    """Report open geometry, back-facing-only hits and unknown material evidence."""
    if not isfinite(distance_m) or distance_m<=0:raise ValueError('Positive ray distance required')
    prepared=[]
    for mesh in meshes:
        triangles=[]
        for triangle in mesh['triangles_world']:
            if len(triangle)!=3:raise ValueError('Three vertices per triangle required')
            triangles.append(tuple(vector(v) for v in triangle))
        prepared.append((mesh,triangles))
    rows=[]
    for ray in rays:
        origin=vector(ray['origin']);direction=unit(ray['direction']);hits=[]
        for mesh,triangles in prepared:
            for triangle in triangles:
                hit=intersection(origin,direction,triangle)
                if hit and hit[0]<=distance_m:
                    hits.append(dict(renderer_id=mesh['renderer_id'],distance_m=hit[0],front_facing=hit[1],
                        opaque=mesh.get('opaque'),casts_shadows=mesh.get('casts_shadows')))
        hits.sort(key=lambda h:h['distance_m'])
        opaque=[h for h in hits if h['opaque'] is True and h['casts_shadows'] is True]
        front=[h for h in opaque if h['front_facing']]
        unknown=any(h['opaque'] is None or h['casts_shadows'] is None for h in hits)
        status=('front_facing_geometry' if front else 'back_facing_geometry_only' if opaque else
                'unqualified_material_or_shadow_state' if unknown else 'non_occluding_geometry_only' if hits else 'open_geometry')
        rows.append(dict(ray=ray,status=status,nearest_hit=hits[0] if hits else None,
            nearest_opaque_hit=opaque[0] if opaque else None,nearest_front_hit=front[0] if front else None))
    counts={status:sum(r['status']==status for r in rows) for status in sorted({r['status'] for r in rows})}
    return dict(method='world_triangle_upper_seam_rays',distance_m=distance_m,samples=len(rows),counts=counts,
        samples_detail=rows,lighting_qualified=False,
        limitations=['Triangle winding is not a simulation of the HDRP shadow caster pass.',
                    'Samples do not prove continuous watertightness.',
                    'Native matched-exposure sun-on/sun-off renders remain required.'])
