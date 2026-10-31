"""Decode terminal SAM grammar using the installed official parser."""
from importlib.metadata import version
import io
import re

from PIL import Image

from ..domain import AgentError

PARSER_VERSION=version('meta-sam-parser')
DECODER_VERSION='1.0'


def decode(text,width,height,*,frame_count=1):
    from meta_sam_parser import CompletedOutcome, image_segmentation_format, video_segmentation_format, decode_mask_to_raster
    if not isinstance(text,str) or len(text.encode())>10_000_000 or not 1<=width<=1280 or not 1<=height<=720 or not 1<=frame_count<=240:raise AgentError('INVALID_SEGMENTATION','Segmentation exceeds application bounds')
    # The library has structural checks but no quota ceiling. Bound allocations before parsing.
    allocations=0
    for h,w in re.findall(r'data=(\d+),(\d+),',text):
        w,h=int(w),int(h);allocations+=w*h
        if w>width or h>height or allocations>64_000_000:raise AgentError('INVALID_SEGMENTATION','Mask allocation exceeds bounds')
    for box in re.findall(r'<\|box;([^|]*)\|>',text):
        w=re.search(r'(?:^|;)w=(\d+)(?:;|$)',box)
        h=re.search(r'(?:^|;)h=(\d+)(?:;|$)',box)
        if w is None or h is None or int(w[1])!=width or int(h[1])!=height:raise AgentError('INVALID_SEGMENTATION','SAM coordinates do not match source media')
    parser=(image_segmentation_format() if frame_count==1 else video_segmentation_format()).create_parser()
    try:
        parser.push(text)
        result=parser.finish(CompletedOutcome()).result
        if any(d.severity=='error' for d in result.diagnostics):raise ValueError('Parser diagnostic error')
        regions=[];identities=set()
        for record in result.records:
            if record.kind=='text':raise ValueError('Unstructured segmentation text')
            if record.kind!='mask':continue
            frame=record.frame.frame_index if record.frame else 0
            identity=(frame,record.object_id)
            if identity in identities or not 0<=frame<frame_count:raise ValueError('Duplicate or invalid source frame')
            identities.add(identity)
            bounds=record.bounds
            if not 0<=bounds.left<bounds.right<=width or not 0<=bounds.top<bounds.bottom<=height:raise ValueError('Invalid mask bounds')
            raster=decode_mask_to_raster(record.mask)
            if len(raster)!=record.mask.width*record.mask.height:raise ValueError('Incomplete mask')
            image=Image.frombytes('L',(record.mask.width,record.mask.height),bytes(v*255 for v in raster));output=io.BytesIO();image.save(output,format='PNG')
            regions.append(dict(frame_index=frame,sam_object_id=record.object_id,bbox_xyxy=[bounds.left/width,bounds.top/height,bounds.right/width,bounds.bottom/height],mask_png=output.getvalue(),mask_size=[record.mask.width,record.mask.height],confidence=record.confidence,association='uncertain',parser_version=PARSER_VERSION))
        return sorted(regions,key=lambda r:(r['frame_index'],r['sam_object_id']))
    except (ValueError,TypeError,IndexError,OverflowError) as exc:raise AgentError('INVALID_SEGMENTATION','SAM output could not be decoded completely') from exc
