"""Bounded yaw/XZ fitting of candidate prefab silhouettes to observed SAM masks."""
from copy import deepcopy
import io
import math
import numpy as np
from PIL import Image,ImageDraw
from .reference_geometry import rotation


def fit_mask_poses(plan,frames,segments,geometry,artifacts,*,guard=None,fine=False):
    output=deepcopy(plan);reports=[];views={f['key']:f for f in frames};assets={a['asset_id']:a for a in geometry}
    for item in output['objects']:
        if guard:guard()
        asset=assets.get(item['asset_id'])
        if asset is None:continue
        observations=[]
        for segment in segments:
            selection=segment.get('selection');frame=views.get(segment['view_key'])
            if segment['object_key']!=item['key'] or not selection or not frame or frame['calibration'] is None:continue
            if selection.get('confidence',0)<.7:continue
            box=selection['bbox_xyxy'];w,h=frame['model_size'];x0,y0,x1,y1=[round(v*d) for v,d in zip(box,[w,h,w,h])]
            if x1-x0<8 or y1-y0<8:continue
            with Image.open(io.BytesIO(artifacts.read(selection['mask_hash']))) as source:mask=source.convert('L').resize((x1-x0,y1-y0),Image.Resampling.NEAREST)
            margin=max(20,round(max(x1-x0,y1-y0)*.6));rect=[max(0,x0-margin),max(0,y0-margin),min(w,x1+margin),min(h,y1+margin)]
            target=Image.new('L',(rect[2]-rect[0],rect[3]-rect[1]));target.paste(mask,(x0-rect[0],y0-rect[1]));size=list(target.size);factor=min(1,256/max(size));size=[max(1,round(n*factor)) for n in size];target=target.resize(size,Image.Resampling.NEAREST)
            observations.append(dict(frame=frame,rect=rect,size=size,target=np.asarray(target)>127))
        # A single silhouette cannot disambiguate depth or orientation.
        if len(observations)<2:continue
        meshes=[(np.asarray(m['vertices'],dtype=float),np.asarray(m['triangles'],dtype=int).reshape(-1,3)) for m in asset['meshes']]
        if not meshes:continue
        original=deepcopy(item);evaluations=0
        def score(position,yaw,scale=None):
            nonlocal evaluations
            evaluations+=1
            if guard and evaluations%24==0:guard()
            angles=[*item['rotation_deg']];angles[1]=yaw;matrix=rotation(angles);worlds=[(vertices*(item['scale'] if scale is None else scale))@matrix.T+position for vertices,triangles in meshes];scores=[]
            for obs in observations:
                frame=obs['frame'];view=frame['calibration'];rect=obs['rect'];size=obs['size'];w,h=frame['model_size'];t=math.tan(math.radians(view['fov_deg'])/2)
                image=Image.new('1',size);draw=ImageDraw.Draw(image)
                for world,(_,triangles) in zip(worlds,meshes):
                    p=(world-view['position_m'])@rotation(view['rotation_deg'])
                    z=np.maximum(p[:,2],.0001);uv=np.column_stack([(.5+p[:,0]/z/(2*t*w/h))*w,(.5-p[:,1]/z/(2*t))*h]);uv=(uv-np.array(rect[:2]))*np.array(size)/np.array([rect[2]-rect[0],rect[3]-rect[1]])
                    for tri in triangles:
                        if np.any(p[tri,2]<=.05):continue
                        points=uv[tri]
                        if points[:,0].max()<0 or points[:,1].max()<0 or points[:,0].min()>=size[0] or points[:,1].min()>=size[1]:continue
                        draw.polygon([tuple(v) for v in points],fill=1)
                predicted=np.asarray(image,dtype=bool);target=obs['target'];union=np.logical_or(predicted,target).sum();scores.append(float(np.logical_and(predicted,target).sum()/max(1,union)))
            return float(np.mean(scores)),scores
        start=np.array(item['position_m'],dtype=float);yaw=float(item['rotation_deg'][1]);initial,initial_views=score(start,yaw);best=(initial,start,yaw,initial_views);hypotheses=[]
        for angle in sorted(set([yaw,0.,90.,180.,270.])):
            position=start.copy();value,view_scores=score(position,angle)
            # Coarse yaw/XZ search is bounded. Fine scale/yaw refinement follows
            # only in the autonomous mode; Y contacts remain native.
            for step in [.12,.05,.02]:
                for repeat in range(2):
                    improved=False
                    for axis in [0,2]:
                        for direction in [-1,1]:
                            trial=position.copy();trial[axis]+=direction*step
                            if np.any(np.abs(trial-start)>.3):continue
                            trial_value,trial_views=score(trial,angle)
                            if trial_value>value+.0001:position,value,view_scores=trial,trial_value,trial_views;improved=True
                    if not improved:break
            hypotheses.append((value,position,angle,view_scores))
            if value>best[0]:best=(value,position,angle,view_scores)
        peak=best[0]
        comparable=[hypothesis for hypothesis in hypotheses if hypothesis[0]>=peak-.03]
        # Silhouettes often cannot distinguish cabinet front/back. Preserve the
        # visually selected facing among statistically similar yaw hypotheses.
        best=min(comparable,key=lambda h:(abs((h[2]-yaw+180)%360-180),-h[0]))
        fitted_scale=np.array(item['scale'],dtype=float)
        if fine:
            value,position,angle,view_scores=best
            # Local refinements retain the selected facing while recovering
            # millimetre-scale translation and small rotation/scale differences.
            for distance,degrees,factor in [(.01,10,.03),(.003,3,.01),(.001,1,.003)]:
                for repeat in range(2):
                    improved=False
                    proposals=[]
                    for axis in [0,2]:
                        for direction in [-1,1]:
                            trial=position.copy();trial[axis]+=direction*distance
                            if np.all(np.abs(trial-start)<=.3):proposals.append((trial,angle,fitted_scale))
                    for direction in [-1,1]:
                        proposals.append((position,(angle+direction*degrees)%360,fitted_scale))
                        trial=fitted_scale*(1+direction*factor)
                        if np.all(np.abs(trial/np.array(original['scale'])-1)<=.15):proposals.append((position,angle,trial))
                    for trial_position,trial_angle,trial_scale in proposals:
                        trial_value,trial_views=score(trial_position,trial_angle,trial_scale)
                        if trial_value>value+.0001 and all(a>=b-.005 for a,b in zip(trial_views,initial_views)):
                            value,position,angle,fitted_scale,view_scores=trial_value,trial_position.copy(),trial_angle,trial_scale.copy(),trial_views;improved=True
                    if not improved:break
            best=value,position,angle,view_scores
        accepted=best[0]>initial+(.003 if fine else .03) and all(after>=before-(.005 if fine else .01) for before,after in zip(initial_views,best[3]))
        if accepted:
            item['position_m']=[round(float(v),5) for v in best[1]];item['rotation_deg'][1]=best[2];item['scale']=[round(float(v),5) for v in fitted_scale]
        reports.append(dict(object_key=item['key'],method='candidate_mesh_silhouette_to_multiview_sam',accepted=accepted,initial_mean_iou=initial,best_mean_iou=best[0],initial_view_ious=initial_views,best_view_ious=best[3],evaluations=evaluations,view_keys=[o['frame']['key'] for o in observations],previous_scale=original['scale'],scale=item['scale'],yaw_hypotheses=[dict(yaw_deg=h[2],mean_iou=h[0]) for h in hypotheses],orientation_ambiguous=len(comparable)>1,previous_position_m=original['position_m'],position_m=item['position_m'],previous_yaw_deg=yaw,yaw_deg=item['rotation_deg'][1],limitation='Two-dimensional silhouette evidence only; occlusion, mask errors and symmetric orientations remain ambiguous. Native contacts must be checked after fitting.'))
    return output,reports


def fit_global_anchor(plan,evaluator,policy,*,guard=None):
    """Translate the assembly, not its cameras, using candidate mesh masks only.

    Search never reads the evaluation report or a source transform. Unit-scale
    priors, if applicable, are established before this experiment.
    """
    from .reference_schedule import SearchBudget,LocalLimit
    from .reference_support_graph import SupportGraph
    budget=SearchBudget(policy,guard);previous_guard=evaluator.guard;evaluator.guard=budget.check
    root_candidates=[]
    for item in plan['objects']:
        meshes=evaluator.raster.meshes.get(item.get('asset_id'))
        count=sum(item['key'] in o['objects'] for o in evaluator.observations.values())
        if not meshes or count<policy['min_anchor_views'] or not evaluator.independent_views(item['key'],policy['min_anchor_views']):continue
        points=np.concatenate([m[0] for m in meshes])*item['scale'];extent=np.ptp(points,axis=0)
        # Broad thin platforms establish a support frame without source identity.
        if extent[1]<.3 and min(extent[0],extent[2])>1:root_candidates.append((float(extent[0]*extent[2]),item['key']))
    if not root_candidates:
        evaluator.guard=previous_guard
        return deepcopy(plan),dict(method='global_xyz_mask_anchor',accepted=False,reason='no_observable_platform_in_three_views',evaluations=0)
    root=max(root_candidates)[1];keys=[root]
    graph=SupportGraph(plan,[dict(object_key=o['key'],support_key=root) for o in plan['objects'] if o['key']!=root])
    start=deepcopy(plan);best=deepcopy(plan);delta=np.zeros(3);initial=None;score=None;angles=np.zeros(3)
    def evaluate(candidate):
        budget.charge();m=evaluator.measure(candidate,'local-proposal',keys=keys)
        return m['score']
    try:
        initial=score=evaluate(best)
        if initial is None:return start,dict(method='global_xyz_mask_anchor',accepted=False,reason='missing_anchor_metric',evaluations=budget.evaluations)
        for step in [.12,.05,.02,.005,.001]:
            for repeat in range(2):
                improved=False
                for axis in [1,0,2]:
                    trials=[]
                    for direction in [-1,1]:
                        shift=delta.copy();shift[axis]+=direction*step
                        if np.max(np.abs(shift))>.4:continue
                        candidate=graph.transform_group(start,root,shift);value=evaluate(candidate)
                        if value is not None:trials.append((value,shift,candidate))
                    if trials:
                        value,shift,candidate=min(trials,key=lambda t:t[0])
                        if value<score-.0001:score,delta,best=value,shift,candidate;improved=True
                if not improved:break
        # Independent views make bounded tilt trials observable; a flat or
        # symmetric residual never establishes a unique orientation.
        for step in [5.,1.,.25]:
            for axis in [1,0,2]:
                trials=[]
                for direction in [-1,1]:
                    trial=angles.copy();trial[axis]+=direction*step
                    if np.max(np.abs(trial))>8:continue
                    candidate=graph.transform_group(start,root,delta,rotation_deg=trial);value=evaluate(candidate)
                    if value is not None:trials.append((value,trial,candidate))
                if trials:
                    value,trial,candidate=min(trials,key=lambda t:t[0])
                    if value<score-policy['minimum_geometry_gain']:score,angles,best=value,trial,candidate
    except LocalLimit:pass
    finally:evaluator.guard=previous_guard
    accepted=initial is not None and score is not None and score<initial-policy['minimum_geometry_gain']
    return (best if accepted else start),dict(method='global_xyz_mask_anchor',accepted=accepted,anchor_object=root,initial_score=initial,score=score,translation_m=delta.tolist() if accepted else [0,0,0],yaw_delta_deg=float(angles[1]) if accepted else 0.,rotation_delta_deg=angles.tolist() if accepted else [0,0,0],orientation_uniqueness_verified=False,evaluations=budget.evaluations,stop_reason=budget.reason,scale_changed=False,source_transforms_used=False,limitation='Platform silhouette anchor; calibrated views and segmentation can remain ambiguous. Native post-contact evaluation decides retention.')


def fit_relative_poses(plan,evaluator,supports,policy,*,guard=None):
    """Local XYZ/yaw trials on inferred support groups, with fixed asset scale."""
    from .reference_schedule import SearchBudget,LocalLimit
    from .reference_support_graph import SupportGraph
    budget=SearchBudget(policy,guard);previous_guard=evaluator.guard;evaluator.guard=budget.check;graph=SupportGraph(plan,supports)
    output=deepcopy(plan);reports=[]
    def objective(candidate,key):
        budget.charge();metrics=evaluator.measure(candidate,'local-proposal',keys=[key]);row=metrics['per_object'].get(key)
        if not row or row['mean_iou'] is None:return None
        distances=[]
        for view,measured in row['views'].items():
            if measured['contour_error_px'] is None:continue
            observation=evaluator.observations[view]
            diagonal=np.linalg.norm(observation['size'])*observation['scale']
            distances.append(min(1.,measured['contour_error_px']/diagonal))
        # IoU alone is flat when silhouettes do not overlap. Contour distance
        # supplies direction until overlap exists, without looking at RGB.
        return .7*(1-row['mean_iou'])+.3*float(np.mean(distances)) if distances else None
    try:
        budget.charge();all_metrics=evaluator.measure(output,'local-proposal')
        ranked=sorted((k for k,r in all_metrics['per_object'].items() if graph.parents[k] is not None and r['covered']),key=lambda k:all_metrics['per_object'][k]['mean_iou'])
        for key in ranked:
            before=deepcopy(output);initial=objective(before,key);score=initial;translation=np.zeros(3);yaw=0.
            if initial is None:continue
            for step,angle in [(.12,10),(.04,5),(.01,2),(.003,.5)]:
                for axis in [0,2]:
                    for direction in [-1,1]:
                        trial=translation.copy();trial[axis]+=direction*step
                        if np.max(np.abs(trial))>.2:continue
                        candidate=graph.transform_group(before,key,trial,yaw);value=objective(candidate,key)
                        if value is not None and value<score-.0001:score,translation,output=value,trial,candidate
                for direction in [-1,1]:
                    trial_yaw=yaw+direction*angle
                    candidate=graph.transform_group(before,key,translation,trial_yaw);value=objective(candidate,key)
                    if value is not None and value<score-.0001:score,yaw,output=value,trial_yaw,candidate
            reports.append(dict(object_key=key,initial_score=initial,score=score,translation_m=translation.tolist(),yaw_delta_deg=yaw,scale_changed=False))
    except LocalLimit:pass
    finally:evaluator.guard=previous_guard
    return output,dict(method='relative_support_visible_masks',objects=reports,evaluations=budget.evaluations,stop_reason=budget.reason,source_transforms_used=False,post_contact_verification_required=True)
