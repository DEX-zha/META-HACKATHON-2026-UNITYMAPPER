"""Candidate-only support topology and rigid group proposals."""
from copy import deepcopy
import numpy as np
from .domain import AgentError
from .reference_geometry import rotation,rotation_euler


class SupportGraph:
    def __init__(self,plan,supports):
        self.keys=[o['key'] for o in plan['objects']]
        if len(set(self.keys))!=len(self.keys):raise AgentError('INVALID_SUPPORT','Duplicate object')
        self.parents={k:None for k in self.keys};seen=set();self.policies={}
        for row in supports:
            k,p=row['object_key'],row['support_key']
            if k not in self.parents or k in seen or p is not None and (p not in self.parents or p==k):raise AgentError('INVALID_SUPPORT','Unknown or duplicate edge')
            policy=row.get('contact_policy','required_contact')
            if policy not in {'required_contact','offset_evidenced','unresolved'}:raise AgentError('INVALID_SUPPORT','Unknown contact policy')
            seen.add(k);self.parents[k]=p;self.policies[k]=policy
        for k in self.keys:
            chain=set();p=k
            while p is not None:
                if p in chain:raise AgentError('INVALID_SUPPORT','Cyclic support graph')
                chain.add(p);p=self.parents[p]
        self.roots=[k for k in self.keys if self.parents[k] is None]

    def descendants(self,key):
        if key not in self.parents:raise AgentError('INVALID_SUPPORT','Unknown group root')
        group=[key]
        for parent in group:group.extend(k for k in self.keys if self.parents[k]==parent)
        return group

    def relative_pose(self,plan,key):
        by_key={o['key']:o for o in plan['objects']};item=by_key[key];parent=by_key.get(self.parents[key])
        if parent is None:return deepcopy(item)
        inverse=rotation(parent['rotation_deg']).T
        scale=np.asarray(parent['scale'],dtype=float)
        if not np.isfinite(scale).all() or np.any(np.abs(scale)<1e-9):raise AgentError('INVALID_SUPPORT','Singular support scale')
        local=(inverse@(np.array(item['position_m'])-parent['position_m']))/scale
        return dict(position_m=local.tolist(),support_key=parent['key'],rotation_deg=rotation_euler(inverse@rotation(item['rotation_deg'])),scale=(np.asarray(item['scale'])/scale).tolist())

    def transform_group(self,plan,key,translation,yaw_deg=0,*,rotation_deg=None):
        delta=np.asarray(translation,dtype=float)
        if delta.shape!=(3,) or not np.isfinite(delta).all() or np.max(np.abs(delta))>1 or not np.isfinite(yaw_deg) or abs(yaw_deg)>180:raise AgentError('INVALID_SUPPORT','Unbounded group transform')
        angles=np.asarray(rotation_deg if rotation_deg is not None else [0,yaw_deg,0],dtype=float)
        if angles.shape!=(3,) or not np.isfinite(angles).all() or np.max(np.abs(angles))>180:raise AgentError('INVALID_SUPPORT','Unbounded group rotation')
        result=deepcopy(plan);by_key={o['key']:o for o in result['objects']};pivot=np.array(by_key[key]['position_m']);matrix=rotation(angles)
        for name in self.descendants(key):
            item=by_key[name];item['position_m']=(pivot+matrix@(np.array(item['position_m'])-pivot)+delta).tolist()
            item['rotation_deg']=rotation_euler(matrix@rotation(item['rotation_deg']))
        return result
