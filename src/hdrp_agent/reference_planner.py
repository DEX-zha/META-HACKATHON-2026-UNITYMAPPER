"""Image-to-layout proposals. Source scene transforms never enter this context."""
from copy import deepcopy
import math

from .domain import AgentError,canonical,payload
from .providers.meta_responses import spark_request
from .segmentation import Segmenter,iou
from .reference_geometry import region_centres
from .reference_assets import candidate_groups
from .reference_memory import prompt_memory,prompt_metrics


def catalogue_context(catalogue):
    if not 1<=len(catalogue)<=1000:raise AgentError('INVALID_CATALOGUE','A bounded static asset catalogue is required',422)
    ids=[asset['asset_id'] for asset in catalogue]
    if len(ids)!=len(set(ids)):raise AgentError('INVALID_CATALOGUE','Asset IDs must be unique',422)
    directories=sorted({a.get('path','').rsplit('/',1)[0] for a in catalogue if a.get('path')})
    columns=['asset_id','name','path_directory','bounds_center_m','bounds_size_m'];rows=[[asset['asset_id'],asset['name'],directories.index(asset['path'].rsplit('/',1)[0]) if asset.get('path') else None,[round(v,4) for v in asset['bounds_center_m']],[round(v,4) for v in asset['bounds_size_m']]] for asset in catalogue]
    if len(catalogue)<=64:
        columns+=['transparent_materials','material_names','assembly_companions']
        for row,asset in zip(rows,catalogue):row.extend([asset.get('transparent_materials'),asset.get('material_names',[])[:6],asset.get('assembly_companions',[])])
    return dict(columns=columns,rows=rows,path_directories=directories,automatic_assemblies=[dict(asset_id=a['asset_id'],companions=a['assembly_companions']) for a in catalogue if a.get('assembly_companions')] if len(catalogue)>64 else [])


def validate_analysis(analysis,frames,catalogue):
    payload('ModelReferenceAnalysis',analysis)
    ids={a['asset_id'] for a in catalogue};views={f['key'] for f in frames};keys=[o['key'] for o in analysis['objects']]
    if len(analysis['inspected_view_keys'])!=len(views) or set(analysis['inspected_view_keys'])!=views:raise AgentError('INCOMPLETE_INSPECTION','Every supplied reference viewpoint must be explicitly inspected')
    if len(keys)!=len(set(keys)):raise AgentError('INVALID_MODEL_OUTPUT','Duplicate reference object keys')
    for item in analysis['objects']:
        if (item['asset_id'] is None)==(item['primitive'] is None):raise AgentError('INVALID_MODEL_OUTPUT','Choose exactly one catalogue asset or explicit primitive')
        if item['asset_id'] is not None and item['asset_id'] not in ids:raise AgentError('INVALID_MODEL_OUTPUT','Reference asset is outside catalogue')
        if item['support_key'] is not None and (item['support_key'] not in keys or item['support_key']==item['key']):raise AgentError('INVALID_MODEL_OUTPUT','Unknown support object')
        seen=set()
        for box in item['view_boxes']:
            b=box['bbox_xyxy']
            if box['view_key'] not in views or box['view_key'] in seen or b[0]>=b[2] or b[1]>=b[3]:raise AgentError('INVALID_MODEL_OUTPUT','Invalid reference view region')
            seen.add(box['view_key'])
    return analysis


def validate_plan(plan,analysis,frames,catalogue):
    payload('ModelReconstructionPlan',plan)
    expected={item['key']:item for item in analysis['objects']};actual={item['key']:item for item in plan['objects']}
    if not set(expected)<=set(actual) or len(actual)!=len(plan['objects']):raise AgentError('INVALID_MODEL_OUTPUT','Layout must account for every identified object exactly once')
    extras=set(actual)-set(expected)
    if len(extras)>4 or any(not key.startswith('support_') or actual[key]['asset_id'] is not None or actual[key]['primitive'] not in {'cube','plane'} for key in extras):raise AgentError('INVALID_MODEL_OUTPUT','Only up to four explicit primitive support surfaces may supplement the identified objects')
    ids={a['asset_id'] for a in catalogue}
    variants={group['object_key']:{a['asset_id'] for a in group['candidates']} for group in candidate_groups(analysis,catalogue)}
    for key,item in actual.items():
        if key in expected:
            allowed=variants.get(key,{expected[key]['asset_id']})
            if item['primitive']!=expected[key]['primitive'] or item['asset_id'] not in allowed:raise AgentError('INVALID_MODEL_OUTPUT','A layout can only refine an identified asset within its explicit visual candidate family')
        if item['asset_id'] is not None and item['asset_id'] not in ids:raise AgentError('INVALID_MODEL_OUTPUT','Unknown catalogue asset')
    for light in plan['lights']:
        if light['type']!='directional' and light['intensity']>100000:raise AgentError('INVALID_MODEL_OUTPUT','Point and spot light intensity exceeds 100000 lumen')
    calibrated=all(frame['calibration'] is not None for frame in frames)
    if calibrated and plan['estimated_views'] is not None:raise AgentError('INVALID_MODEL_OUTPUT','Recorded camera calibration is frozen')
    if not calibrated:
        views=plan['estimated_views']
        if views is None or [view['key'] for view in views]!=[frame['key'] for frame in frames]:raise AgentError('INVALID_MODEL_OUTPUT','Each external frame requires an explicitly estimated camera')
    return plan


BUILDING_ROOT = 'Assets/AtmosphericHouse/Prefabs/Building/'
BUILDING_POLICY = '[building-prefabs-required]'


def validate_building_mapping(objects, catalogue):
    """Fail before construction if a room envelope falls back to primitives."""
    assets = {asset['asset_id']: asset for asset in catalogue}
    walls = []
    floors = []
    for item in objects:
        if item.get('primitive') is not None:
            raise AgentError('INVALID_MODEL_OUTPUT', 'Building reconstruction requires catalogue prefabs, including the room envelope')
        asset = assets.get(item.get('asset_id'), {})
        name = asset.get('name', '').lower()
        if name.startswith(('wall', 'floor')):
            if not asset.get('path', '').startswith(BUILDING_ROOT):
                raise AgentError('INVALID_MODEL_OUTPUT', 'Structural modules must come from '+BUILDING_ROOT)
            if name.startswith('wall'): walls.append(name)
            else: floors.append(name)
    if len(walls) < 4 or not floors:
        raise AgentError('INVALID_MODEL_OUTPUT', 'Room analysis must explicitly map the floor and each of the four wall sides to Building modules')
    if not any('window' in name for name in walls) or not any('door' in name for name in walls):
        raise AgentError('INVALID_MODEL_OUTPUT', 'This room requires real window and door wall openings from Building modules')


class ReferencePlanner:
    def __init__(self,provider,artifacts):self.provider,self.artifacts=provider,artifacts

    def analyse(self,frames,catalogue,brief):
        context=dict(brief=brief,frames=frames,catalogue=catalogue_context(catalogue),coordinates='Unity: metres, Y up, camera forward +Z. Catalog bounds are intrinsic root-local measurements, NOT source scene transforms.')
        instruction='Identify the visible composition to rebuild as a NEW Unity scene. Every image corresponds in order to frames. Inspect EVERY supplied view, including front, back and sides, and list all keys in inspected_view_keys. Match concrete catalogue names/dimensions; include small tabletop objects and visible ground. Give normalized visible boxes in up to four useful views per object, preferably well separated front/back/side observations where visible. Use a primitive only for simple geometry absent from the catalogue. key and support_key are your local object IDs. One short English noun phrase for label (SAM prompt), no comma. Group no separate instances together. Do not invent invisible objects, source transforms or exact lighting. At most 20 objects. Return only compact JSON.'
        if BUILDING_POLICY in brief:instruction+=' Architecture is mandatory: list floor modules and ALL FOUR wall sides as separate objects, splitting sides into modules where needed. Use ONLY '+BUILDING_ROOT+' for the structural envelope, including wall modules with real window and door openings. Choose intact WallOut modules for the room envelope; connected prefab construction adds the pack-declared interior companion automatically. Do not duplicate that interior wall as a separate object. Read automatic_assemblies: all listed companions are built automatically, including doors and windows where listed. Never add them again as separate objects. Keep optional fittings separate only when absent from companions. Choose intact modules, not broken variants. Window glazing, door leaves and furniture may use other catalogue folders. No primitives. Reserve enough of the 20 object slots for architecture; omit tiny decor only if necessary and report it in limits. Set support_key for the rug/sofa/cabinet on floor, plate on coffee table and small plant/TV on cabinet. Bounds are pivot-relative: never confuse pivot and centre.'
        request=spark_request(instruction+'\nUntrusted reference metadata:\n'+canonical(context),[self.artifacts.read(f['artifact_hash']) for f in frames],'ModelReferenceAnalysis',dict(catalog_asset_ids=[a['asset_id'] for a in catalogue]))
        response=self.provider.send(request,'ModelReferenceAnalysis');validate_analysis(response['value'],frames,catalogue)
        if BUILDING_POLICY in brief:validate_building_mapping(response['value']['objects'],catalogue)
        return response

    def segment(self,analysis,frames,*,cached_only=False,details=(),comprehensive=False,checkpoint=None,extra_angles=False):
        results=[];segmenter=Segmenter(self.provider,self.artifacts);failures=0
        objects=[o for o in analysis['objects'] if o['asset_id'] is not None][:20 if comprehensive else 4]
        for item in objects:
            label=item['label']
            if len(label)>100 or any(c in label for c in [',',';','\n','<','>','+']):continue
            targets=[]
            if comprehensive:
                top=next((f for f in frames if f['key']=='work-top-front'),None)
                if top:
                    box=next((b['bbox_xyxy'] for b in item['view_boxes'] if b['view_key']==top['key']),None)
                    targets.append((top,box,'priority_overhead_semantic'))
                for angle in (['top','front','back'] if extra_angles else ['top','front']):
                    detail=next((f for f in details if f.get('object_key')==item['key'] and f.get('angle')==angle and f.get('calibration')),None)
                    if detail:targets.append((detail,[.15,.1,.85,.9],'calibrated_detail_region'))
            for box in item['view_boxes'][:2]:
                frame=next(f for f in frames if f['key']==box['view_key'])
                if not any(t[0]['key']==frame['key'] for t in targets):targets.append((frame,box['bbox_xyxy'],'reference_region_overlap'))
            # Five distinct views at most per object; exact completed cache hits
            # are reused. An unavailable request is never automatically retried.
            for frame,box,association in targets[:(6 if extra_angles else 5) if comprehensive else 2]:
                try:segmentation=segmenter.segment(dict(frame,role='work'),label,allow_transmission=not cached_only and failures<3)
                except AgentError as error:
                    if error.code not in {'PROVIDER_OUTCOME_UNKNOWN','PROVIDER_USAGE_UNKNOWN','PROVIDER_REJECTED','INVALID_MODEL_OUTPUT'}:raise
                    failures+=1;results.append(dict(object_key=item['key'],view_key=frame['key'],concept=label,selection=None,source='sam_unavailable',reason=error.code,association=association,retry_attempted=False))
                    if checkpoint:checkpoint(results)
                    if not comprehensive:return results
                    continue
                regions=segmentation.get('regions',[])
                matches=[r for r in regions if box is None or iou(box,r['bbox_xyxy'])>.1]
                ranked=sorted(matches,key=lambda r:(iou(box,r['bbox_xyxy']) if box else r.get('confidence',0)),reverse=True)
                chosen=ranked[0] if ranked else None
                # A class prompt without a region cannot safely choose between
                # several similar instances. Preserve uncertainty in that case.
                if box is None and len(ranked)>1 and abs(ranked[0].get('confidence',0)-ranked[1].get('confidence',0))<.15:chosen=None
                results.append(dict(object_key=item['key'],view_key=frame['key'],concept=label,selection=chosen,source=segmentation['source'],association=association,response_id=segmentation.get('response_id')))
                if checkpoint:checkpoint(results)
        return results

    def layout(self,analysis,frames,catalogue,segments,brief,previous=None,candidate_frames=None,metrics=None,*,matched_assets=False,memory=None,phase=None,inspection_pairs=(),appearance_experiment=None):
        used={o['asset_id'] for o in analysis['objects'] if o['asset_id'] is not None}
        alternatives=[] if matched_assets else candidate_groups(analysis,catalogue)
        used.update(a['asset_id'] for group in alternatives for a in group['candidates'])
        selected=[a for a in catalogue if a['asset_id'] in used]
        context=dict(brief=brief,correction_memory=prompt_memory(memory),experiment_phase=phase,reference_frames=frames,catalogue=catalogue_context(selected or catalogue),analysis=analysis,segmentation=[dict(object_key=s['object_key'],view_key=s['view_key'],source=s['source'],bbox_xyxy=s['selection']['bbox_xyxy'] if s.get('selection') else None,confidence=s['selection'].get('confidence') if s.get('selection') else None) for s in segments],previous_plan=previous,previous_metrics=prompt_metrics(metrics),candidate_frames=candidate_frames,
            rules=dict(maximum_objects=20,coordinates='Unity metres; Y up; root position is prefab pivot, NOT visual bounds centre. Euler rotation in degrees. Use intrinsic bounds_center_m to place bottoms on supports.',camera='estimated_views must be null when all reference frames have known calibration; otherwise one estimated pose per reference frame in identical order. Unity camera forward is +Z: X rotation +90 looks DOWN, -90 looks UP. Ensure objects are in front of camera.',light_units='directional intensity in lux; point/spot intensity in lumen. Real-time raster lighting; baked indirect reproduction is not qualified by this workflow.',preserve='Every analysed object and selected asset. Prefer original prefab colors (base_color_rgba=null). Use color override only with visual evidence.',depth='A SAM mask is not depth. Infer scale/placement from multiple views, camera calibration, catalogue dimensions and support relationships. State ambiguity.'))
        if BUILDING_POLICY in brief:context['rules']['room_finish']='Rectangular AtmosphericHouse rooms receive coherent WallIn_B companions and a connected Ceiling_3x3 ceiling at the interior wall tops. This derived assembly is built after floor contacts; do not add duplicate ceilings. The editor-only visualization helper is disabled like play mode.';context['rules']['architecture']='All structural modules must use '+BUILDING_ROOT+'. No extra primitive supports or walls. Preserve real openings. Fit adjacent module mesh bounds, including root pivot offsets, without closing doors/windows with solid walls. Window/door fittings and furniture may use other folders. Use intact variants. For the illustrated overhead reference, infer an overhead camera without horizontally mirroring the scene; use conservative lighting/exposure so surfaces remain visible.'
        context['calibrated_region_centres']=region_centres(analysis,frames,segments)
        context['allowed_asset_variants']=[dict(object_key=group['object_key'],asset_ids=[a['asset_id'] for a in group['candidates']]) for group in alternatives]
        context['rules']['asset_refinement']='The initial visual asset choice may be wrong. You may change an identified object ONLY to one of its explicit allowed_asset_variants when actual reference/candidate appearance supports it. In particular, opaque panels and transparent glass doors are different appearances. Explain a variant change in notes. Small differences in approximate bound projection error (<0.01) do not override visible materials or broken-plank pattern.'
        if phase=='image_refinement':context['rules']['single_image_fit']='Reference camera and metric dimensions are unknown. Jointly correct estimated_views, object placement/scale and illumination from the visible comparison. Match left/right and top/bottom explicitly; camera roll can mirror the apparent layout. Fix clipping or severe overexposure before finer placement: HDRP directional intensity is lux, exposure_ev is photographic EV (increase EV to darken). Keep inferred units and dimensions explicit estimates. Never describe an uncut cube wall as having an opening. Preserve evidence-backed identities; do not invent unseen rooms.'
        if matched_assets:context['rules']['asset_refinement']='Asset identity has been compared in separate object-detail requests with closeup reference images and native prefab renders. Preserve the selected asset_id for every object; do not undo these matches using wide composition images. This stage adjusts placement and lighting only.'
        context['rules']['world_alignment']='Use the image-derived calibrated world centres to anchor the entire layout before placing lights. Convert visible centres to prefab pivots using the rotated/scaled intrinsic catalogue centre. Do not reset an already calibrated layout to world origin. Place and aim lights relative to the inferred scene objects, not the origin. A vertical overhead spot mainly lights tops; reconstruct incidence direction from which surfaces are illuminated across the reference views.'
        context['rules']['contact_correction']='Unity resolves support contacts against actual candidate meshes and returns the applied plan plus per-object contact gaps. On later iterations preserve these corrected heights. Resolve any unresolved contacts by correcting X/Z, rotation or scale using reference images. Approximate visible centres are initial priors, never exact targets. Check chair facing direction and spacing in front/back/top views. A Unity plane is 10 by 10 metres at unit scale.'
        instruction='Reconstruct the visible reference faithfully as a static Unity scene using the allowed assets and explicit simple primitives. Infer placements, rotations, scales, lighting, exposure and flat gradient sky color from the actual images. Do not merely brighten the whole scene. Account for every identified object exactly once. You may add up to four clearly visible surrounding ground/platform/wall support surfaces missed by the object analysis, ONLY as cube or plane primitives with keys starting support_ and explain their visual evidence in notes; never invent extra decoration. If previous_plan exists, revise it using actual candidate images and measured differences; retain correct parts. Input images are first all reference frames, then all candidate frames in the metadata order. Return compact JSON; prefer rounded numeric coordinates to long explanations.'
        # All eight reference angles remain visible. Use four distributed
        # candidate angles for correction within the provider's twelve-image cap.
        supplied=candidate_frames or []
        remaining=12-len(frames)
        if len(supplied)>remaining:
            preferred=['work-front','work-back','work-back-right','work-top-front']
            indices=[i for key in preferred for i,frame in enumerate(supplied) if frame['key']==key][:remaining]
            for i in [round(i*(len(supplied)-1)/max(1,remaining-1)) for i in range(remaining)]+list(range(len(supplied))):
                if len(indices)<remaining and i not in indices:indices.append(i)
            supplied=[supplied[i] for i in indices]
        context['candidate_frames']=supplied
        images=[self.artifacts.read(f['artifact_hash']) for f in frames+supplied]
        if previous is not None and candidate_frames:
            from .reference_comparison import correction_boards
            images,pairs=correction_boards(self.artifacts,analysis,frames,candidate_frames,previous,catalogue,segments=segments,priority_view=(memory or {}).get('priority_view','work-top-front'),metrics=metrics)
            from .reference_inspection import append_inspection_boards
            images,pairs=append_inspection_boards(self.artifacts,images,pairs,inspection_pairs)
            context['paired_comparison_images']=pairs
            context['candidate_frames']=candidate_frames
            instruction='Correct the visible POSE and SPACING differences before adjusting lighting. The first two images (when priority_full_frame metadata exists) are the priority REFERENCE then CANDIDATE at full resolution. Subsequent images are paired boards: REFERENCE LEFT, CANDIDATE RIGHT at identical camera/crop coordinates. Overview boards show whole views; remaining boards compare individual objects, with up to two camera rows. All image indices/crops/calibration are in paired_comparison_images; reference_frames and candidate_frames are metadata only, NOT extra supplied images. Inspect every object board. A good contact does not imply correct X/Z position or yaw. Compare chair back/seat facing, rectangular bin orientation, bottle position, plate/bowl spacing, cloth coverage and table/wardrobe alignment wherever these objects exist. Translate image displacement to Unity axes using the supplied camera rotation. The previous plan is the actual applied candidate, including native surface contact corrections. Correct yaw, X/Z and scale when visibly wrong; do not freeze layout merely because contacts pass. Preserve matched asset identities and correct parts. Return the complete compact ModelReconstructionPlan JSON. Explain concrete pose changes and remaining ambiguity briefly in notes. Do not invent invisible objects. Lighting similarity alone is not sufficient.'
            context['rules']['world_alignment']='Region-centre triangulation is an uncertain initialization only. Correct the previous applied plan using the paired visual evidence; do not reimpose its initial coordinates.'
        if any(p.get('reference') is None for p in inspection_pairs):
            instruction+=' Candidate interior survey boards are CANDIDATE ONLY (four tiles), never reference pairs. Use the camera poses, actual prefab geometry/face normals and projected object bounds to diagnose missing inward faces, misplaced WallOut modules, openings and clipping. SAM wall regions provide uncertain 2D association, not depth or proof of a wall defect. Correct assembly and orientation rather than hiding errors by changing transparency, exposure or double-sided materials. Preserve intended door/window holes. Interior views cannot establish resemblance to an unseen reference interior.'
        if any(p.get('reference') is not None for p in inspection_pairs):instruction+=' Active editor closeup boards show targeted top/front/back observations of uncertain objects. Compare shape, facing, spacing and support in these paired images before proposing a correction. These are actual new camera observations, not enlarged crops. The editor render path can differ in lighting from GameView; use the full priority pair to decide lighting changes.'
        if memory:
            instruction+=' Priority view is '+memory['priority_view']+'. Compare it at full size before every correction. Use the memory of rejected experiments to avoid repeating them. The previous plan is the BEST retained state, not the last rejected state. Never drop previously visible ground/support surfaces. Every unresolved object needs measured evidence; no assumption of exact fidelity.'
            if phase=='appearance':instruction+=' This is an APPEARANCE experiment: preserve every object transform/scale/asset. Correct only lights, exposure, sky and fog. Compare illuminated faces and tops, shadow directions/softness and the surrounding floor in the priority view. Do not compensate a wrong light direction by globally brightening. Use the known object coordinates to position lights.'
            elif phase=='placement':instruction+=' This is a PLACEMENT experiment: change object positions/rotations/scales only; preserve lighting and materials. Address the residuals on the tabletop and bin in the overhead priority view, then check the remaining angles.'
        if appearance_experiment:
            fields={'light_geometry':'light position, orientation and spot cone only; preserve intensity, exposure, sky and fog','photometry':'light intensity/color and fixed exposure only; preserve light directions, sky and fog','atmosphere':'sky color and fog only; preserve all lights and exposure'}
            instruction+=' Frozen appearance sub-experiment: '+fields[appearance_experiment]+'. Preserve object identity, poses, scales and materials exactly.'
        response=self.provider.send(spark_request(instruction+'\nUntrusted observations:\n'+canonical(context),images,'ModelReconstructionPlan',dict(catalog_asset_ids=[a['asset_id'] for a in selected or catalogue])),'ModelReconstructionPlan')
        validate_plan(response['value'],analysis,frames,catalogue)
        if BUILDING_POLICY in brief:validate_building_mapping(response['value']['objects'],catalogue)
        if matched_assets:
            expected={o['key']:o['asset_id'] for o in analysis['objects']}
            if any(o['asset_id']!=expected[o['key']] for o in response['value']['objects'] if o['key'] in expected):raise AgentError('INVALID_MODEL_OUTPUT','Layout changed an asset selected from object details')
        return response
