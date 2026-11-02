"""Geometric proposals for visual support review; proposals are never approvals."""
from .house_supports import footprint_supported


def candidates(asset):
    result=[]
    for surface in asset.get('surfaces',[]):
        triangles=surface.get('triangles',[])
        points=[v for t in triangles for v in t]
        if not points:
            continue
        # Inset the measured patch; reject holes and disconnected/overlapping geometry.
        rectangle=[min(v[0] for v in points)+.02,min(v[2] for v in points)+.02,max(v[0] for v in points)-.02,max(v[2] for v in points)-.02]
        if rectangle[2]-rectangle[0]<.08 or rectangle[3]-rectangle[1]<.08:
            continue
        if not footprint_supported(triangles,rectangle):
            continue
        height=sum(v[1] for v in points)/len(points)
        above=[]
        for other in asset.get('surfaces',[]):
            for t in other.get('triangles',[]):
                y=min(v[1] for v in t)
                if y>height+.02 and min(v[0] for v in t)<rectangle[2] and max(v[0] for v in t)>rectangle[0] and min(v[2] for v in t)<rectangle[3] and max(v[2] for v in t)>rectangle[1]:
                    above.append(y-height)
        result.append(dict(surface_id=surface['id'],rectangle_xz=rectangle,height_m=height,overhead_clearance_m=min(above) if above else None,qualification='geometry_candidate'))
    return result
