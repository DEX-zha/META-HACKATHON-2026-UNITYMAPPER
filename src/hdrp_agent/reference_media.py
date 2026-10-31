"""Local reference ingestion; timestamps and original files remain auditable."""
import hashlib
import io
import json
from pathlib import Path
import subprocess

from PIL import Image,ImageOps

from .config import contained
from .domain import AgentError


def bounded_image(data):
    with Image.open(io.BytesIO(data)) as original:
        if original.width*original.height>40_000_000:raise AgentError('INVALID_MEDIA','Reference image is too large',422)
        image=ImageOps.exif_transpose(original).convert('RGB');original_size=list(image.size)
        image.thumbnail((1280,720),Image.Resampling.LANCZOS)
        output=io.BytesIO();image.save(output,format='PNG')
    return output.getvalue(),dict(original_size=original_size,model_size=list(image.size),resize='aspect_preserved_no_crop')


def ingest(bundle,directory,artifacts):
    directory=Path(directory).resolve();frames=[]
    if bundle['kind']=='recorded':
        from .capture_validation import read_capture
        from .media import encode_clip
        capture_root=contained(directory.parents[2]/'unity/HDRPValidation/.hdrp-agent/captures',Path(bundle['capture_directory']))
        checked=read_capture(capture_root)
        expected=bundle['inspection']
        for index,view in enumerate(expected['work_views']):
            record=next(frame for frame in checked['statics'] if frame['camera_key']==view['key'])
            raw=(capture_root/record['file']).read_bytes();data,transform=bounded_image(raw)
            frames.append(dict(key=view['key'],artifact_hash=artifacts.put(data,'image/png'),original_artifact_hash=artifacts.put(raw,'image/png'),original_sha256=hashlib.sha256(raw).hexdigest(),timestamp_seconds=None,calibration=view,**transform))
        if checked['clip']:
            clip=encode_clip(capture_root,checked['clip']);bundle['recorded_video']=dict(path=str(capture_root/clip['file']),**clip)
    else:
        sources=bundle['media_files']
        if not 1<=len(sources)<=3:raise AgentError('INVALID_MEDIA','Use one video or up to three reference images',422)
        for source in sources:
            path=contained(directory,directory/source)
            if path.stat().st_size>200_000_000:raise AgentError('INVALID_MEDIA','Reference input exceeds 200 MB',422)
            if path.suffix.lower() in {'.mp4','.mov','.m4v','.webm'}:
                if len(sources)!=1:raise AgentError('INVALID_MEDIA','A video must be imported alone',422)
                probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,check=True,timeout=30)
                duration=float(json.loads(probe.stdout)['format']['duration'])
                if not 0<duration<=120:raise AgentError('INVALID_MEDIA','Use a video of at most 120 seconds',422)
                for index,fraction in enumerate([.1,.5,.9]):
                    time=duration*fraction
                    result=subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True,timeout=60)
                    data,transform=bounded_image(result.stdout)
                    frames.append(dict(key='reference-'+str(index),artifact_hash=artifacts.put(data,'image/png'),original_artifact_hash=artifacts.put(result.stdout,'image/png'),timestamp_seconds=time,original_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),calibration=None,**transform))
            else:
                raw=path.read_bytes();data,transform=bounded_image(raw)
                frames.append(dict(key='reference-'+str(len(frames)),artifact_hash=artifacts.put(data,'image/png'),original_artifact_hash=artifacts.put(raw,'image/'+('jpeg' if path.suffix.lower() in {'.jpg','.jpeg'} else 'png')),timestamp_seconds=None,original_sha256=hashlib.sha256(raw).hexdigest(),calibration=None,**transform))
    return frames
