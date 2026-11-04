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


def test_unknown_sam_call_preserves_other_concepts_without_retry():
    from hdrp_agent.house_vision import observe_concepts
    from hdrp_agent.domain import AgentError
    calls=[]
    def observe(concept):
        calls.append(concept)
        if concept=='lamp':raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Unknown')
        return 'mask-'+concept
    result=observe_concepts(['bed','lamp','books'],observe)
    assert sorted(calls)==['bed','books','lamp']
    assert [r['status'] for r in result]==['observed','unavailable','observed']
    assert result[2]['value']=='mask-books'
    assert 'value' not in result[1]


def test_stop_and_budget_failures_remain_fatal():
    import pytest
    from hdrp_agent.house_vision import observe_concepts
    from hdrp_agent.domain import AgentError
    for code in ['STOP_REQUESTED','BUDGET_EXCEEDED','RECOVERY_REQUIRED','INVALID_MODEL_OUTPUT']:
        def observe(_):raise AgentError(code,'Must stop')
        with pytest.raises(AgentError) as failure:observe_concepts(['bed'],observe)
        assert failure.value.code==code
