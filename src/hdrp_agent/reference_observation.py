"""One bounded evidence acquisition when geometry lacks reliable observations."""
from copy import deepcopy
from contextlib import closing
from .domain import AgentError,canonical,payload,fingerprint
from .providers.meta_responses import spark_request
from .segmentation import Segmenter,iou


def acquire_observations(provider,artifacts,analysis,frames,details,segments,geometry,guard,checkpoint=None):
    missing=sorted((k for k,v in geometry['per_object'].items() if not v['covered']),key=lambda k:-sum(o.get('support_key')==k for o in analysis['objects']))[:3]
    if not missing:return segments,dict(requested=False,reason='coverage_available')
    by_object={o['key']:o for o in analysis['objects']}
    chosen=[f for f in frames if f.get('calibration') and not f['key'].startswith('control-')][:8]
    for key in missing:
        detail=next((f for f in details if f.get('object_key')==key and f.get('angle')=='front'),None)
        if detail and len(chosen)<12:chosen.append(detail)
    if not chosen:return segments,dict(requested=False,reason='no_calibrated_source_observations')
    known={(s['object_key'],s['view_key'],s['concept']) for s in segments};by_view={f['key']:f for f in chosen}
    context=dict(objects=[dict(key=k,label=by_object[k]['label'],missing_reasons=geometry['per_object'][k]['missing_reasons']) for k in missing],frames=[{k:f.get(k) for k in ['key','object_key','angle','calibration','artifact_hash']} for f in chosen],previous_requests=[dict(object_key=k,view_key=v,concept=c) for k,v,c in sorted(known) if k in missing])
    instruction='Choose additional visual observations for the listed objects only. Their SAM masks are missing, unreliable, too small or do not provide independent views. Inspect the supplied images in metadata order. Request at most three source views per object and at most three objects. Use a short, concrete English noun phrase identifying the visible object for SAM. Prefer clearly visible large regions and separated camera angles; never invent hidden geometry. An identical previous (object, view, concept) request cannot be replayed. A better concept or previously unused visible view is a new experiment. Return an empty requests list if no reliable new evidence is available. No control images or ground-truth poses are supplied.'
    guard();request=spark_request(instruction+'\nUntrusted image metadata:\n'+canonical(context),[artifacts.read(f['artifact_hash']) for f in chosen],'ModelReferenceObservationPlan')
    with closing(artifacts.store.connect()) as connection:prior=connection.execute('SELECT id,status FROM calls WHERE payload_hash=? ORDER BY created_at DESC LIMIT 1',(fingerprint(request),)).fetchone()
    if prior:
        if prior['status']!='settled':raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Observation request already admitted; no automatic retransmission')
        response=provider.recover_completed(prior['id'],request,'ModelReferenceObservationPlan')
    else:response=provider.send(request,'ModelReferenceObservationPlan')
    value=payload('ModelReferenceObservationPlan',response['value'])
    output=deepcopy(segments);segmenter=Segmenter(provider,artifacts);attempted=[]
    if checkpoint:checkpoint(output,dict(requested=True,model_response=response,attempts=attempted,source_transforms_used=False))
    for request in value['requests']:
        key=request['object_key'];concept=request['concept']
        if key not in missing or any(c in concept for c in [',',';','\n','<','>','+']):raise AgentError('INVALID_MODEL_OUTPUT','Observation request outside the listed uncertain objects')
        for view in request['view_keys']:
            if view not in by_view or by_view[view].get('object_key') not in {None,key}:raise AgentError('INVALID_MODEL_OUTPUT','Observation image not supplied for this object')
            if (key,view,concept) in known:continue
            known.add((key,view,concept));guard();frame=by_view[view]
            segmentation=segmenter.segment(dict(frame,role='work'),concept)
            box=next((b['bbox_xyxy'] for b in by_object[key]['view_boxes'] if b['view_key']==view),None)
            regions=segmentation.get('regions',[]);ranked=sorted([r for r in regions if box is None or iou(box,r['bbox_xyxy'])>.1],key=lambda r:iou(box,r['bbox_xyxy']) if box else r.get('confidence',0),reverse=True)
            selected=ranked[0] if ranked else None
            if box is None and len(ranked)>1 and abs(ranked[0].get('confidence',0)-ranked[1].get('confidence',0))<.15:selected=None
            item=dict(object_key=key,view_key=view,concept=concept,selection=selected,source=segmentation['source'],association='additional_visual_observation',response_id=segmentation.get('response_id'))
            old=next((s for s in output if s['object_key']==key and s['view_key']==view),None)
            if old is None:output.append(item)
            elif selected and selected.get('confidence',0)>(old.get('selection') or {}).get('confidence',0):output[output.index(old)]=item
            attempted.append(item)
            if checkpoint:checkpoint(output,dict(requested=True,model_response=response,attempts=attempted,source_transforms_used=False))
    return output,dict(requested=True,model_response=response,attempts=attempted,source_transforms_used=False)
