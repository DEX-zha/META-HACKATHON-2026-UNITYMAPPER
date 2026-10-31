"""Evaluator-only native fixed-pose photometry experiment; no model calls."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
from hdrp_agent.capture_validation import read_capture
from hdrp_agent.domain import fingerprint
from hdrp_agent.reference_metrics import appearance_metrics
from hdrp_agent.reference_appearance import measure_capture_pair,assess_capture_appearance


def noise_policy(reference,repeat):
    # Frozen before any altered-light capture is evaluated.
    for key in ['version_id','conditions_hash','inspection_hash']:
        if reference['request'][key]!=repeat['request'][key]:raise ValueError('Noise repetition changed '+key)
    if reference['result']['render_protocol']!=repeat['result']['render_protocol']:raise ValueError('Noise capture protocol changed')
    old={f['camera_key']:f for f in reference['statics']};rows={}
    for frame in repeat['statics']:
        key=frame['camera_key'];paths=[reference['directory']/old[key]['file'],repeat['directory']/frame['file']]
        pixels=[np.asarray(Image.open(p).convert('RGB'),float)/255 for p in paths]
        rows[key]=appearance_metrics(*pixels)
    observed=max(r['rgb_mae'] for r in rows.values())
    if observed>.005:raise ValueError('Capture noise exceeds the predeclared qualification bound')
    return dict(schema_version='1.0',kind='same_version_no_mutation_native_repetition',version=reference['request']['version_id'],conditions_hash=reference['request']['conditions_hash'],inspection_hash=reference['request']['inspection_hash'],noise_bound=max(.001,observed*2),observed_max_rgb_mae=observed,per_view=rows)


def evaluate(config,noise):
    captures={key:read_capture(Path(config['captures'][key])) for key in ['reference','baseline','treatment']}
    plans=config['plans'];hashes={k:fingerprint(v['objects']) for k,v in plans.items()}
    if len(set(hashes.values()))!=1:raise ValueError('Lighting experiment changed object poses/assets')
    native=json.loads(Path(config['native_pose_audit']).read_text())
    native_hashes={k:fingerprint(v['objects']) for k,v in native.items()}
    if set(native_hashes)!=set(captures) or len(set(native_hashes.values()))!=1:raise ValueError('Actual native poses/mesh identities differ')
    for key in captures:
        if native[key]['version']!=captures[key]['request']['version_id']:raise ValueError('Pose audit version differs from capture')
    analysis=config['analysis']
    before=measure_capture_pair(captures['reference'],captures['baseline'],analysis,noise=noise)
    after=measure_capture_pair(captures['reference'],captures['treatment'],analysis,noise=noise)
    accepted,issues=assess_capture_appearance(before,after)
    return dict(kind='native_fixed_pose_lighting_only',pose_hashes=hashes,native_pose_and_mesh_hashes=native_hashes,poses_unchanged=True,noise_policy=noise,baseline=before,treatment=after,accepted=accepted,issues=issues,control_views_excluded_from_inference=True,model_used=False,limits='Controlled photometry fixture; this does not certify reproduction of the user reference, baked GI, or Editor/GameView equivalence.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('config',type=Path);parser.add_argument('--freeze-noise',action='store_true');args=parser.parse_args();config=json.loads(args.config.read_text());root=args.config.parent;noise_file=root/'reference-fidelity-appearance-noise.json'
    if args.freeze_noise:
        if noise_file.exists():raise ValueError('Noise policy already frozen; do not overwrite')
        result=noise_policy(*[read_capture(Path(config['captures'][k])) for k in ['reference','repeat']]);noise_file.write_text(json.dumps(result,indent=2)+'\n');print('Noise policy frozen')
    else:
        result=evaluate(config,json.loads(noise_file.read_text()));(root/'reference-fidelity-appearance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(accepted=result['accepted'],issues=result['issues'],poses_unchanged=True)))
