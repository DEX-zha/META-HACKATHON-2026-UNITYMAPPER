"""Evidence-linked SAM concepts and actual raster-mask overlays."""
import io
from PIL import Image


def concepts(instances, assets):
    by_guid={a['prefab_guid']:name for name,a in assets.items()}
    families={
        'bed':'bed', 'wardrobe':'wardrobe', 'bookshelf':'bookshelf', 'book':'books',
        'desk':'desk', 'workdesk':'desk', 'chair':'chair', 'sofa':'sofa', 'table':'table',
        'dresser':'chest of drawers', 'plant':'plant', 'lamp':'lamp', 'curtain':'curtain',
        'carpet':'rug', 'rug':'rug', 'papers':'papers', 'computer':'computer',
        'tv':'television', 'pillow':'pillow', 'box':'storage box', 'basket':'basket',
    }
    found=[]
    for item in instances:
        name=by_guid.get(item['prefab_guid'],item.get('role','furniture')).split('/')[-1].lower()
        concept=next((v for k,v in families.items() if k in name),name.replace('_',' '))
        if concept not in found:found.append(concept)
    return found or ['furniture']


def overlay(source, regions, read):
    """Bounds locate the local raster; they are never painted as filled boxes."""
    image=Image.open(io.BytesIO(source)).convert('RGBA')
    for index,region in enumerate(regions):
        x0,y0,x1,y1=region['bbox_xyxy'];w,h=image.size
        left,top,right,bottom=round(x0*w),round(y0*h),round(x1*w),round(y1*h)
        if right<=left or bottom<=top:continue
        mask=Image.open(io.BytesIO(read(region['mask_artifact_hash']))).convert('L')
        mask=mask.resize((right-left,bottom-top),Image.Resampling.NEAREST)
        tint=Image.new('RGBA',mask.size,[(8,102,255),(255,157,0),(30,190,110),(195,75,220)][index%4]+(0,))
        tint.putalpha(mask.point(lambda p:round(p*.38)))
        image.alpha_composite(tint,(left,top))
    out=io.BytesIO();image.convert('RGB').save(out,format='PNG');return out.getvalue()
