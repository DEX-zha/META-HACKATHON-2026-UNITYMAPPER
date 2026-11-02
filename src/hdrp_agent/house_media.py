"""Transport-sized inspection batches; every full-resolution capture is retained."""
import io
from PIL import Image


def inspection_batches(captures, read, *, max_image_bytes=2_000_000):
    batch=[];images=[];size=0
    for capture in captures:
        with Image.open(io.BytesIO(read(capture['artifact_hash']))) as source:
            out=io.BytesIO();source.convert('RGB').save(out,format='JPEG',quality=88,subsampling=2)
        data=out.getvalue();encoded=4*((len(data)+2)//3)
        if batch and (len(batch)==12 or size+encoded>max_image_bytes):
            yield batch,images
            batch=[];images=[];size=0
        batch.append(capture);images.append(data);size+=encoded
    if batch:yield batch,images
