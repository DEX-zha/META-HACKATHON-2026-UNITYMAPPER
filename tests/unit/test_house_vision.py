import io
from PIL import Image
from hdrp_agent.house_vision import overlay,concepts


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def test_overlay_uses_mask_pixels_not_bounding_rectangle():
    source=png(Image.new('RGB',(10,10),'white'));mask=Image.new('L',(4,4));mask.putpixel((1,1),255)
    result=Image.open(io.BytesIO(overlay(source,[dict(bbox_xyxy=[.2,.1,.6,.5],mask_artifact_hash='m')],lambda _:png(mask))))
    assert result.getpixel((3,2))!=(255,255,255)
    assert result.getpixel((2,1))==(255,255,255)
    assert result.getpixel((6,5))==(255,255,255)


def test_queries_include_small_props_not_just_furniture():
    assets={name:dict(prefab_guid=name) for name in ['Bed_king','Book_set_A','Book_set_B','Carpet_C','Curtain_A']}
    assert concepts([dict(prefab_guid=n) for n in assets],assets)==['bed','books','rug','curtain']
