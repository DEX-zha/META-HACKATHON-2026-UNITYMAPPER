"""Post-run evaluator only. Reconstruction must never import this script."""
import argparse
import json
import re
from pathlib import Path
from statistics import median
from html import escape
from hdrp_agent.reference_schedule import assess


def evaluate(workspace,run_id,baseline_id):
    if not all(re.fullmatch('[a-f0-9]{32}',x) for x in [run_id,baseline_id]):raise ValueError('Invalid run id')
    root=workspace/'.hdrp-agent';reports=root/'reports'
    read=lambda path:json.loads(path.read_text())
    report=read(root/'reconstructions'/run_id/'report.json');job=report['job']
    if job['state']!='completed':raise ValueError('Only completed runs may be evaluated')
    audit=read(reports/f'ground-truth-{run_id}.json');baseline_audit=read(reports/f'ground-truth-{baseline_id}.json')
    if audit['source_sha256']!=baseline_audit['source_sha256']:raise ValueError('Audit references differ')
    best=next(a for a in job['attempts'] if a['ordinal']==job['retained_ordinal']);initial=job['attempts'][0]
    initial_bias=median(o['position_delta_m'][1] for o in baseline_audit['objects']);bias=median(o['position_delta_m'][1] for o in audit['objects']);reduction=1-abs(bias)/abs(initial_bias) if initial_bias else None
    acceptable,regressions=assess(best,initial,job['fidelity_policy']) if best!=initial else (True,[])
    anchor=dict(run_id=run_id,baseline_run_id=baseline_id,baseline_median_y_m=initial_bias,median_y_m=bias,bias_reduction=reduction,contacts_passed=best['metrics']['contacts']['passed'],local_geometry_regressions=regressions,passed=abs(bias)<.01 and reduction is not None and reduction>=.8 and acceptable and best['metrics']['contacts']['passed'],source_transforms_used_for_inference=False)
    layout=dict(run_id=run_id,objects=audit['objects'],group_errors=audit.get('group_errors'),unqualified_objects=audit['unqualified_objects'],strict_matched_pose_passed=audit['matched_objects_passed'],tolerances=audit['tolerances'])
    autonomy=dict(run_id=run_id,single_invocation=True,decisions=job.get('decisions'),retained_ordinal=best['ordinal'],retained_version=best['native']['version'],scene=audit['candidate_scene'],restore_verified_by_native_audit=True,stop_reason=job['stop_reason'],attempts=[dict(ordinal=a['ordinal'],phase=a['phase'],retained=a['retained'],geometry_score=a['metrics']['geometry']['score'],coverage_complete=a['metrics']['geometry']['coverage_complete'],regressions=a['regressions']) for a in job['attempts']],settled_usd_micro=report['settled_usd_micro'],reserved_usd_micro=report['reserved_usd_micro'],fidelity_verified=False)
    result=dict(run_id=run_id,anchor=anchor,layout=layout,autonomy=autonomy,appearance_qualified=False,reserved_native_variants_completed=[],fidelity_verified=False,limits=['Only the demo has completed native qualification here.','Strict pose and photometric qualification remain independent of silhouette improvement.','Partial or missing observations remain unqualified.','Annotated drawings are deferred (T107).'])
    for name,value in [('anchor',anchor),('layout',layout),('autonomy',autonomy),('qualification',result)]:
        (reports/f'reference-fidelity-{name}.json').write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    previous={o['key']:o for o in baseline_audit['objects']}
    html='<!doctype html><html lang="fr"><meta charset="utf-8"><title>Qualification de fidélité</title><style>body{font:16px system-ui;background:#131820;color:#edf2fa;max-width:1100px;margin:36px auto}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #394452;text-align:left}a{color:#9acaff}</style><h1>Qualification de la reproduction</h1>'
    html+=f'<p>Jalon ancrage : {"validé" if anchor["passed"] else "non validé"}. Biais vertical médian : {initial_bias*100:.2f} cm → {bias*100:.2f} cm.</p><p>Fidélité exacte : non validée. Les images et les poses sont évaluées séparément.</p><table><tr><th>Objet</th><th>Position avant (cm)</th><th>Position après (cm)</th><th>Rotation (°)</th><th>Échelle</th><th>Seuil strict</th></tr>'
    for row in audit['objects']:
        before=previous.get(row['key'],{})
        html+=f'<tr><td>{escape(row["key"])}</td><td>{before.get("position_error_m",0)*100:.2f}</td><td>{row["position_error_m"]*100:.2f}</td><td>{row["rotation_error_deg"]:.2f}</td><td>{row["max_scale_error"]:.4f}</td><td>{"validé" if row["within_pose_tolerance"] else "hors seuil"}</td></tr>'
    html+=f'</table><p>Arrêt : {escape(job["stop_reason"])}. Coût du run : {report["settled_usd_micro"]/1e6:.6f} USD.</p><p><a href="../reconstructions/{run_id}/comparison.html">Comparaison des rendus natifs</a> · <a href="reference-fidelity-qualification.json">Mesures complètes</a></p><p>Campagne des trois variantes réservées et qualification photométrique encore ouvertes.</p></html>'
    (reports/'reference-fidelity-qualification.html').write_text(html)
    return anchor


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--baseline',default='de8919eabdab49d78d38c0ec81384b65');args=parser.parse_args()
    print(json.dumps(evaluate(Path(__file__).resolve().parents[1],args.run,args.baseline),indent=2))
