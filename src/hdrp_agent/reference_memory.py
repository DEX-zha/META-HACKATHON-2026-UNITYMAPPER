"""Reference-scoped evidence and bounded autonomous correction scheduling."""
from copy import deepcopy
from .domain import fingerprint


def evidence_key(frames,catalogue_hash):
    return fingerprint(dict(catalogue=catalogue_hash,frames=[{k:f.get(k) for k in ('key','artifact_hash','calibration')} for f in frames]))


def experiment_identity(plan,evidence,policy):
    return fingerprint(dict(evidence=evidence,policy=policy,plan={k:v for k,v in plan.items() if k!='notes'}))


def new_memory(key,analysis,inherited=None,priority_view='work-top-front',policy_hash=None,solver_version=None):
    same=isinstance(inherited,dict) and inherited.get('evidence_key')==key and inherited.get('priority_view')==priority_view and inherited.get('policy_hash')==policy_hash and inherited.get('solver_version')==solver_version
    return dict(schema_version=1,evidence_key=key,priority_view=priority_view,policy_hash=policy_hash,solver_version=solver_version,
                history=deepcopy(inherited.get('history',[])[-12:]) if same else [],
                objects={o['key']:dict(label=o['label'],asset_id=o['asset_id'],support_key=o['support_key'],status='unverified',observations=[],last_metrics=None) for o in analysis['objects']},
                exact_reconstruction_verified=False)


def phase_for(ordinal):
    return 'baseline' if ordinal==0 else 'appearance' if ordinal in {3,5} else 'placement'


def appearance_step(memory):
    count=sum(row.get('phase')=='appearance' for row in (memory or {}).get('history',[]))
    return ['light_geometry','photometry','atmosphere'][count%3]


def constrain_proposal(proposed,incumbent,phase,appearance_experiment=None):
    """Apply only the advertised experiment; preserve surrounding supports.

    Asset identity is validated before this function. Both raw model response
    and the scoped plan remain in the attempt receipt for accountability.
    """
    if incumbent is None or phase=='baseline':return deepcopy(proposed)
    plan=deepcopy(incumbent);items={o['key']:o for o in proposed['objects']}
    if phase in {'placement','anchoring','arranging','scaling'}:
        for item in plan['objects']:
            if item['key'] in items:
                for field in ['position_m','rotation_deg','scale']:item[field]=deepcopy(items[item['key']][field])
    elif phase=='appearance' and appearance_experiment:
        if appearance_experiment=='atmosphere':
            for field in ['sky_color_rgb','fog_mean_free_path_m']:plan[field]=deepcopy(proposed[field])
        else:
            fields=['position_m','rotation_deg','spot_angle_deg'] if appearance_experiment=='light_geometry' else ['intensity','color_rgb']
            if len(plan['lights'])==len(proposed['lights']):
                for old,new in zip(plan['lights'],proposed['lights']):
                    if old['type']==new['type']:
                        for field in fields:old[field]=deepcopy(new[field])
            if appearance_experiment=='photometry':plan['exposure_ev']=proposed['exposure_ev']
    else:
        for field in ['lights','exposure_ev','sky_color_rgb','fog_mean_free_path_m']:plan[field]=deepcopy(proposed[field])
    plan['notes']=deepcopy(proposed['notes'])
    return plan


def update_memory(memory,attempt,incumbent,accepted,run_id):
    metrics=attempt['metrics'];prior=incumbent['metrics'] if incumbent else None
    before={o['key']:o for o in incumbent['applied_plan']['objects']} if incumbent else {}
    changes=[]
    for item in attempt['applied_plan']['objects']:
        old=before.get(item['key'])
        fields={k:dict(before=old.get(k) if old else None,after=item[k]) for k in ['position_m','rotation_deg','scale'] if old is None or item[k]!=old[k]}
        if fields:changes.append(dict(object_key=item['key'],fields=fields))
    evidence=dict(run_id=run_id,ordinal=attempt['ordinal'],phase=attempt.get('phase','baseline'),accepted=accepted,
                  score=metrics['score'],priority_score=metrics.get('priority_score'),previous_score=prior['score'] if prior else None,
                  regressions=attempt.get('regressions',[]),changes=changes,
                  notes=attempt['applied_plan']['notes'],reason='retained_by_measured_comparison' if accepted else 'rejected_keep_previous_best')
    evidence['appearance_values']=deepcopy({k:attempt['applied_plan'].get(k) for k in ['lights','exposure_ev','sky_color_rgb','fog_mean_free_path_m','estimated_views']})
    if metrics.get('composition'):
        evidence['composition']=deepcopy(metrics['composition'])
    if metrics.get('geometry'):
        evidence.update(geometry_score=metrics['geometry']['score'],previous_geometry_score=prior.get('geometry',{}).get('score') if prior else None,applied_plan_hash=metrics['geometry']['applied_plan_hash'],version=metrics['geometry']['version'],coverage_complete=metrics['geometry']['coverage_complete'],policy_hash=memory.get('policy_hash'),solver_version=memory.get('solver_version'))
    if attempt.get('appearance_experiment'):evidence['appearance_experiment']=attempt['appearance_experiment']
    memory['history']=(memory['history']+[evidence])[-18:]
    for key,state in memory['objects'].items():
        current=metrics.get('per_object',{}).get(key)
        state['observations']=(state['observations']+[dict(run_id=run_id,ordinal=attempt['ordinal'],accepted=accepted,metrics=current)])[-6:]
        if accepted:state['last_metrics']=current
        state['status']='measured_residual_remains' if state['last_metrics'] else 'unmeasured'
    memory['exact_reconstruction_verified']=False


def regressions(candidate,incumbent):
    if incumbent is None:return []
    now=candidate['metrics'];old=incumbent['metrics'];issues=[]
    if old.get('contacts',{}).get('passed') and not now.get('contacts',{}).get('passed'):issues.append(dict(kind='support_contacts'))
    # Averages may never conceal a large regression in a previously measured
    # object or viewpoint. These are rejection bounds, not fidelity tolerances.
    for key,view in now['per_view'].items():
        before=old['per_view'].get(key)
        if before and view['score']>before['score']+.025:issues.append(dict(kind='view',view_key=key,delta=view['score']-before['score']))
    for key,item in now.get('per_object',{}).items():
        before=old.get('per_object',{}).get(key)
        if before and item.get('priority_rgb_mae') is not None and before.get('priority_rgb_mae') is not None and item['priority_rgb_mae']>before['priority_rgb_mae']+.06:
            issues.append(dict(kind='object',object_key=key,delta=item['priority_rgb_mae']-before['priority_rgb_mae']))
    return issues


def prompt_metrics(metrics):
    if not metrics:return None
    def contact(row):
        return {k:row.get(k) for k in ['support_key','status','reason','previous_gap_m','required_shift_y_m']} if row else None
    result={k:metrics.get(k) for k in ['score','priority_score','priority_view','global_score']}
    result['per_view']={key:{k:row.get(k) for k in ['score','rgb_mae','edge_mae']} for key,row in metrics.get('per_view',{}).items() if not key.startswith('control-')}
    result['per_object']={}
    for key,row in metrics.get('per_object',{}).items():
        fit=row.get('pose_fit_before_contact') or {}
        result['per_object'][key]=dict(priority_rgb_mae=row.get('priority_rgb_mae'),mask_view_count=len(row.get('mask_views',[])),contact=contact(row.get('support_contact')),pose_fit={k:fit[k] for k in ['accepted','initial_mean_iou','best_mean_iou','orientation_ambiguous'] if k in fit})
    geometry=metrics.get('geometry')
    if geometry:result['geometry']=dict(score=geometry['score'],coverage_complete=geometry['coverage_complete'],per_object={key:{k:row.get(k) for k in ['mean_iou','contour_error_px','view_count','covered','missing_reasons']} for key,row in geometry['per_object'].items()})
    # These are correction evidence, not just report decoration. Omitting them
    # left Muse unaware of clipped lighting and measured inward/outward defects.
    for key in ('architecture','plan_photometry'):
        if key in metrics:result[key]=deepcopy(metrics[key])
    result['contacts_passed']=metrics.get('contacts',{}).get('passed')
    return result


def prompt_memory(memory):
    if not memory:return None
    history=[]
    for entry in memory.get('history',[])[-6:]:
        history.append(dict(run_id=entry['run_id'],ordinal=entry['ordinal'],phase=entry['phase'],accepted=entry['accepted'],score=entry['score'],priority_score=entry.get('priority_score'),regressions=[{k:v for k,v in row.items() if k in {'kind','object_key','view_key','delta'}} for row in entry.get('regressions',[]) if 'control' not in row.get('kind','') and not row.get('view_key','').startswith('control-')],appearance_experiment=entry.get('appearance_experiment'),appearance_values=entry.get('appearance_values'),
                            changes=[dict(object_key=change['object_key'],proposed={field:value['after'] for field,value in change['fields'].items()}) for change in entry.get('changes',[])],notes=[note[:350] for note in entry.get('notes',[])[:4]]))
        if 'geometry_score' in entry:history[-1].update({k:entry.get(k) for k in ['geometry_score','previous_geometry_score','coverage_complete','version','applied_plan_hash']})
    return dict(evidence_key=memory['evidence_key'],priority_view=memory['priority_view'],history=history,total_archived_experiments=len(memory.get('history',[])),exact_reconstruction_verified=False,
                objects={key:dict(label=row['label'],asset_id=row['asset_id'],support_key=row['support_key'],status=row['status'],last_measurements=prompt_metrics(dict(per_object={key:row['last_metrics']}))['per_object'][key] if row.get('last_metrics') else None) for key,row in memory['objects'].items()})
