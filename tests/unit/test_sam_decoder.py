import pytest

from hdrp_agent.domain import AgentError
from hdrp_agent.providers.sam_decoder import decode

MASK="!!!!!'y80v-)c"


def test_empty_result_is_valid_and_local_mask_maps_to_source_bbox():
    assert decode('',10,10)==[]
    value=f'<0f>1<|box;x1=2;y1=1;x2=5;y2=4;w=10;h=10|><|mask;x=0;y=0;data=4,4,{MASK}|>\n'
    result=decode(value,10,10)
    assert result[0]['bbox_xyxy']==[.2,.1,.6,.5]
    assert result[0]['mask_size']==[4,4]
    assert result[0]['association']=='uncertain'


def test_invalid_partial_mask_and_allocation_bomb_are_refused():
    for value in ['<0f>1<|box;x1=2;', '<0f>1<|mask;x=0;y=0;data=99999999,99999999,!bad|>']:
        with pytest.raises(AgentError):decode(value,10,10)


def test_explicit_video_frame_order_is_used():
    def frame(i):return f'<{i}f>1<|box;x1=2;y1=1;x2=5;y2=4;w=10;h=10|><|mask;x=0;y=0;data=4,4,{MASK}|>\n'
    result=decode(frame(2)+frame(0)+frame(1),10,10,frame_count=3)
    assert [r['frame_index'] for r in result]==[0,1,2]


def test_reordered_source_dimensions_cannot_bypass_media_check():
    value=f'<0f>1<|box;x1=2;y1=1;x2=5;y2=4;h=999;w=999|><|mask;x=0;y=0;data=4,4,{MASK}|>\n'
    with pytest.raises(AgentError,match='source media'):decode(value,10,10)
