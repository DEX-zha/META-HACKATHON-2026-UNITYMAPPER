"""Lossy viewing copies retain the original, ordered PNG evidence."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

from .config import contained
from .domain import AgentError


def encode_clip(directory, records, fps=24):
    directory=Path(directory).resolve()
    if fps!=24 or not 1<=len(records)<=240:raise AgentError('INVALID_MEDIA','Bounded 24 fps clip required',422)
    records=sorted(records,key=lambda r:r['frame_index'])
    if [r['frame_index'] for r in records]!=list(range(len(records))):raise AgentError('MISSING_FRAME','Frames are missing or duplicated',422)
    output=directory/'clip.mp4'
    with tempfile.TemporaryDirectory(dir=directory,prefix='.encoding-') as temp:
        for index,record in enumerate(records):
            source=contained(directory,directory/record['file'])
            if not source.is_file():raise AgentError('MISSING_FRAME','Original PNG is missing',422)
            with Image.open(source) as image:
                if image.size!=(1280,720) or image.format!='PNG':raise AgentError('INVALID_MEDIA','Expected original 1280x720 PNG',422)
                image.verify()
            shutil.copyfile(source,Path(temp)/f'frame-{index:04d}.png')
        target=Path(temp)/'clip.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(fps),'-i',str(Path(temp)/'frame-%04d.png'),'-frames:v',str(len(records)),'-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(target)],check=True,timeout=120,capture_output=True)
        details=subprocess.run(['ffprobe','-v','error','-count_frames','-show_entries','stream=codec_name,nb_read_frames,r_frame_rate,duration,codec_type','-of','json',str(target)],check=True,timeout=30,capture_output=True)
        streams=json.loads(details.stdout)['streams']
        if len(streams)!=1 or streams[0]['codec_name']!='h264' or int(streams[0]['nb_read_frames'])!=len(records) or abs(float(streams[0]['duration'])-len(records)/fps)>1/fps:raise AgentError('INVALID_MEDIA','Encoded stream failed frame/duration verification')
        if target.stat().st_size>20_000_000:raise AgentError('PAYLOAD_TOO_LARGE','Derived MP4 exceeds 20 MB',413)
        target.replace(output)
    return dict(file=output.name,codec='h264',fps=fps,frame_count=len(records),duration_seconds=len(records)/fps,audio=False,original_frame_files=[r['file'] for r in records])


def crop(image_path,bbox,output_path):
    if len(bbox)!=4 or not all(type(v) in (float,int) and 0<=v<=1 for v in bbox) or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:raise AgentError('INVALID_REGION','Normalized nonempty bbox required',422)
    with Image.open(image_path) as image:
        width,height=image.size
        box=(int(bbox[0]*width),int(bbox[1]*height),max(1,int(bbox[2]*width)),max(1,int(bbox[3]*height)))
        if box[0]>=box[2] or box[1]>=box[3]:raise AgentError('INVALID_REGION','Crop is smaller than one pixel',422)
        image.crop(box).save(output_path)
    return dict(source_size=[width,height],pixel_bbox=list(box),normalized_bbox=bbox)
