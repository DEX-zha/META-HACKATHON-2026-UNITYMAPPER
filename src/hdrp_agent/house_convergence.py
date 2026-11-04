"""Iterate candidates while retaining the best native/visual result and evidence."""
from copy import deepcopy
from statistics import median
import re
import math
from difflib import SequenceMatcher
from .domain import fingerprint, AgentError
from .house_repairs import propose


def native_failures(proof):
    failures={('native',fingerprint(d)) for d in proof.get('defects',[])}
    for i in proof.get('instances',[]):
        if not all(i.get(k) for k in ('connected','native_scale','support_passed')):failures.add(('instance',i['id']))
    rooms={i.get('room_id','house') for i in proof.get('instances',[])}|{c.get('room_id','house') for c in proof.get('captures',[])}
    observed={c.get('room_id','house') for c in proof.get('captures',[]) if c.get('usable',True)}
    failures.update(('coverage',r) for r in rooms-observed)
    if not proof.get('source_scene_unchanged'):failures.add(('source','changed'))
    return failures


def same_defect(a,b):
    """Conservative correspondence; physical defects never migrate between objects."""
    if a['room_id']!=b['room_id']:return False
    same_target=a.get('instance_id')==b.get('instance_id')
    if same_target and a['kind']==b['kind']:return True
    if a['kind'] not in {'missing','composition'} or b['kind'] not in {'missing','composition'}:return False
    normalize=lambda o:re.sub(r'[^a-z0-9 ]',' ',o.get('message','').lower())
    left,right=normalize(a),normalize(b)
    if not left or not right:return False
    # Category/target drift may describe the same absence, but uncertain matches fail closed.
    similarity=SequenceMatcher(None,left,right).ratio()
    return similarity >= (.72 if same_target else .9)


def unmatched(old,new):
    return [o for o in new if not any(same_defect(previous,o) for previous in old)]


def counterfactual_candidates(before,after,old,new):
    """Only pre-existing furnishing targets can have pre-existing sparse content."""
    previous={i['id']:i for i in before['instances']};current={i['id']:i for i in after['instances']}
    return [o for o in unmatched(old,new) if o['kind'] in {'composition','missing'}
            and o.get('instance_id') in previous and o.get('instance_id') in current
            and all(previous[o['instance_id']].get(k)==current[o['instance_id']].get(k)
                    for k in ('prefab_guid','position','center','yaw','scale','support_id'))]


def signature(manifest):
    return fingerprint(dict(instances=manifest['instances'],exposure_ev=manifest.get('exposure_ev',6),calibrate_exposure=manifest.get('calibrate_exposure',False),lighting=manifest.get('lighting')))


def observed_controls(manifest,proof):
    """Use measured exposure for new trials without rewriting historical input."""
    if not manifest.get('calibrate_exposure'):return manifest
    calibration=proof.get('exposure_calibration') or {}
    ev=calibration.get('locked_ev100')
    if not calibration.get('fixed_readback_verified') or type(ev) not in (int,float) or not math.isfinite(ev) or not -4<=ev<=16:
        raise AgentError('EVIDENCE_MISSING','Calibrated exposure requires a verified native EV100 receipt')
    for capture in proof.get('captures',[]):
        state=capture.get('render_request_state') or {}
        if state.get('status')!='observed' or state.get('exposure_mode')!='Fixed' or not isinstance(state.get('exposure_ev'),(int,float)) or abs(state['exposure_ev']-ev)>.05:
            raise AgentError('EVIDENCE_MISSING','Capture exposure does not match the locked calibration')
    if not proof.get('captures'):raise AgentError('EVIDENCE_MISSING','Exposure calibration has no subsequent captures')
    candidate=deepcopy(manifest);candidate.update(exposure_ev=ev,calibrate_exposure=False)
    return candidate


def exposure_proposal(manifest,proof,attempted):
    levels=[c['mean_rgb'] for c in proof.get('captures',[]) if 'mean_rgb' in c]
    if not levels:return None
    level=median(levels);ev=manifest.get('exposure_ev',6)
    step=1 if level>.8 else -1 if level<.06 else 0
    if not step or not -4<=ev+step<=16:return None
    candidate=deepcopy(manifest);candidate['exposure_ev']=ev+step
    if signature(candidate) in attempted:return None
    return candidate,dict(kind='exposure',scope_id='house',reason='Measured median brightness outside usable range',before=ev,after=ev+step)


def exposure_error(proof):
    levels=[c['mean_rgb'] for c in proof.get('captures',[]) if 'mean_rgb' in c]
    if not levels:return 1
    v=median(levels);return max(0,v-.8,.06-v)


def acceptable(before,after,old_observations,new_observations,patch):
    if native_failures(after)-native_failures(before):return False,'Native regression'
    if {i['id'] for i in before.get('instances',[])}-{i['id'] for i in after.get('instances',[])}:return False,'Existing equipment disappeared'
    if patch['kind']=='exposure':
        improved=exposure_error(after)<exposure_error(before)
        return improved,'Exposure improved' if improved else 'Exposure did not improve'
    if exposure_error(after)>exposure_error(before)+.01:return False,'Observation exposure regressed'
    if unmatched(old_observations,new_observations):return False,'New visual defects'
    old_blocking=[o for o in old_observations if o['severity']=='blocking']
    new_blocking=[o for o in new_observations if o['severity']=='blocking']
    if unmatched(old_blocking,new_blocking):return False,'Visual defect severity increased'
    if native_failures(before)-native_failures(after):return True,'Native defect resolved'
    if unmatched(new_observations,old_observations):return True,'Visual defect resolved'
    if len(after.get('instances',[]))>len(before.get('instances',[])):return True,'Additional supported equipment'
    return False,'No measured progress'


def converge(manifest,receipt,proof,observations,*,build,inspect,enrich,record,guard,reconsider=None):
    """No iteration quota: stop on no safe proposal, repeated state, budget or user stop.

    Each candidate is saved separately by Unity. Rejection keeps the accepted scene
    path and evidence, so a worse proposal never replaces the selected result.
    """
    attempted={signature(manifest)};attempted_poses={fingerprint(manifest['instances'])};round_index=0;rejections=0;reconsidered=set();planning_observations=observations
    while True:
        guard()
        baseline=observed_controls(manifest,proof)
        attempted.add(signature(baseline))
        proposal=exposure_proposal(baseline,proof,attempted)
        if proposal is None:
            movement=propose(baseline,planning_observations,attempted_poses)
            if movement and signature(movement[0]) not in attempted:proposal=movement
        if proposal is None:proposal=enrich(baseline,proof,observations,attempted)
        if proposal is None:
            reason_key=fingerprint(dict(manifest=signature(manifest),observations=observations,rejections=rejections))
            if reconsider is not None and (observations or rejections) and reason_key not in reconsidered:
                reconsidered.add(reason_key)
                revised=reconsider(manifest,proof)
                # A planning reply cannot erase defects without a new build and review.
                if revised and fingerprint(revised)!=fingerprint(planning_observations):
                    planning_observations=revised;continue
            return manifest,receipt,proof,observations,'NO_SAFE_PROGRESS'
        candidate,patch=proposal;key=signature(candidate)
        if key in attempted:return manifest,receipt,proof,observations,'REPEATED_STATE'
        attempted.add(key);attempted_poses.add(fingerprint(candidate["instances"]));round_index+=1
        record(round_index,'proposed',patch,receipt,proof)
        candidate_receipt,candidate_proof=build(candidate)
        # Avoid paying for review of a native regression.
        if native_failures(candidate_proof)-native_failures(proof):
            record(round_index,'rejected',dict(patch,rejection='Native regression',native_defects=candidate_proof.get('defects',[])),candidate_receipt,candidate_proof);rejections+=1;continue
        candidate_observations=inspect(candidate,candidate_proof)
        eligible=counterfactual_candidates(manifest,candidate,observations,candidate_observations)
        if eligible:
            guard()
            baseline_review=inspect(manifest,proof)
            verified=[old for old in baseline_review if any(same_defect(old,new) and
                      old['severity']==new['severity'] for new in eligible)]
            if verified:
                # Preserve the defect in both scenes; do not label an old absence
                # as damage caused by a new, supported accessory elsewhere.
                observations=observations+unmatched(observations,verified)
                planning_observations=observations
                patch=dict(patch,existing_defects_verified=verified,baseline_scene_path=proof['scene_path'])
        passed,reason=acceptable(proof,candidate_proof,observations,candidate_observations,patch)
        if passed:
            manifest,receipt,proof,observations=candidate,candidate_receipt,candidate_proof,candidate_observations
            planning_observations=observations
            record(round_index,'accepted',dict(patch,acceptance=reason),receipt,proof)
        else:
            record(round_index,'rejected',dict(patch,rejection=reason,observed_defects=[{k:o.get(k) for k in ('room_id','instance_id','kind','severity','message')} for o in candidate_observations]),candidate_receipt,candidate_proof);rejections+=1
