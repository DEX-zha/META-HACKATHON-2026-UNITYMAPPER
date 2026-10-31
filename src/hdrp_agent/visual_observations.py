"""Public visual evidence only; provider envelopes and private source data stay private."""
def export_observations(job):
    analysis=job.get('effective_analysis') or job.get('analysis_response',{}).get('value',{})
    objects=[]
    for obj in analysis.get('objects',[]):
        objects.append({k:obj[k] for k in ('key','concept','asset_id','view_boxes') if k in obj})
    regions=[]
    for segment in job.get('segments',[]):
        selection=segment.get('selection') or {}
        regions.append(dict(object_key=segment.get('object_key'),view_key=segment.get('view_key'),concept=segment.get('concept'),bbox_xyxy=selection.get('bbox_xyxy'),source=segment.get('source'),resolved=bool(selection)))
    return dict(objects=objects,regions=regions,frames=[dict(key=f['key'],size=f.get('model_size')) for f in job.get('frames',[])])
