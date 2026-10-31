from hdrp_agent.providers.fake import FakeProvider


def test_offline_provider_uses_same_interface_without_repair_claim():
    fixture=dict(scene_version='version',inspected_capture_ids=[],observations=[],hypotheses=[],unsupported_limits=['offline fixture'])
    provider=FakeProvider([fixture])
    response=provider.send({'model':'muse-spark-1.3','input':[]},'ModelDiagnosis')
    assert response['provider_mode']=='offline'
    assert response['repair_validated'] is False
    assert response['usd']=='0'
    assert response['response_id'].startswith('offline-')
