"""Rectangular AtmosphericHouse perimeter constraints, qualified with gp.unity.

Uses candidate floor dimensions and prefab-local geometry, not example room poses.
WallOut modules run along local -X; their exterior faces point towards local +Z.
"""
from copy import deepcopy
import numpy as np
from .reference_geometry import rotation


def fit_building_perimeter(plan, catalogue):
    assets = {a['asset_id']: a for a in catalogue}
    floors = [o for o in plan['objects'] if assets.get(o.get('asset_id'), {}).get('name', '').startswith('Floor_')]
    walls = [o for o in plan['objects'] if assets.get(o.get('asset_id'), {}).get('name', '').startswith('WallOut_')]
    if not floors or len(walls) < 4:
        return plan, []
    corners = []
    for obj in floors:
        if abs(obj['rotation_deg'][0]) > .01 or abs(obj['rotation_deg'][2]) > .01 or abs(obj['rotation_deg'][1]/90-round(obj['rotation_deg'][1]/90)) > .001:
            return plan, []
        asset = assets[obj['asset_id']]
        for x in (-.5, .5):
            for z in (-.5, .5):
                local = np.asarray(asset['bounds_center_m']) + np.asarray(asset['bounds_size_m'])*[x, 0, z]
                corners.append(np.asarray(obj['position_m'])+rotation(obj['rotation_deg'])@(local*obj['scale']))
    points = np.asarray(corners)
    lo, hi = points.min(axis=0), points.max(axis=0)
    if min(hi[0]-lo[0], hi[2]-lo[2]) < .1:
        return plan, []
    # Do not fill an L-shaped floor or disconnected tiles with a guessed room.
    area = sum(assets[o['asset_id']]['bounds_size_m'][0]*o['scale'][0]*assets[o['asset_id']]['bounds_size_m'][2]*o['scale'][2] for o in floors)
    if abs(area-(hi[0]-lo[0])*(hi[2]-lo[2])) > .01*area:
        return plan, []
    sides = {'north': [], 'south': [], 'east': [], 'west': []}
    for obj in walls:
        asset = assets[obj['asset_id']]
        if not asset.get('path','').startswith('Assets/AtmosphericHouse/Prefabs/Building/'):
            return plan, []
        centre = np.asarray(obj['position_m'])+rotation(obj['rotation_deg'])@(np.asarray(asset['bounds_center_m'])*obj['scale'])
        distances = dict(north=abs(centre[2]-hi[2]), south=abs(centre[2]-lo[2]), east=abs(centre[0]-hi[0]), west=abs(centre[0]-lo[0]))
        ordered = sorted(distances,key=distances.get)
        if distances[ordered[1]]-distances[ordered[0]] < .03:
            return plan, [dict(method='building_perimeter', status='ambiguous_side', object_key=obj['key'])]
        sides[ordered[0]].append((obj,centre))
    if any(not group for group in sides.values()):
        return plan, [dict(method='building_perimeter',status='incomplete_side_coverage')]
    result = deepcopy(plan)
    targets = {o['key']:o for o in result['objects']}
    changes = []
    for side, group in sides.items():
        axis = 0 if side in ('north','south') else 2
        yaw = dict(north=0,south=180,east=90,west=270)[side]
        group.sort(key=lambda pair:pair[1][axis])
        lengths = [assets[o['asset_id']]['bounds_size_m'][0]*o['scale'][0] for o,_ in group]
        ratio = (hi[axis]-lo[axis])/sum(lengths)
        # A gross mismatch needs a different module selection, not huge distortion.
        if not .75 <= ratio <= 1.25:
            return plan, [dict(method='building_perimeter',status='incompatible_module_lengths',side=side,ratio=float(ratio))]
        edge = lo[axis]
        for (obj,_), length in zip(group,lengths):
            item = targets[obj['key']]
            item['rotation_deg'] = [0.,float(yaw),0.]
            item['scale'][0] *= float(ratio)
            offset = rotation(item['rotation_deg'])@(np.asarray(assets[item['asset_id']]['bounds_center_m'])*item['scale'])
            position = list(item['position_m'])
            position[axis] = float(edge+length*ratio/2-offset[axis])
            # Prefab root is the authored wall socket plane. Its thickness lies outside.
            normal = 2 if axis==0 else 0
            position[normal] = float(hi[normal] if side in ('north','east') else lo[normal])
            item['position_m'] = position
            edge += length*ratio
            changes.append(dict(object_key=item['key'],side=side,position_m=position,rotation_deg=item['rotation_deg']))
    return result, [dict(method='building_perimeter',status='fitted',source_transforms_used=False,assembly_convention='AtmosphericHouse WallOut local -X span, +Z exterior; gp example',walls=changes)]
