"""Consolidate immutable diagnostic runs. Never used by reconstruction."""
import hashlib,json
from pathlib import Path
from html import escape
from hdrp_agent.budget import Budget
from hdrp_agent.store import Store

root=Path(__file__).resolve().parents[1];state=root/'.hdrp-agent';reports=state/'reports'
read=lambda p:json.loads(p.read_text())
campaign=read(reports/'reference-fidelity-campaign.json')
for variant in campaign['variants']:
    run_id=variant.get('run_id')
    if not run_id:continue
    report=read(state/'reconstructions'/run_id/'report.json');job=report['job']
    variant.update(state=job['state'],solver_version=job.get('fidelity_policy',{}).get('solver_version'),stop_reason=job.get('stop_reason'),settled_usd_micro=report['settled_usd_micro'],reserved_usd_micro=report['reserved_usd_micro'],fidelity_verified=False)
    path=reports/f'ground-truth-{run_id}.json'
    if job['state']=='completed' and path.exists():
        audit=read(path);variant.update(audit=str(path.relative_to(root)),strict_matched_pose_passed=audit['matched_objects_passed'],objects=audit['objects'],unqualified_objects=audit['unqualified_objects'],group_errors=audit.get('group_errors'))
    else:variant['source_audit']='not_admissible_or_not_executed'
source=root/'unity/HDRPValidation'/campaign['source_fixture_origin']
campaign['source_origin_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==campaign['source_origin_sha256']
budget=Budget(Store(state/'global.sqlite3')).state()
campaign['global_budget']={k:v for k,v in budget.items() if k.endswith('_usd_micro') or k=='currency'}
(reports/'reference-fidelity-campaign.json').write_text(json.dumps(campaign,indent=2)+'\n')
result=read(reports/'reference-fidelity-qualification.json');result.update(campaign=campaign,appearance=read(reports/'reference-fidelity-appearance.json') if (reports/'reference-fidelity-appearance.json').exists() else None,reserved_native_variants_completed=[v['id'] for v in campaign['variants'] if v['state']=='completed'],fidelity_verified=False)
result['appearance_qualified']=bool(result['appearance'] and result['appearance']['accepted'])
result['limits']=['Strict pose fidelity remains unverified; every object must meet 1 mm / 0.1 deg / 0.001 scale independently.','Diagnostic campaign used successive solver versions during implementation; it is not a uniform frozen-release benchmark.','Interrupted runs retain unknown reservations and are not silently retried.','Photometry fixture qualification does not certify user-scene lighting or baked indirect illumination.','Annotated drawings remain deferred (T107).']
(reports/'reference-fidelity-qualification.json').write_text(json.dumps(result,indent=2)+'\n')
html='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Fidelity qualification</title><style>body{font:16px system-ui;background:#131820;color:#edf2fa;max-width:1100px;margin:36px auto}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #394452;text-align:left}a{color:#9acaff}</style><h1>Strict fidelity not validated</h1>'''
a=result['anchor'];html+=f'<p>Demo anchoring: {a["baseline_median_y_m"]*100:.2f} cm → {a["median_y_m"]*100:.2f} cm ; JF1 {"validated" if a["passed"] else "not validated"}.</p><table><tr><th>Demo object</th><th>Position (cm)</th><th>Rotation (°)</th><th>Scale</th><th>Strict threshold</th></tr>'
for o in result['layout']['objects']:html+=f'<tr><td>{escape(o["key"])}</td><td>{o["position_error_m"]*100:.2f}</td><td>{o["rotation_error_deg"]:.2f}</td><td>{o["max_scale_error"]:.4f}</td><td>{"validated" if o["within_pose_tolerance"] else "outside threshold"}</td></tr>'
html+='</table><p>Final fidelity-5 pass: four candidates evaluated in one invocation using the previously retained analysis and best candidate. No further admissible improvement; the initial candidate is restored and audited. Stopped for insufficient observations, without a convergence verdict.</p><h2>Diagnostic variants</h2><p>Successive solver versions; failures retained. Detailed audits are available in the JSON.</p><table><tr><th>Case</th><th>State</th><th>Solver</th><th>Stop</th><th>Report</th></tr>'
for v in campaign['variants']:html+=f'<tr><td>{escape(v["id"])}</td><td>{escape(v["state"])}</td><td>{escape(v.get("solver_version") or "inconnu")}</td><td>{escape(v.get("stop_reason") or v.get("reason") or "—")}</td><td><a href="../reconstructions/{v["run_id"]}/comparison.html">Captures</a></td></tr>'
b=campaign['global_budget'];html+=f'</table><p>Global budget: {b["settled_usd_micro"]/1e6:.6f} USD settled ; {b["unknown_reserved_usd_micro"]/1e6:.6f} USD retained for unknown costs ; {b["available_usd_micro"]/1e6:.6f} USD available.</p>'
html+='<p>Controlled appearance: '+('validated on a fixture with fixed poses' if result['appearance_qualified'] else 'not validated')+'. This does not establish photometric qualification of the user scene.</p>'
html+='<ul>'+''.join('<li>'+escape(s)+'</li>' for s in result['limits'])+'</ul><p><a href="reference-fidelity-qualification.json">Full evidence</a> · <a href="../reconstructions/'+result['run_id']+'/comparison.html">Retained demo</a></p></html>'
(reports/'reference-fidelity-qualification.html').write_text(html)
print(json.dumps(dict(source_unchanged=campaign['source_origin_unchanged'],variants=[dict(id=v['id'],state=v['state']) for v in campaign['variants']],budget=campaign['global_budget']),indent=2))
