"""Compare numerical visibility with the native synthetic fixture; evaluator only."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from hdrp_agent.reference_metrics import SceneRaster,mask_metrics

root=Path(__file__).resolve().parents[1]/'.hdrp-agent'/'reports'
fixture=json.loads((root/'reference-fidelity-raster-fixture.json').read_text())
with Image.open(root/'reference-fidelity-raster-fixture.png') as image:rgb=np.asarray(image.convert('RGB'),float)/255
observed=(rgb[:,:,0]>.2)&(rgb[:,:,0]>2*rgb[:,:,1])&(rgb[:,:,0]>2*rgb[:,:,2])
identity,status=SceneRaster([]).render(fixture['plan'],fixture['view'],(rgb.shape[1],rgb.shape[0]))
metrics=mask_metrics(observed,identity==0)
result=dict(kind='native_cube_raster_qualification',metrics=metrics,render_status=status,passed=metrics['visible_iou'] is not None and metrics['visible_iou']>=.98 and metrics['contour_error_px']<=1.,limits='One opaque synthetic cube in the Editor HDRP probe. Transparent, alpha-cutout, skinned and near-clipped meshes remain unqualified.')
(root/'reference-fidelity-raster.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
