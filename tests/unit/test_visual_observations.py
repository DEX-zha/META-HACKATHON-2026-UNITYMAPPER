from hdrp_agent.visual_observations import export_observations


def test_public_observations_exclude_provider_and_private_data():
    job=dict(source_private={'secret':'private'},analysis_response={'reasoning':'secret','value':{'objects':[dict(key='bed',asset_id='asset',concept='bed',private='secret')]}},segments=[dict(object_key='bed',view_key='reference-0',concept='bed',source='sam-3.1',selection={'bbox_xyxy':[.1,.2,.5,.7],'mask_secret':'secret'})],frames=[dict(key='reference-0',model_size=[100,100],private='secret')])
    result=export_observations(job)
    assert 'secret' not in str(result)
    assert result['regions'][0]['resolved']
    assert result['regions'][0]['bbox_xyxy']==[.1,.2,.5,.7]
    assert export_observations({})==dict(objects=[],regions=[],frames=[])
