"""Construct model context from an allowlist; evaluation inputs never enter here."""
from .domain import AgentError, fingerprint
from copy import deepcopy

SCENE_FIELDS={'logical_key','name','active','position_m','rotation_deg','scale','light','volume','renderer','mesh'}
BAKE_FIELDS={'lightmapper','baked_gi','realtime_gi','lightmap_resolution_texels_per_unit','lightmap_max_size','lightmap_padding_texels','direct_samples','indirect_samples','environment_samples','mixed_mode','lightmap_count'}


def work_context(brief,criteria,scene,captures):
    version=scene['version']
    objects=[{k:v for k,v in obj.items() if k in SCENE_FIELDS} for obj in scene['objects']]
    public=[]
    for capture in captures:
        if capture['role']!='work':continue
        if capture['version_id']!=version or not capture['render_ready']:raise AgentError('STALE_VERSION','Work capture does not show the current rendered version')
        public.append({k:capture[k] for k in ['artifact_hash','version_id','inspection_hash','conditions_hash','camera_key','frame_index','simulated_time','provenance']})
        public[-1]['id']='capture-'+fingerprint(public[-1])[:32]
    if not public:raise AgentError('CAPABILITY_MISSING','No current work-view evidence is available')
    if len(public)>12:raise AgentError('INVALID_INPUT','Select at most 12 explicit work frames',422)
    if len({c['inspection_hash'] for c in public})!=1 or len({c['conditions_hash'] for c in public})!=1:raise AgentError('CAPTURE_UNSTABLE','Work frames have incompatible conditions')
    bake={key:value for key,value in scene.get('bake',{}).items() if key in BAKE_FIELDS}
    return deepcopy(dict(brief=brief,criteria=criteria,scene_version=version,objects=objects,work_captures=public,capabilities=scene.get('capabilities',[]),bake_settings=bake))


DIAGNOSE='''Inspect the whole visible scene in EVERY supplied work frame, including timestamped clip frames. Return all their exact IDs in inspected_capture_ids. Scan lighting leaks, wall/ceiling/window joints, shadow consistency, GI, volumetric effects, materials and placement against the brief. Report remaining technical defects across all views, not just the first obvious one. Group repeated instances with the same plausible cause and list every supported affected target. Return at most five concise observations and three prioritized hypotheses, one evidence item each, sentences under 160 characters. Empty hypotheses is appropriate only when no remaining grounded technical correction is available; put unaddressable defects in unsupported_limits. Use the exact scene_version and capture IDs. A patch is a controlled experiment whose success requires new renders and independent evaluation. Put causal uncertainty in uncertainty; missing_information contains only facts required to safely specify an experiment, not its unknown outcome. Known capability bounds and absolute UV regeneration do not require knowing the original generator settings. Separate observed facts from hypotheses and artistic judgment. SAM regions are uncertain selections. Never fabricate invisible details, suggest arbitrary scripts, or claim artistic acceptance. The system repeats this global inspection after every patch without asking the user to point out individual areas.'''
PROPOSE='''Propose one causal HDRP correction for the selected hypothesis, covering all affected existing targets supported by that hypothesis, including repeated surfaces. Use supported operations and exact bounds/units; at most eight operations. UV regeneration uses a protected mesh clone and requires mesh.uv_repair_supported=true; it does not move geometry. Preserve exposure, ambiance constraints and required elements. The runtime decides whether rebaking is required. Do not create/delete scene objects, run code, hide evidence, or declare success. If evidence is insufficient, no patch is admissible.'''
