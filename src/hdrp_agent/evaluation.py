"""Deterministic acceptance on frozen, operator-owned evidence; never model votes."""
from copy import deepcopy
from datetime import datetime
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import ValidationError

from .domain import AgentError, fingerprint, payload

METHODS={
    'luminance_error':{'artifact','visibility'},'luminance_range':{'visibility'},
    'beam_visibility':{'visibility','artistic'},'support_gap':{'geometry'},
    'intersection_depth':{'geometry'},'artistic_review':{'artistic'},
    'frame_time_regression':{'performance'},
}
REVIEW_FIELDS={'session_id','before_version','after_version','criteria_hash','criterion_id','reviewer_id','decision','notes','created_at'}


def finite(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Missing finite measurement')
    return value


class Evaluator:
    def __init__(self,artifacts,reviews):self.artifacts,self.reviews=artifacts,Path(reviews)

    def freeze(self,criteria,targets):
        try:
            for criterion in criteria:
                payload('Criterion',criterion)
                if criterion['method'] not in METHODS or criterion['kind'] not in METHODS[criterion['method']]:raise ValueError('Unknown method or inconsistent criterion kind')
                if criterion['target'] not in targets:raise ValueError('Unregistered evaluation target')
                target=targets[criterion['target']]
                if criterion['method'] in {'luminance_error','luminance_range','beam_visibility'}:
                    if not isinstance(target.get('camera_key'),str) or not target['camera_key']:raise ValueError('A registered camera is required')
                    roi=target.get('roi',[])
                    if len(roi)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in roi) or roi[0]>=roi[2] or roi[1]>=roi[3]:raise ValueError('Invalid registered region')
                    if criterion['method']=='luminance_error':
                        if not isinstance(target.get('reference_artifact_hash'),str):raise ValueError('Private reference evidence is required')
                        self._luma(target['reference_artifact_hash'],roi)
                    if criterion['method']=='beam_visibility':
                        background=target.get('background_roi',[])
                        if len(background)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in background) or background[0]>=background[2] or background[1]>=background[3]:raise ValueError('Registered beam background region is required')
                low,high=criterion['minimum'],criterion['maximum']
                for bound in (low,high):
                    if bound is not None:finite(bound)
                if low is not None and high is not None and low>high:raise ValueError('Inverted criterion bounds')
                if criterion['method']!='artistic_review' and low is None and high is None:raise ValueError('Numeric criterion needs a threshold')
                method=criterion['method'];unit=criterion['unit']
                allowed={'luminance_error':{'relative_reduction','regression','normalized'},'luminance_range':{'normalized'},'beam_visibility':{'contrast'},'support_gap':{'m'},'intersection_depth':{'m'},'artistic_review':{'human'},'frame_time_regression':{'ratio'}}
                if unit not in allowed[method]:raise ValueError('Unsupported measurement unit')
            if not criteria or len({c['id'] for c in criteria})!=len(criteria):raise ValueError('Criteria IDs must be unique')
        except (ValidationError,ValueError,AgentError,OSError) as exc:raise AgentError('INVALID_CRITERIA',str(exc),422) from exc
        frozen=deepcopy(dict(criteria=criteria,targets=targets,criteria_hash=fingerprint(criteria)))
        frozen['frozen_hash']=fingerprint(frozen)
        return frozen

    def _luma(self,digest,roi):
        if len(roi)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>1 for x in roi) or roi[0]>=roi[2] or roi[1]>=roi[3]:raise ValueError('Invalid registered region')
        with Image.open(io.BytesIO(self.artifacts.read(digest))) as im:
            if im.width>1920 or im.height>1080:raise ValueError('Oversized evaluation image')
            rgb=np.asarray(im.convert('RGB'),dtype=np.float64)/255
        h,w=rgb.shape[:2];x0,y0,x1,y1=[round(x*d) for x,d in zip(roi,[w,h,w,h])]
        if x1<=x0 or y1<=y0:raise ValueError('Empty evaluation region')
        rgb=rgb[y0:y1,x0:x1];linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        return linear@np.array([.2126,.7152,.0722])

    def _image(self,packet,target,roi=None):
        captures=[c for c in packet['captures'] if c['camera_key']==target['camera_key']]
        if len(captures)!=1:raise ValueError('Target requires one registered static camera')
        return self._luma(captures[0]['artifact_hash'],roi or target['roi'])

    def _review(self,session_id,before,after,criteria_hash,criterion_id):
        if not self.reviews.exists():return None
        decisions={}
        for path in sorted(self.reviews.glob('*.json')):
            if path.is_symlink() or path.stat().st_size>100_000:continue
            try:
                review=json.loads(path.read_text())
                if set(review)!=REVIEW_FIELDS or type(review['decision']) is not bool:continue
                if any(not isinstance(review[k],str) or not review[k] or len(review[k])>4000 for k in REVIEW_FIELDS-{'decision'}):continue
                if datetime.fromisoformat(review['created_at'].replace('Z','+00:00')).tzinfo is None:continue
                if (review['session_id'],review['before_version'],review['after_version'],review['criteria_hash'],review['criterion_id'])!=(session_id,before['version'],after['version'],criteria_hash,criterion_id):continue
                reviewer=review['reviewer_id']
                if reviewer in decisions and decisions[reviewer]!=review['decision']:return None
                decisions[reviewer]=review['decision']
            except (ValueError,TypeError,OSError,KeyError):continue
        return all(decisions.values()) if decisions else None

    def _measure(self,criterion,target,before,after,session_id,criteria_hash):
        method=criterion['method']
        if method=='artistic_review':return self._review(session_id,before,after,criteria_hash,criterion['id']),None
        if method=='frame_time_regression':
            if before.get('capture_policy')!=after.get('capture_policy'):raise ValueError('Performance capture policies differ; a fresh matched baseline is required')
            values=[]
            for packet in [before,after]:
                p=packet['performance']
                if p['frame_count']!=120 or p['method']!='editor_wall_frame_time_no_readback' or p['capture_framerate_disabled'] is not True:raise ValueError('Unqualified performance samples')
                if p.get('focused') is not True or p.get('focus_stable') is not True or p.get('v_sync_count')!=0 or p.get('target_frame_rate')!=-1:raise ValueError('Performance requires stable foreground focus with vSync and frame cap disabled')
                values.append(finite(p['median_frame_ms']))
            if values[0]<=0 or values[1]<=0:raise ValueError('Invalid frame duration')
            return values[1]/values[0]-1,None
        if method in {'support_gap','intersection_depth'}:
            key={'support_gap':'support_gap_m','intersection_depth':'intersection_depth_m'}[method]
            value=finite(after['geometry'][criterion['target']][key]);previous=finite(before['geometry'][criterion['target']][key])
            low,high=criterion['minimum'],criterion['maximum']
            distance=lambda x:max(0,(low-x) if low is not None else 0,(x-high) if high is not None else 0)
            return value,distance(value)<distance(previous)
        a=self._image(before,target);b=self._image(after,target)
        if a.shape!=b.shape:raise ValueError('Region dimensions differ')
        if method=='luminance_error':
            reference=self._luma(target['reference_artifact_hash'],target['roi'])
            if a.shape!=reference.shape:raise ValueError('Reference is not aligned')
            ea=float(np.mean(np.abs(a-reference)));eb=float(np.mean(np.abs(b-reference)))
            if criterion['unit']=='relative_reduction':
                if ea<=1e-9:raise ValueError('No measurable baseline defect')
                return (ea-eb)/ea,eb<ea
            return (eb-ea if criterion['unit']=='regression' else eb),eb<ea
        if method=='luminance_range':
            value=float(np.mean(b));previous=float(np.mean(a))
            low,high=criterion['minimum'],criterion['maximum']
            distance=lambda x:max(0,(low-x) if low is not None else 0,(x-high) if high is not None else 0)
            return value,distance(value)<distance(previous)
        background=self._image(after,target,target['background_roi']);old_background=self._image(before,target,target['background_roi'])
        value=float(np.mean(b)-np.mean(background));previous=float(np.mean(a)-np.mean(old_background))
        return value,value>previous

    def evaluate(self,frozen,before,after,*,session_id):
        sealed={k:v for k,v in frozen.items() if k!='frozen_hash'}
        if fingerprint(sealed)!=frozen.get('frozen_hash') or fingerprint(frozen['criteria'])!=frozen['criteria_hash']:raise AgentError('CRITERIA_FROZEN','Evaluation thresholds and targets are frozen')
        issues=[]
        if before.get('inspection_hash')!=after.get('inspection_hash') or before.get('conditions_hash')!=after.get('conditions_hash'):issues.append('Capture conditions differ')
        for packet in [before,after]:
            if packet.get('comparable') is not True:issues.append('Repeated witness is unverified')
            captures=packet.get('captures',[])
            if len({c['camera_key'] for c in captures if c['role']=='work'})<3 or len({c['camera_key'] for c in captures if c['role']=='control'})<2:issues.append('Three work and two control views are required')
            if any(c['version_id']!=packet['version'] or c.get('render_ready') is not True or c.get('provenance')!='live' for c in captures):issues.append('Current live rendered evidence is required')
            if packet.get('requires_bake') and not packet.get('bake_verified'):issues.append('Current bake proof is missing')
        results={};improved=False;progress={}
        for c in frozen['criteria']:
            try:
                value,gain=self._measure(c,frozen['targets'][c['target']],before,after,session_id,frozen['criteria_hash'])
                if value is None:raise ValueError('Independent human review is missing')
                if c['method']=='artistic_review':passed=value
                else:
                    finite(value);passed=(c['minimum'] is None or value>=c['minimum']) and (c['maximum'] is None or value<=c['maximum'])
                improved=improved or (gain is True and c['kind'] in {'artifact','visibility','geometry'} and c['unit']!='regression')
                if c['kind'] in {'artifact','geometry'} and c['unit']!='regression':progress[c['id']]=gain
                results[c['id']]=dict(value=value,passed=bool(passed),reason=None)
            except (KeyError,ValueError,TypeError,AgentError,OSError) as exc:results[c['id']]=dict(value=None,passed=None,reason=str(exc))
        required=[results[c['id']] for c in frozen['criteria'] if c['required']]
        if any(r['passed'] is False for r in required):verdict='rejected'
        elif issues or any(r['passed'] is None for r in required):verdict='inconclusive'
        elif improved:verdict='improved'
        else:verdict='no_improvement'
        return dict(schema_version='1.0',session_id=session_id,before_version=before['version'],after_version=after['version'],criteria_hash=frozen['criteria_hash'],frozen_hash=frozen['frozen_hash'],per_criterion=results,target_progress=progress,verdict=verdict,provisional=verdict=='inconclusive',issues=sorted(set(issues)),judge_provenance='deterministic_metrics_and_independent_local_reviews')
