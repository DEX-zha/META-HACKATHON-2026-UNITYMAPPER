"""Fixed scale priors from recorded model evidence, never evaluator transforms."""
from copy import deepcopy
import numpy as np
from .domain import fingerprint


def restore_origin_scale(plan,origin,bound=.15):
    result=deepcopy(plan);by_key={o['key']:o for o in origin['objects']};changes=[];unqualified=[]
    for item in result['objects']:
        original=by_key.get(item['key'])
        if not original or original.get('asset_id')!=item.get('asset_id') or original.get('primitive')!=item.get('primitive'):
            unqualified.append(dict(object_key=item['key'],reason='origin_identity_differs'));continue
        scale=np.asarray(original['scale'],dtype=float);current=np.asarray(item['scale'],dtype=float)
        if not np.isfinite(scale).all() or np.any(scale<=0) or np.any(np.abs(current/scale-1)>bound):
            unqualified.append(dict(object_key=item['key'],reason='scale_outside_origin_bound'));continue
        if item['scale']!=original['scale']:
            changes.append(dict(object_key=item['key'],before=item['scale'],after=original['scale']))
            item['scale']=deepcopy(original['scale'])
    return result,dict(method='restore_recorded_scale_origin_before_fixed_scale_search',origin_plan_hash=fingerprint(origin),changes=changes,unqualified=unqualified,source_transforms_used=False)


def fit_evidenced_scale(plan,evaluator,origin,policy,guard=None):
    """A separate bounded proposal, enabled only by the frozen scale policy."""
    from .reference_schedule import SearchBudget,LocalLimit
    if policy['scale_mode']!='evidenced':return deepcopy(plan),dict(method='multiview_scale_experiment',accepted=False,reason='scale_locked',source_transforms_used=False)
    if not origin:return deepcopy(plan),dict(method='multiview_scale_experiment',accepted=False,reason='missing_scale_origin',source_transforms_used=False)
    output=deepcopy(plan);original={o['key']:o for o in origin['objects']};budget=SearchBudget(policy,guard);previous_guard=evaluator.guard;evaluator.guard=budget.check;changes=[]
    try:
        for item in output['objects']:
            source=original.get(item['key'])
            if not item.get('asset_id') or not source or source.get('asset_id')!=item['asset_id'] or not evaluator.independent_views(item['key'],3):continue
            budget.charge();before=evaluator.measure(output,'local-proposal',keys=[item['key']]);row=before['per_object'].get(item['key'])
            if not row or row['view_count']<3 or before['render_issues']:continue
            views=row['views']
            if any(v['centroid_error_px'] is None or v['centroid_error_px']>2 for v in views.values()):continue
            best=None
            for factor in [.85,.9,.94,.97,1.,1.03,1.06,1.1,1.15]:
                scale=(np.asarray(source['scale'])*factor).tolist()
                if np.any(np.abs(np.asarray(scale)/source['scale']-1)>policy['scale_change_bound']+1e-12):continue
                candidate=deepcopy(output);target=next(o for o in candidate['objects'] if o['key']==item['key']);target['scale']=scale
                budget.charge();measured=evaluator.measure(candidate,'local-proposal',keys=[item['key']]);after=measured['per_object'][item['key']]
                if measured['render_issues'] or after['view_count']!=row['view_count']:continue
                consistent=all(k in after['views'] and v['visible_iou'] is not None and after['views'][k]['visible_iou'] is not None and after['views'][k]['visible_iou']>=v['visible_iou']+.01 and after['views'][k]['contour_error_px']<=v['contour_error_px']-1 and after['views'][k]['centroid_error_px'] is not None and after['views'][k]['centroid_error_px']<=v['centroid_error_px']+1 for k,v in views.items())
                if consistent and (best is None or measured['score']<best[0]):best=(measured['score'],scale)
            if best:
                changes.append(dict(object_key=item['key'],before=item['scale'],after=best[1],origin_scale=source['scale'],reliable_views=row['view_count']));item['scale']=best[1]
    except LocalLimit:pass
    finally:evaluator.guard=previous_guard
    return output,dict(method='multiview_scale_experiment',accepted=bool(changes),changes=changes,evaluations=budget.evaluations,stop_reason=budget.reason,origin_plan_hash=fingerprint(origin),source_transforms_used=False,post_contact_verification_required=True)
