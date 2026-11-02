"""Progressive zone assembly: retain previous furniture, verify each new zone."""
from copy import deepcopy
from .house_convergence import native_failures


def batches(instances):
    by_id={i['id']:i for i in instances};zones={}
    for item in instances:
        parent=item;visited=set()
        while parent.get('support_id') in by_id:
            if parent['id'] in visited:raise ValueError('Cyclic instance support')
            visited.add(parent['id']);parent=by_id[parent['support_id']]
        key=(parent['room_id'],parent['group_id'])
        zones.setdefault(key,[]).append(item)
    return list(zones.items())


def assemble(manifest, *, build, inspect, repair, record, guard):
    accepted=deepcopy(manifest);accepted['instances']=[]
    receipt=proof=None
    for (room,zone),items in batches(manifest['instances']):
        guard();candidate=deepcopy(accepted);candidate['instances'].extend(deepcopy(items))
        # Preserve the planned routes for later zones as well as accepted repairs.
        for entry in manifest.get('access',[]):
            current=next((a for a in candidate.get('access',[]) if a['room_id']==entry['room_id']),None)
            if current is None:candidate.setdefault('access',[]).append(deepcopy(entry))
            else:
                for point in entry['points']:
                    if point not in current['points']:current['points'].append(point)
        record(room,zone,'building',None)
        candidate_receipt,candidate_proof=build(candidate)
        baseline=native_failures(proof) if proof else set()
        if native_failures(candidate_proof)-baseline:
            record(room,zone,'rejected_native',candidate_proof);continue
        observations=inspect(candidate,candidate_proof,room,zone)
        hard=lambda obs:[o for o in obs if o.get('kind') in {'collision','support','passage','orientation'}]
        if hard(observations):
            candidate,candidate_receipt,candidate_proof,observations=repair(candidate,candidate_receipt,candidate_proof,observations,room,zone)
        if hard(observations) or native_failures(candidate_proof)-baseline:
            record(room,zone,'unresolved',candidate_proof);continue
        accepted,receipt,proof=candidate,candidate_receipt,candidate_proof
        record(room,zone,'accepted',proof)
    if proof is None:
        # Keep an inspected shell, never pretend rejected furniture exists.
        accepted['access']=[];receipt,proof=build(accepted)
    return accepted,receipt,proof
