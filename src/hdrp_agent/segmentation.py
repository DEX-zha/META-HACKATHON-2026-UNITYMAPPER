from contextlib import closing
import hashlib
import json
import io
from PIL import Image

from .domain import AgentError, canonical, fingerprint
from .providers.meta_responses import sam_request
from .providers.sam_decoder import decode, PARSER_VERSION, DECODER_VERSION


def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));intersection=x*y
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0


class Segmenter:
    def __init__(self,provider,artifacts):self.provider,self.artifacts=provider,artifacts
    def segment(self,frame,concept,engine_regions=(),*,allow_transmission=True):
        if frame.get('role')!='work':raise AgentError('CONTROL_LEAK','Planner segmentation accepts work views only',422)
        data=self.artifacts.read(frame['artifact_hash'])
        key=fingerprint(dict(media_sha256=hashlib.sha256(data).hexdigest(),concept=concept,model='sam-3.1',parser=PARSER_VERSION,decoder=DECODER_VERSION,preprocessing='original-bounded-png'))
        cached=self.artifacts.cache_get(key)
        if cached:return json.loads(self.artifacts.read(cached))
        if not allow_transmission:return dict(source='not_requested',regions=list(engine_regions),reason='No completed cached SAM result; no provider retry',association='uncertain')
        request=sam_request(concept,data)
        with closing(self.artifacts.store.connect()) as c:
            prior=c.execute("SELECT id,status FROM calls WHERE model='sam-3.1' AND payload_hash=? AND status IN ('settled','sent','unknown') LIMIT 1",(fingerprint(request),)).fetchone()
        if prior:return dict(source='not_requested',regions=list(engine_regions),reason='A previously transmitted identical SAM request has no reusable mask; no replay',prior_call_id=prior['id'],association='uncertain')
        response=self.provider.send(request)
        try:
            with Image.open(io.BytesIO(data)) as image:width,height=image.size
            regions=decode(response['value'],width,height)
        except AgentError:
            return dict(source='engine_fallback',regions=list(engine_regions),reason='SAM output invalid; no causal diagnosis inferred',response_id=response['response_id'],association='uncertain')
        for region in regions:
            png=region.pop('mask_png');region['mask_hash']=self.artifacts.put(png,'image/png',metadata={'source_media':frame['artifact_hash'],'sam_response_id':response['response_id']})
            region['candidates']=[dict(target_id=r['target_id'],bbox_iou=iou(region['bbox_xyxy'],r['bbox_xyxy']),evidence='Projected bounds overlap; occlusion and correspondence unverified') for r in engine_regions if iou(region['bbox_xyxy'],r['bbox_xyxy'])>.1]
        result=dict(source='sam-3.1',response_id=response['response_id'],regions=regions,association='uncertain',causal_diagnosis=False)
        artifact=self.artifacts.put(canonical(result).encode(),'application/json');self.artifacts.cache_put(key,artifact)
        return result
