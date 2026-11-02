import io
import random
from PIL import Image
from hdrp_agent.house_media import inspection_batches


def test_large_observations_split_by_bytes_without_losing_views_or_resolution():
    im=Image.frombytes('RGB',(1280,720),random.Random(1).randbytes(1280*720*3))
    out=io.BytesIO();im.save(out,format='PNG')
    captures=[dict(artifact_hash=str(i)) for i in range(13)]
    batches=list(inspection_batches(captures,lambda _:out.getvalue()))
    assert len(batches)>2
    assert [c for batch,_ in batches for c in batch]==captures
    for batch,images in batches:
        assert len(images)==len(batch)<=12
        assert sum(4*((len(i)+2)//3) for i in images)<=2_000_000
        assert all(Image.open(io.BytesIO(i)).size==(1280,720) for i in images)
