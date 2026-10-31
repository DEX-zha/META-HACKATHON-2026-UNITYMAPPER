"""Geometry in calibrated images, independently of RGB and source scene poses."""
from copy import deepcopy
import io
import math
import numpy as np
from PIL import Image
from .domain import AgentError,fingerprint
from .reference_geometry import rotation,project_points,ray


def boundary(mask):
    padded=np.pad(mask,1);interior=padded[1:-1,1:-1]&padded[:-2,1:-1]&padded[2:,1:-1]&padded[1:-1,:-2]&padded[1:-1,2:]
    return mask&~interior


def mask_metrics(reference,candidate,pixel_scale=1):
    a=np.asarray(reference,dtype=bool);b=np.asarray(candidate,dtype=bool)
    if a.shape!=b.shape:raise AgentError('INVALID_MEDIA','Masks have different calibrated grids')
    if not a.any():return dict(visible_iou=None,contour_error_px=None,centroid_error_px=None,missing_reason='empty_reference_mask')
    if not b.any():return dict(visible_iou=0.,contour_error_px=float(math.hypot(*a.shape)*pixel_scale),centroid_error_px=None,missing_reason='candidate_not_visible')
    iou=float((a&b).sum()/(a|b).sum());ac=np.argwhere(boundary(a));bc=np.argwhere(boundary(b))
    # Bounded, deterministic contour quadrature; report its sampling limit.
    ac=ac[np.linspace(0,len(ac)-1,min(512,len(ac)),dtype=int)];bc=bc[np.linspace(0,len(bc)-1,min(512,len(bc)),dtype=int)]
    def distance(x,y):
        return np.concatenate([np.sqrt(((v[:,None,:]-y[None,:,:])**2).sum(axis=2).min(axis=1)) for v in np.array_split(x,max(1,math.ceil(len(x)/64)))])
    contour=float((distance(ac,bc).mean()+distance(bc,ac).mean())*.5*pixel_scale)
    centre=float(np.linalg.norm(np.argwhere(a).mean(axis=0)-np.argwhere(b).mean(axis=0))*pixel_scale)
    return dict(visible_iou=iou,contour_error_px=contour,centroid_error_px=centre,missing_reason=None,contour_samples_max=512)


def appearance_metrics(reference,candidate):
    a=np.asarray(reference,dtype=float);b=np.asarray(candidate,dtype=float)
    if a.shape!=b.shape or a.ndim!=3:raise AgentError('INVALID_MEDIA','Appearance grids differ')
    # Inputs are normalized RGB, supplied by the matched capture protocol.
    if not np.isfinite(a).all() or not np.isfinite(b).all() or a.min()<0 or b.min()<0 or a.max()>1 or b.max()>1:raise AgentError('INVALID_MEDIA','Normalized finite RGB required')
    luminance=lambda x:x@np.array([.2126,.7152,.0722])
    la,lb=luminance(a),luminance(b)
    gradient=sum(float(np.abs(np.diff(la,axis=k)-np.diff(lb,axis=k)).mean()) for k in [0,1])/2
    return dict(rgb_mae=float(np.abs(a-b).mean()),luminance_mae=float(np.abs(la-lb).mean()),shadow_gradient_mae=gradient,saturation_fraction_delta=float(np.mean(b.max(axis=2)>.99)-np.mean(a.max(axis=2)>.99)))


def appearance_regions(reference,candidate,regions):
    """Same pixel regions on both images; never recenter around the candidate."""
    a=np.asarray(reference,dtype=float);b=np.asarray(candidate,dtype=float)
    result=dict(global_metrics=appearance_metrics(a,b),regions={})
    for key,region in regions.items():
        mask=np.asarray(region,dtype=bool)
        if mask.shape!=a.shape[:2]:raise AgentError('INVALID_MEDIA','Appearance mask grid differs')
        if int(mask.sum())<16:
            result['regions'][key]=dict(measured=False,reason='region_too_small');continue
        la=a@np.array([.2126,.7152,.0722]);lb=b@np.array([.2126,.7152,.0722])
        gradients=[]
        for axis in [0,1]:
            adjacent=(mask[:-1]&mask[1:]) if axis==0 else (mask[:,:-1]&mask[:,1:])
            error=np.abs(np.diff(la,axis=axis)-np.diff(lb,axis=axis))
            if adjacent.any():gradients.append(float(error[adjacent].mean()))
        result['regions'][key]=dict(measured=True,pixel_count=int(mask.sum()),rgb_mae=float(np.abs(a-b)[mask].mean()),luminance_mae=float(np.abs(la-lb)[mask].mean()),shadow_gradient_mae=float(np.mean(gradients)) if gradients else None,reference_saturated_fraction=float((a.max(axis=2)[mask]>.99).mean()),candidate_saturated_fraction=float((b.max(axis=2)[mask]>.99).mean()))
    return result


def assess_appearance(before,after,*,reference_protocol,candidate_protocol,controls,noise_bound):
    """Independent appearance gate; control evidence never enters model context."""
    issues=[]
    if not reference_protocol or reference_protocol!=candidate_protocol:issues.append(dict(kind='capture_protocol_unqualified'))
    if noise_bound is None or not math.isfinite(noise_bound) or noise_bound<0:issues.append(dict(kind='capture_noise_unqualified'))
    if not controls:issues.append(dict(kind='missing_control_views'))
    tolerance=noise_bound if noise_bound is not None and math.isfinite(noise_bound) and noise_bound>=0 else 0
    if after['global_metrics']['luminance_mae']>=before['global_metrics']['luminance_mae']-tolerance:issues.append(dict(kind='no_appearance_gain'))
    for key,previous in before['regions'].items():
        if not previous['measured']:continue
        current=after['regions'].get(key,{})
        if not current.get('measured'):issues.append(dict(kind='appearance_region_missing',region=key));continue
        if current['luminance_mae']>previous['luminance_mae']+tolerance or current['candidate_saturated_fraction']>max(previous['candidate_saturated_fraction'],current['reference_saturated_fraction'])+tolerance:issues.append(dict(kind='appearance_region_regression',region=key))
    for key,values in controls.items():
        if values.get('before') is None or values.get('after') is None or values['after']>values['before']+tolerance:issues.append(dict(kind='appearance_control_regression',view_key=key))
    return not issues,issues


def bind_measurements(plan,version,metrics,*,expected_version=None):
    if not version or expected_version is not None and version!=expected_version:raise AgentError('STALE_VERSION','Geometry does not describe applied version')
    if 'version' in metrics and metrics['version']!=version:raise AgentError('STALE_VERSION','Reused geometry version')
    if metrics.get('applied_plan_hash',fingerprint(plan))!=fingerprint(plan):raise AgentError('STALE_VERSION','Geometry belongs to a different applied plan')
    if metrics.get('stage') not in {None,'after_native_contacts'}:raise AgentError('STALE_VERSION','Proposal measurements cannot certify native contact results')
    value=deepcopy(metrics);value.update(version=version,applied_plan_hash=fingerprint(plan),stage='after_native_contacts')
    return value


def primitive_mesh(kind):
    if kind=='plane':return [(np.array([[-5,0,-5],[5,0,-5],[5,0,5],[-5,0,5]],float),np.array([[0,1,2],[0,2,3]]))]
    if kind!='cube':return []
    vertices=np.array([[x,y,z] for x in [-.5,.5] for y in [-.5,.5] for z in [-.5,.5]])
    triangles=np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],[2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]])
    return [(vertices,triangles)]


class SceneRaster:
    """Perspective-correct triangle depth, all candidate meshes share one buffer."""
    def __init__(self,geometry):
        self.meshes={a['asset_id']:[(np.asarray(m['vertices'],float),np.asarray(m['triangles'],int).reshape(-1,3)) for m in a['meshes']] for a in geometry}

    def render(self,plan,view,size,guard=None,only_keys=None):
        w,h=size;depth=np.full((h,w),np.inf);identity=np.full((h,w),-1,dtype=np.int16);unsupported=[];near_clipped=False
        for object_id,item in enumerate(plan['objects']):
            if only_keys is not None and item['key'] not in only_keys:continue
            meshes=self.meshes.get(item.get('asset_id'),primitive_mesh(item.get('primitive')))
            if not meshes:unsupported.append(item['key']);continue
            matrix=rotation(item['rotation_deg'])
            for vertices,triangles in meshes:
                world=(vertices*item['scale'])@matrix.T+item['position_m'];uv,z=project_points(world,view,size)
                # Discard offscreen faces in bulk before entering the raster loop.
                points=uv[triangles];zs=z[triangles];near=zs.min(axis=1)>.01
                near_clipped|=bool(np.any((zs.min(axis=1)<=.01)&(zs.max(axis=1)>.01)))
                finite=np.isfinite(points).all(axis=(1,2));lo=np.nan_to_num(points,nan=-1e6).min(axis=1);hi=np.nan_to_num(points,nan=-1e6).max(axis=1)
                kept=np.where(near&finite&(hi[:,0]>=0)&(hi[:,1]>=0)&(lo[:,0]<w)&(lo[:,1]<h))[0]
                for n,idx in enumerate(kept):
                    if guard and n%64==0:guard()
                    p=points[idx];tz=zs[idx];x0,y0=np.maximum(0,np.floor(lo[idx]).astype(int));x1,y1=np.minimum([w-1,h-1],np.ceil(hi[idx]).astype(int))
                    den=(p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
                    if abs(den)<1e-10:continue
                    yy,xx=np.mgrid[y0:y1+1,x0:x1+1];xx=xx+.5;yy=yy+.5
                    a=((p[1,1]-p[2,1])*(xx-p[2,0])+(p[2,0]-p[1,0])*(yy-p[2,1]))/den
                    b=((p[2,1]-p[0,1])*(xx-p[2,0])+(p[0,0]-p[2,0])*(yy-p[2,1]))/den;c=1-a-b
                    inside=(a>=-1e-8)&(b>=-1e-8)&(c>=-1e-8);inv=a/tz[0]+b/tz[1]+c/tz[2]
                    d=np.divide(1,inv,out=np.full_like(inv,np.inf),where=inv>0);old=depth[y0:y1+1,x0:x1+1];win=inside&(d<old)
                    old[win]=d[win];identity[y0:y1+1,x0:x1+1][win]=object_id
        return identity,dict(unsupported_objects=unsupported,near_plane_clipping_unqualified=near_clipped)


class GeometryEvaluator:
    def __init__(self,frames,segments,geometry,artifacts,*,width=256,guard=None):
        self.raster=SceneRaster(geometry);self.guard=guard;self.width=width;self.observations={};self.excluded=[];by_view={f['key']:f for f in frames if not f['key'].startswith('control-')}
        for segment in segments:
            chosen=segment.get('selection');frame=by_view.get(segment['view_key'])
            if not chosen or not frame or not frame.get('calibration') or chosen.get('confidence',0)<.7:
                self.excluded.append(dict(object_key=segment['object_key'],view_key=segment['view_key'],reason='missing_or_low_confidence_mask'));continue
            w,h=frame['model_size'];size=(min(w,width),round(h*min(w,width)/w));x0,y0,x1,y1=[round(v*d) for v,d in zip(chosen['bbox_xyxy'],[w,h,w,h])]
            # A one-pixel contour displacement is already >12% of an 8 px
            # object width. Keep such evidence as unknown and use its closeups.
            if min(x1-x0,y1-y0)<16 or min(x1-x0,y1-y0)*size[0]/w<4:
                self.excluded.append(dict(object_key=segment['object_key'],view_key=segment['view_key'],reason='insufficient_mask_pixel_extent'));continue
            with Image.open(io.BytesIO(artifacts.read(chosen['mask_hash']))) as im:crop=im.convert('L').resize((x1-x0,y1-y0),Image.Resampling.NEAREST)
            full=Image.new('L',(w,h));full.paste(crop,(x0,y0));mask=np.asarray(full.resize(size,Image.Resampling.NEAREST))>127
            observation=self.observations.setdefault(frame['key'],dict(view=frame['calibration'],size=size,scale=w/size[0],objects={},truncated_objects=[]))
            observation['objects'][segment['object_key']]=mask
            if x0<=0 or y0<=0 or x1>=w or y1>=h:observation['truncated_objects'].append(segment['object_key'])

    def independent_views(self,key,minimum=2):
        """Reject repeated viewpoints/zoom-only images as depth coverage."""
        from itertools import combinations
        rays=[]
        for obs in self.observations.values():
            if key in obs.get('truncated_objects',[]):continue
            mask=obs['objects'].get(key)
            if mask is None or not mask.any():continue
            y,x=np.argwhere(mask).mean(axis=0);w,h=obs['size']
            rays.append(ray(obs['view'],[x/w,y/h,x/w,y/h],w/h))
        for group in combinations(rays,minimum):
            if all(np.linalg.norm(a[0]-b[0])>=.05 and np.linalg.norm(np.cross(a[1],b[1]))>=math.sin(math.radians(3)) for a,b in combinations(group,2)):return True
        return False

    def measure(self,plan,version,*,keys=None):
        per_object={o['key']:dict(views={},missing_reasons=[]) for o in plan['objects'] if o.get('asset_id') is not None and (keys is None or o['key'] in keys)};issues=[]
        ids={o['key']:i for i,o in enumerate(plan['objects'])}
        for key,obs in self.observations.items():
            active=set(obs['objects'])&set(per_object)
            if not active:continue
            identity,status=self.raster.render(plan,obs['view'],obs['size'],self.guard)
            if status['unsupported_objects'] or status['near_plane_clipping_unqualified']:issues.append(dict(view_key=key,**status))
            for object_key in active:per_object[object_key]['views'][key]=mask_metrics(obs['objects'][object_key],identity==ids[object_key],obs['scale'])
        values=[]
        for key,row in per_object.items():
            valid=[v for v in row['views'].values() if v['visible_iou'] is not None]
            row['view_count']=len(valid);row['mean_iou']=float(np.mean([v['visible_iou'] for v in valid])) if valid else None
            row['contour_error_px']=float(np.mean([v['contour_error_px'] for v in valid])) if valid else None
            row['covered']=len(valid)>=2 and self.independent_views(key)
            if not row['covered']:row['missing_reasons'].append('fewer_than_two_independent_reliable_views')
            if any(key in obs.get('truncated_objects',[]) for obs in self.observations.values()):row['missing_reasons'].append('truncated_masks_do_not_establish_full_coverage')
            if row['mean_iou'] is not None:values.append(1-row['mean_iou'])
        result=dict(per_object=per_object,score=float(np.mean(values)) if values else None,coverage_complete=bool(per_object) and all(v['covered'] for v in per_object.values()) and not issues,render_issues=issues,excluded_masks=self.excluded,grid_width=self.width,metric='visible_mesh_iou_without_rgb',fidelity_verified=False)
        bound=bind_measurements(plan,version,result)
        if version=='local-proposal':bound['stage']='proposal_prediction'
        return bound
