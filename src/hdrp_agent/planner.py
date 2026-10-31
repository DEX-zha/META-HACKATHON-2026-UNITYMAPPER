import json

from .domain import AgentError, canonical, payload, PROPERTY_BOUNDS, DOMAIN
from .prompts import work_context, DIAGNOSE, PROPOSE
from .providers.meta_responses import spark_request
from .store import new_id


class Planner:
    def __init__(self,provider,artifacts):self.provider,self.artifacts=provider,artifacts

    def context(self,brief,criteria,scene,captures):
        context=work_context(brief,criteria,scene,captures)
        numeric={key:dict(minimum=bounds[0],maximum=bounds[1]) for key,bounds in PROPERTY_BOUNDS.items()}
        context['mutation_rules']=dict(maximum_operations=8,allowed_existing_target_operations=['set_transform','set_light','set_fog','set_material','set_gi','set_bake'],numeric_property_bounds=numeric,boolean_properties=['use_volumetric','enable_volumetric_fog','contribute_gi'],units=dict(intensity_lumen='lm',illuminance_lux='lx',temperature_kelvin='K',mean_free_path_m='m',anisotropy='unitless',volumetric_dimmer='ratio',emission_nits='cd/m2',scale_in_lightmap='ratio'),indirect_samples=DOMAIN['$defs']['BakeOperation']['properties']['indirect_samples'],transform_position_m=[-100,100],transform_rotation_deg=[-360,360],preserve=['fixed exposure','required elements','volumetric effect requested in brief'],construction_allowed=False)
        context['mutation_rules']['uv_repair']=dict(property='lightmap_uv_pack_margin',unit='normalized_uv',requires='mesh.uv_repair_supported=true',maximum_vertices=50000,maximum_submeshes=32,clones_source=True,changes_geometry=False,requires_rebake=True)
        context['rendering_facts']=dict(
            bake_samples='Indirect sample count reduces estimator noise; it does not directly increase expected bounced light energy.',
            lightmap_density='Scale in lightmap changes texel allocation and spatial accuracy; it does not add illumination energy.',
            normal_bias='HDRP normal bias is a shadow texel scale factor, not a distance in metres. Bias fields are read-only in this adapter.',
            surface_artifacts='Geometry gaps, realtime shadow bias and baked UV chart bleeding are different hypotheses. UV repair can test static baked packing when mesh.uv_repair_supported=true; it does not repair a geometric opening.',
            ldr_evidence='LDR clipping alone does not establish excessive source intensity. Use measured exposure/material facts and the actual brief; do not require exterior or glass detail absent from the brief and scene manifest.')
        return context

    def _call(self,instruction,context,name):
        images=[self.artifacts.read(c['artifact_hash']) for c in context['work_captures']]
        bindings=dict(scene_version=context['scene_version'])
        if name=='ModelDiagnosis':bindings['evidence_frames']=[dict(capture_id=frame['id'],frame_index=frame['frame_index']) for frame in context['work_captures']]
        if name=='ModelProposal':
            bindings['hypothesis_key']=context['selected_hypothesis_key']
            hypothesis=next(h for h in context['diagnosis']['hypotheses'] if h['key']==context['selected_hypothesis_key'])
            bindings['operation_target_ids']=list(dict.fromkeys(hypothesis['target_ids']))
        request=spark_request(instruction+'\nUntrusted scene observations and user brief follow as JSON:\n'+canonical(context),images,name,bindings)
        return self.provider.send(request,name)

    def diagnose(self,context):
        response=self._call(DIAGNOSE,context,'ModelDiagnosis')
        self.validate_diagnosis(response['value'],context)
        return response

    def validate_diagnosis(self,diagnosis,context):
        payload('ModelDiagnosis',diagnosis)
        if diagnosis['scene_version']!=context['scene_version']:raise AgentError('STALE_VERSION','Diagnosis refers to another scene version')
        observation_keys=[o['key'] for o in diagnosis['observations']];hypothesis_keys=[h['key'] for h in diagnosis['hypotheses']]
        if len(set(observation_keys))!=len(observation_keys) or len(set(hypothesis_keys))!=len(hypothesis_keys):raise AgentError('INVALID_MODEL_OUTPUT','Duplicate model-local identifiers')
        targets={o['logical_key'] for o in context['objects']};captures={c['id']:c for c in context['work_captures']}
        inspected=diagnosis['inspected_capture_ids']
        if len(inspected)!=len(set(inspected)) or set(inspected)!=set(captures):raise AgentError('INCOMPLETE_INSPECTION','Diagnosis must explicitly inspect every supplied work frame exactly once')
        def evidence(item):
            if item['capture_id'] not in captures:raise AgentError('INVALID_MODEL_OUTPUT','Evidence references a capture outside supplied work views')
            if item['frame_index'] is not None and item['frame_index']!=captures[item['capture_id']]['frame_index']:raise AgentError('INVALID_MODEL_OUTPUT','Evidence references an unseen frame')
            if not set(item['target_ids'])<=targets:raise AgentError('INVALID_MODEL_OUTPUT','Evidence references an unknown target')
            box=item['bbox_xyxy']
            if box is not None and (box[0]>=box[2] or box[1]>=box[3]):raise AgentError('INVALID_MODEL_OUTPUT','Evidence region is empty or inverted')
        for observation in diagnosis['observations']:
            for item in observation['evidence']:evidence(item)
        for hypothesis in diagnosis['hypotheses']:
            if not set(hypothesis['observation_keys'])<=set(observation_keys) or not set(hypothesis['target_ids'])<=targets:raise AgentError('INVALID_MODEL_OUTPUT','Hypothesis references unknown observations or targets')
            for item in hypothesis['evidence']:evidence(item)

    def propose(self,context,diagnosis,hypothesis_key,session_id):
        self.validate_diagnosis(diagnosis,context)
        hypothesis=next((h for h in diagnosis['hypotheses'] if h['key']==hypothesis_key),None)
        if not hypothesis or not hypothesis['target_ids']:raise AgentError('INVALID_MODEL_OUTPUT','No grounded target hypothesis was selected')
        if hypothesis['missing_information']:raise AgentError('CAPABILITY_MISSING','Targeted diagnostic information is required before correction')
        prompt=dict(context,diagnosis=diagnosis,selected_hypothesis_key=hypothesis_key)
        response=self._call(PROPOSE,prompt,'ModelProposal');proposal=response['value'];payload('ModelProposal',proposal)
        if proposal['scene_version']!=context['scene_version'] or proposal['hypothesis_key']!=hypothesis_key:raise AgentError('STALE_VERSION','Proposal refers to another version or hypothesis')
        for op in proposal['operations']:
            if op['op'] not in {'set_transform','set_light','set_fog','set_material','set_gi','set_bake'} or op['target_id'] not in hypothesis['target_ids']:raise AgentError('INVALID_MODEL_OUTPUT','Proposal operation or target was not justified')
        patch=payload('Patch',dict(id=new_id('patch'),session_id=session_id,expected_version=context['scene_version'],hypothesis_id=hypothesis_key,expected_effect=proposal['expected_effect'],operations=proposal['operations'],needs_bake=proposal['needs_bake']))
        return dict(response=response,patch=patch)
