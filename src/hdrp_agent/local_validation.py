"""Independent verification of Unity J0 evidence; performs no inference."""
import json
from pathlib import Path

from .capture_validation import read_capture,repeatability
from .domain import AgentError
from .media import encode_clip


def verify(settings):
    path=settings.state/'reports/j0-local-pipeline.json'
    report=json.loads(path.read_text())
    if len(report.get('captures',[]))!=3 or any(p is None for p in report['captures']):raise AgentError('CAPABILITY_MISSING','Three completed Unity capture runs are required')
    captures=[read_capture(p) for p in report['captures']]
    report['repeatability']=repeatability(captures[0],captures[1])
    report['restored_repeatability']=repeatability(captures[0],captures[2])
    report['clip']=encode_clip(captures[0]['directory'],captures[0]['clip'])
    bake_path=settings.workspace/'unity/HDRPValidation/.hdrp-agent/bakes'/(report['bake_job_id']+'.json')
    bake=json.loads(bake_path.read_text());phases=[event['phase'] for event in bake['events']]
    report['gpu_bake_verified']=bool(bake['status']=='complete' and bake['resources_verified'] and 'bakeStarted' in phases and 'bakeCompleted' in phases and 'bakeCancelled' not in phases and bake['after_version']==captures[0]['request']['version_id'])
    report['capture_verified']=report['repeatability']['stable'] and report['restored_repeatability']['stable']
    report['restored_files_verified']=bool(report['restored_files_verified'] and report['baseline_manifest_hash']==captures[0]['request']['scene_manifest_hash']==captures[2]['request']['scene_manifest_hash'])
    report['status']='verified' if report['capture_verified'] and report['gpu_bake_verified'] and report['restored_files_verified'] else 'inconclusive'
    if not report['capture_verified'] and captures[0]['request']['plan']['warmup_frames']<120:report['status']='needs_maximum_warmup_retry'
    report['provider_requests_sent']=0
    report['note']='Measured graphical PlayMode evidence; no model inference or autonomous correction is validated.'
    hardware=settings.state/'reports/unity-hardware-verification.json'
    if hardware.exists():report['hardware_evidence']=str(hardware.relative_to(settings.workspace))
    path.write_text(json.dumps(report,indent=2))
    return {key:report[key] for key in ['status','capture_verified','gpu_bake_verified','restored_files_verified','provider_requests_sent']}
