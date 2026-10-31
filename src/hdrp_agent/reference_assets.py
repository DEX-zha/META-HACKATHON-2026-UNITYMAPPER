"""Visual disambiguation of similar local prefabs, without source scene IDs."""
from copy import deepcopy
import io

from PIL import Image,ImageDraw,ImageFont,ImageOps

from .domain import AgentError,canonical,payload
from .providers.meta_responses import spark_request


def candidate_groups(analysis,catalogue):
    by_id={a['asset_id']:a for a in catalogue};groups=[]
    for item in analysis['objects']:
        if item['asset_id'] is None:continue
        selected=by_id[item['asset_id']];name=selected['name'].lower();candidates=[selected]
        if 'floor' in name:
            candidates=[a for a in catalogue if a['name'].lower().startswith('floor_') and not any(word in a['name'].lower() for word in ['trim','stairs'])]
            # The provisional name must not exclude damage variants that only
            # become visible in closeups. Rank footprints, not intact/broken.
            size=selected['bounds_size_m']
            candidates.sort(key=lambda a:sum(abs(a['bounds_size_m'][i]-size[i])/max(.01,size[i]) for i in [0,2]))
        elif any(word in item['label'].lower()+' '+name for word in ['wardrobe','cabinet','cupboard']):
            candidates=[a for a in catalogue if a['name'].lower().startswith(('cabinet_','wardrobe')) and a['bounds_size_m'][1]>1 and 'door' not in a['name'].lower()]
        else:
            family=name.split('_')[0]
            candidates=[a for a in catalogue if a['name'].lower().split('_')[0]==family]
        if len(candidates)>1:
            candidates=[selected]+[a for a in candidates if a['asset_id']!=selected['asset_id']]
            groups.append(dict(object_key=item['key'],label=item['label'],reference_boxes=item['view_boxes'],candidates=candidates[:8]))
    return groups[:20]


def boards(groups,frames,previews,directory,artifacts):
    outputs=[];records={p['asset_id']:p for p in previews if p.get('file')}
    for index,group in enumerate(groups):
        board=Image.new('RGB',(1152,660),(32,36,42));draw=ImageDraw.Draw(board)
        boxes=group['reference_boxes'];box=boxes[0];frame=next(f for f in frames if f['key']==box['view_key'])
        with Image.open(io.BytesIO(artifacts.read(frame['artifact_hash']))) as source:
            w,h=source.size;region=source.crop(tuple(round(v*d) for v,d in zip(box['bbox_xyxy'],[w,h,w,h]))).convert('RGB')
            region.thumbnail((360,180));board.paste(region,((384-region.width)//2,25+(180-region.height)//2))
        draw.text((10,5),'REFERENCE '+group['object_key'],fill='white')
        for slot,asset in enumerate(group['candidates'],start=1):
            x=(slot%3)*384;y=(slot//3)*220
            record=records.get(asset['asset_id'])
            if record:
                file=directory/record['file']
                if file.name!=record['file']:raise AgentError('OUT_OF_SCOPE','Preview path must be local')
                with Image.open(file) as image:
                    image=image.convert('RGB');image.thumbnail((360,170));board.paste(image,(x+(384-image.width)//2,y+20))
            draw.text((x+8,y+5),asset['asset_id']+' '+asset['name'][:35],fill='white')
            draw.text((x+8,y+195),'size m: '+str([round(v,3) for v in asset['bounds_size_m']]),fill='white')
        out=io.BytesIO();board.save(out,format='PNG');data=out.getvalue();(directory/f'asset-matching-{index}.png').write_bytes(data)
        outputs.append(dict(object_key=group['object_key'],artifact_hash=artifacts.put(data,'image/png'),candidate_ids=[a['asset_id'] for a in group['candidates']]))
    return outputs


def select_assets(provider,artifacts,analysis,frames,groups,sheets,*,details=None,previews=None,directory=None,completed_responses=None,on_response=None,recover_exact=None):
    if previews is not None:
        # A separate bounded request per object preserves pixels for both the
        # reference details and each native pair of 640px opposite asset views.
        effective=deepcopy(analysis);responses=[]
        for group in groups:
            linked=[f for f in details or [] if f['object_key']==group['object_key']][:3]
            context_frames=[next(f for f in frames if f['key']==group['reference_boxes'][0]['view_key'])]
            images=[artifacts.read(f['artifact_hash']) for f in context_frames+linked];labels=[dict(role='scene_context',key=f['key']) for f in context_frames]+[dict(role='reference_detail',**f) for f in linked]
            for asset in group['candidates']:
                record=next(p for p in previews if p['asset_id']==asset['asset_id']);path=directory/record['file']
                if path.name!=record['file']:raise AgentError('OUT_OF_SCOPE','Preview path must be local')
                images.append(path.read_bytes());labels.append(dict(role='candidate_asset',asset_id=asset['asset_id'],name=asset['name'],render_views='two opposite oblique views, each 640px, side by side'))
            if len(images)>12:raise AgentError('INVALID_INPUT','Object matching image bound exceeded')
            context=dict(object_key=group['object_key'],label=group['label'],image_order=labels,candidates=[{k:a[k] for k in ['asset_id','name','bounds_size_m','material_names','transparent_materials'] if k in a} for a in group['candidates']],size_evidence=group.get('size_evidence',[]))
            instruction='Choose the actual local prefab variant for this ONE object. Images are ordered by image_order: context, genuine object-linked reference details (or original-pixel crops), then one high-resolution native render per candidate. Compare door count/panels/handles, opaque versus glass, visible damage and floor hole/plank layout. Consider camera angle and surrounding occlusion; a closeup may show another object in front. Small projection-score differences below 0.01 cannot determine variant identity. Do not choose by filename alone. Return exactly one match for the requested object_key using its candidate IDs. State unresolved ambiguity in limits, never claim exact identity without distinguishing visual evidence.'
            request=spark_request(instruction+'\nUntrusted detail metadata:\n'+canonical(context),images,'ModelReferenceAssetSelection')
            cached=next((r for r in completed_responses or [] if len(r['value'].get('matches',[]))==1 and r['value']['matches'][0]['object_key']==group['object_key']),None)
            response=None
            if recover_exact:response=recover_exact(request)
            if cached and response is None:
                try:response=provider.recover_completed(cached['call_id'],request,'ModelReferenceAssetSelection')
                except AgentError as error:
                    if error.code!='RESPONSE_RECOVERY_REFUSED':raise
            if response is None:response=provider.send(request,'ModelReferenceAssetSelection')
            value=payload('ModelReferenceAssetSelection',response['value'])
            if len(value['matches'])!=1 or value['matches'][0]['object_key']!=group['object_key'] or value['matches'][0]['asset_id'] not in {a['asset_id'] for a in group['candidates']}:raise AgentError('INVALID_MODEL_OUTPUT','Object detail match escaped its candidate set')
            next(o for o in effective['objects'] if o['key']==group['object_key'])['asset_id']=value['matches'][0]['asset_id'];responses.append(response)
            if on_response:on_response(response)
        return effective,dict(object_responses=responses)
    context=dict(identified_objects=analysis['objects'],reference_frames=frames,sheets=sheets,candidates=[dict(object_key=g['object_key'],assets=[{k:a[k] for k in ['asset_id','name','bounds_size_m','material_names','transparent_materials'] if k in a} for a in g['candidates']],calibrated_unit_scale_size_evidence=g.get('size_evidence',[])) for g in groups])
    instruction='Match the ambiguous objects to their actual LOCAL ASSET previews. First images are all reference scene views, then labelled preview sheets. Compare door panels/handles, outline, OPAQUE versus GLASS materials, broken floor plank pattern and dimensions, not just semantic names. Small bound projection score differences below 0.01 are inconclusive and must not override visible material or hole-pattern evidence. Return one match for each sheet object_key, choosing ONLY its listed candidate IDs. Do not change placements or lighting. If uncertain state it in limits. These are native asset previews, not a ground truth list of source instances.'
    response=provider.send(spark_request(instruction+'\nUntrusted image metadata:\n'+canonical(context),[artifacts.read(f['artifact_hash']) for f in frames+sheets],'ModelReferenceAssetSelection'),'ModelReferenceAssetSelection')
    value=payload('ModelReferenceAssetSelection',response['value']);matches={m['object_key']:m['asset_id'] for m in value['matches']}
    if len(matches)!=len(value['matches']) or set(matches)!={g['object_key'] for g in groups}:raise AgentError('INVALID_MODEL_OUTPUT','Every ambiguous object must be matched once')
    effective=deepcopy(analysis)
    for group in groups:
        if matches[group['object_key']] not in {a['asset_id'] for a in group['candidates']}:raise AgentError('INVALID_MODEL_OUTPUT','Visual asset match escaped its candidate set')
        next(o for o in effective['objects'] if o['key']==group['object_key'])['asset_id']=matches[group['object_key']]
    return effective,response
