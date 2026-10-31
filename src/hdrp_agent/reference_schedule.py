"""Frozen reconstruction policy and evidence-driven, bounded decisions."""
from copy import deepcopy
import time
from .domain import AgentError,fingerprint,payload


def default_policy():
    value=dict(schema_version='1.0',solver_version='fidelity-5',max_candidates=6,max_seconds=2400,max_local_evaluations=2000,max_local_seconds=120,max_images=12,max_inspection_views=8,min_geometry_views=2,min_anchor_views=3,minimum_geometry_gain=.002,object_regression_bound=.035,view_regression_bound=.05,geometry_iou_gate=.97,geometry_contour_gate_px=2.,scale_change_bound=.15,scale_mode='locked',noise_baseline_hash=None)
    payload('FidelityPolicy',value);return value


class LocalLimit(Exception):pass

class SearchBudget:
    def __init__(self,policy,guard=None):self.started=time.monotonic();self.policy=policy;self.guard=guard;self.evaluations=0;self.reason=None;self.last_external_check=None
    def check(self):
        now=time.monotonic()
        # Raster calls this every 64 triangles. Reading the full run from SQLite
        # on every such check swamps numerical work; cancellation stays <=250 ms.
        if self.guard and (self.last_external_check is None or now-self.last_external_check>=.25):
            self.guard();self.last_external_check=now
        if now-self.started>=self.policy['max_local_seconds']:
            self.reason='local_time_limit';raise LocalLimit(self.reason)
    def charge(self):
        self.check()
        if self.evaluations>=self.policy['max_local_evaluations']:
            self.reason='local_evaluation_limit';raise LocalLimit(self.reason)
        self.evaluations+=1


def geometry_ready(geometry,policy):
    return bool(geometry and geometry['coverage_complete'] and all(o['mean_iou']>=policy['geometry_iou_gate'] and o['contour_error_px']<=policy['geometry_contour_gate_px'] for o in geometry['per_object'].values()))


def proposal_base(attempts,best,phase):
    """A rejected global hypothesis may seed a joint corrective experiment.

    It never becomes the retained result without passing all normal gates.
    Only the next arrangement trial can use it; no native command is replayed.
    """
    if phase=='arranging' and attempts and best:
        latest=attempts[-1]
        if latest['phase']=='anchoring' and latest.get('state')=='rendered' and latest['metrics']['contacts']['passed']:
            now=latest['metrics'].get('geometry',{}).get('score');old=best['metrics'].get('geometry',{}).get('score')
            if now is not None and old is not None and now<old:return latest
    return best


def next_action(attempts,best,policy):
    if len(attempts)>=policy['max_candidates']:return dict(action='stop',reason='candidate_limit')
    if best is None:return dict(action='baseline',reason='establish_current_evidence')
    g=best['metrics'].get('geometry')
    if not g or g['score'] is None:return dict(action='stop',reason='insufficient_observations')
    phases=[a['phase'] for a in attempts]
    if 'anchoring' not in phases:return dict(action='anchoring',reason='global_frame_not_examined')
    # Use the numerical and visual paths as independent experiments.
    if 'arranging' not in phases:return dict(action='arranging',reason='relative_layout_not_examined')
    if policy['scale_mode']=='evidenced' and 'scaling' not in phases:return dict(action='scaling',reason='separate_bounded_multiview_scale_experiment')
    if 'placement' not in phases:return dict(action='placement',reason='independent_visual_hypothesis')
    if geometry_ready(g,policy):
        if not policy.get('noise_baseline_hash') or not best['metrics'].get('appearance',{}).get('protocol_qualified'):
            return dict(action='stop',reason='appearance_capture_unqualified')
        if attempts[-1]['phase']=='appearance' and not attempts[-1].get('retained'):
            return dict(action='stop',reason='no_admissible_progress')
        return dict(action='appearance',reason='visual_geometry_gate_passed')
    recent=[a for a in attempts if a['phase']!='baseline'][-2:]
    if len(recent)==2 and not any(a.get('retained') for a in recent):return dict(action='stop',reason='no_admissible_progress' if g['coverage_complete'] else 'insufficient_observations')
    return dict(action='anchoring' if attempts[-1]['phase']!='anchoring' else 'placement',reason='remaining_geometric_residual')


def assess(candidate,best,policy):
    if best is None:return True,[]
    now=candidate['metrics'];old=best['metrics'];issues=[]
    if old['contacts']['passed'] and not now['contacts']['passed']:issues.append(dict(kind='support_contacts'))
    a,b=now.get('geometry'),old.get('geometry')
    if not a or not b or a['score'] is None or b['score'] is None:return False,[dict(kind='missing_geometry')]
    for key,before in b['per_object'].items():
        after=a['per_object'].get(key,{})
        if before['mean_iou'] is not None:
            if after.get('mean_iou') is None:issues.append(dict(kind='lost_measurement',object_key=key));continue
            if after['view_count']<before['view_count']:issues.append(dict(kind='lost_coverage',object_key=key))
            if before['mean_iou']-after['mean_iou']>policy['object_regression_bound']:issues.append(dict(kind='geometry_object',object_key=key,delta=before['mean_iou']-after['mean_iou']))
            for view,previous in before['views'].items():
                current=after['views'].get(view)
                if current and previous['visible_iou'] is not None and current['visible_iou'] is not None and previous['visible_iou']-current['visible_iou']>policy['view_regression_bound']:issues.append(dict(kind='geometry_view',object_key=key,view_key=view))
    if candidate['phase']=='appearance':
        if candidate['applied_plan']['objects']!=best['applied_plan']['objects']:issues.append(dict(kind='appearance_changed_pose'))
        if not now.get('appearance') or not old.get('appearance'):issues.append(dict(kind='appearance_capture_unqualified'))
        else:
            from .reference_appearance import assess_capture_appearance
            _,appearance_issues=assess_capture_appearance(old['appearance'],now['appearance']);issues.extend(appearance_issues)
    elif a['score']>=b['score']-policy['minimum_geometry_gain']:issues.append(dict(kind='no_geometry_gain'))
    return not issues,issues
