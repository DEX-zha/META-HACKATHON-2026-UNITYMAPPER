"""Progressive zone assembly: retain previous furniture, verify each new zone."""
from copy import deepcopy
from .house_convergence import native_failures


def repairable_native(proof):
    """Only layout faults may enter recovery; isolation/identity faults stay fatal."""
    failures=native_failures(proof)
    return bool(failures) and all(kind in {'native','instance'} for kind,_ in failures) and all(
        i.get('connected') and i.get('native_scale') for i in proof.get('instances',[])
    ) and all(d.get('kind') in {'support','passage'} for d in proof.get('defects',[]))


def native_observations(proof, receipt, room):
    """Preserve measured faults for replanning without inventing a movement delta."""
    instances={i['id']:i for i in proof.get('instances',[])}
    defects=list(proof.get('defects',[]))
    reported={d.get('instance_id') for d in defects if d.get('kind')=='support'}
    defects.extend(dict(kind='support',instance_id=i['id'],message='Native support check failed')
                   for i in instances.values() if not i.get('support_passed') and i['id'] not in reported)
    result=[]
    for d in defects:
        if d.get('kind') not in {'support','passage'}:continue
        scope=d.get('room_id') or d.get('target',{}).get('room_id') or instances.get(d.get('instance_id'),{}).get('room_id')
        if scope and scope!=room:continue
        result.append(dict(room_id=scope or room,instance_id=d.get('instance_id',''),kind=d['kind'],
            severity='blocking',message='Native measurement: '+d.get('message',d['kind']),
            suggested_action='none',translation_m=[0,0,0],yaw_delta=0,
            evidence_ids=[receipt['details_artifact_hash']] if receipt.get('details_artifact_hash') else []))
    return result


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
        native_regression=native_failures(candidate_proof)-baseline
        if native_regression and not repairable_native(candidate_proof):
            record(room,zone,'rejected_native',candidate_proof);continue
        observations=inspect(candidate,candidate_proof,room,zone)
        observations+=native_observations(candidate_proof,candidate_receipt,room)
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


def inspection_scope(planned, candidate, room, zone):
    """Future planned furniture is not a missing item in an intermediate zone."""
    current={i['id'] for i in candidate['instances'] if i['room_id']==room}
    return dict(phase='progressive_zone', room_id=room, zone_id=zone,
                expected_instance_ids=sorted(current),
                deferred_instance_ids=sorted(i['id'] for i in planned['instances']
                                             if i['room_id']==room and i['id'] not in current))


def scoped_observations(observations, scope):
    if not scope:return observations
    deferred=set(scope['deferred_instance_ids'])
    return [o for o in observations if not (o.get('kind')=='missing' and o.get('instance_id') in deferred)]


ZONE_REVIEW_POLICY = ('Read inspection_scope before judging completeness. During progressive_zone, '
    'inspect placement, supports, access and orientation of the expected current instances. '
    'deferred_instance_ids are planned furniture for later assembly, not missing defects in this stage. '
    'Do not demand whole-room furnishing or decorations before those zones are built. '
    'Still report real defects of current objects, native failures and unsafe architecture. '
    'When inspection_scope is null this is a whole-room review: report ALL unmet requirements, '
    'including previously deferred furniture that is still absent. ')
