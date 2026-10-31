"""Operator-only immutable reports. Never fed back into planner prompts."""
from contextlib import closing
from pathlib import Path
import json

from .domain import AgentError,canonical,payload
from .config import contained
from .store import utc_now


def build(store,artifacts,session_id):
    session=store.get('sessions',session_id)
    with closing(store.connect()) as c:
        run=c.execute('SELECT body FROM session_runs WHERE session_id=?',(session_id,)).fetchone()
        events=[dict(id=r['id'],kind=r['kind'],body=json.loads(r['body']),created_at=r['created_at']) for r in c.execute('SELECT * FROM events WHERE subject=? ORDER BY id',(session_id,))]
        commands=[dict(id=r['id'],kind=r['kind'],status=r['status'],command=json.loads(r['body']),receipt=json.loads(r['result']) if r['result'] else None) for r in c.execute('SELECT * FROM commands WHERE session_id=? ORDER BY rowid',(session_id,))]
    data=json.loads(run[0]) if run else {}
    call_ids={}
    def collect(value):
        if isinstance(value,dict):
            if isinstance(value.get('call_id'),str):call_ids[value['call_id']]=True
            for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    collect(events)
    calls=[]
    with closing(store.connect()) as c:
        for cid in call_ids:
            row=c.execute('SELECT id,model,status,reserved,actual,created_at FROM calls WHERE id=?',(cid,)).fetchone()
            if row:calls.append(dict(row))
    unresolved=[]
    human_feedback=[event for event in events if event['kind']=='operator_artistic_feedback' and isinstance(event['body'],dict)]
    pending_feedback=[event for event in human_feedback if event['body'].get('status')=='artistic_review_pending' and event['body'].get('decision') is None]
    for event in pending_feedback:
        unresolved.append('Artistic review pending: '+str(event['body'].get('notes','Unresolved visual defect')))
    if session['verdict']!='improved':unresolved.append(session['stop_reason'] or 'Session incomplete; no verified correction')
    for attempt in data.get('attempts',[]):
        evaluation=attempt['evaluation']
        for key,result in evaluation['per_criterion'].items():
            if result['passed'] is not True:unresolved.append(key+': '+(result['reason'] or 'criterion failed'))
    audit=data.get('final_audit');candidate=data.get('final_candidate') or data.get('provisional_candidate')
    if audit:
        value=audit['value']
        unresolved.extend('Residual observation: '+item['claim'] for item in value['observations'])
        unresolved.extend('Unresolved hypothesis: '+item['cause'] for item in value['hypotheses'])
        unresolved.extend('Unsupported: '+item for item in value['unsupported_limits'])
    automatic_pass=dict(candidate_version=candidate['after']['version'] if candidate else None,candidate_snapshot=candidate['snapshot_id'] if candidate else None,human_review_required=bool(candidate) and session['verdict']!='improved',final_audit=audit,internal_attempts=len(data.get('attempts',[])))
    report=dict(schema_version='1.0',generated_at=utc_now(),session=session,execution=data,events=events,human_feedback=human_feedback,commands=commands,provider_calls=calls,cost_summary=dict(currency='USD',settled_usd_micro=sum(c['actual'] or 0 for c in calls if c['status']=='settled'),active_reserved_usd_micro=sum(c['reserved'] for c in calls if c['status'] in {'reserved','sent','unknown'})),unresolved=unresolved,repair_validated=session['verdict']=='improved' and session['provider_mode']=='live' and not pending_feedback,native_video_verified=False)
    report['automatic_pass']=automatic_pass
    digest=artifacts.put(canonical(report).encode(),'application/json',metadata={'kind':'operator_report','session_id':session_id})
    return payload('Report',dict(session_id=session_id,state=session['state'],verdict=session['verdict'],best_version=session['best_version'],report_artifact_hash=digest,unresolved=[x[:1000] for x in unresolved][:100],provider_mode=session['provider_mode']))


def export(settings,store,artifacts,session_id,output):
    report=build(store,artifacts,session_id)
    path=contained(settings.workspace,Path(output));path.parent.mkdir(parents=True,exist_ok=True)
    content=artifacts.read(report['report_artifact_hash'])
    temp=path.with_name(path.name+'.writing');temp.write_bytes(content);temp.replace(path)
    return dict(file=str(path),report=report)


def comparison_html(store,artifacts,session_id,attempt_index=None):
    """Standalone review of original rendered evidence; no edited screenshots."""
    import base64
    from html import escape
    report=build(store,artifacts,session_id)
    data=json.loads(artifacts.read(report['report_artifact_hash']))
    session=data['session'];run=data['execution'];attempts=run.get('attempts',[])
    if not attempts:
        return '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>État du passage HDRP</title><body><h1>Aucun candidat à comparer</h1><p>Session '+escape(session_id)+'</p><p>État : '+escape(session['state'])+' · verdict : '+escape(session['verdict'])+'</p><p>'+escape(session['stop_reason'] or 'Aucun rendu candidat disponible.')+'</p><p>Essais correctifs engagés : '+str(session['attempts_used'])+'. Les captures d’une session antérieure ne sont pas présentées comme le résultat de ce passage. Aucun avis artistique requis à ce stade.</p></body></html>'
    if attempt_index is None:
        final=run.get('final_candidate') or run.get('provisional_candidate')
        attempt_index=final['ordinal']-1 if final else -1
    attempt=attempts[attempt_index];before=run['baseline'];after=attempt['after']
    if before['inspection_hash']!=after['inspection_hash'] or before['conditions_hash']!=after['conditions_hash']:raise AgentError('CAPTURE_UNSTABLE','Comparison conditions differ')
    pairs=[];right={c['camera_key']:c for c in after['captures']}
    for capture in before['captures']:
        key=capture['camera_key'];candidate=right.get(key)
        if not candidate or candidate['role']!=capture['role'] or capture['version_id']!=before['version'] or candidate['version_id']!=after['version']:raise AgentError('STALE_VERSION','Comparison camera, role or version mismatch')
        photos=[]
        for label,item in [('Avant '+before['version'],capture),('Candidat '+after['version'],candidate)]:
            binary=artifacts.read(item['artifact_hash']);encoded=base64.b64encode(binary).decode()
            photos.append('<figure><figcaption>'+label+'</figcaption><img alt="'+escape(key,quote=True)+'" src="data:image/png;base64,'+encoded+'"></figure>')
        pairs.append('<section><h2>'+escape(key)+' · '+escape(capture['role'])+'</h2><div class="pair">'+''.join(photos)+'</div></section>')
    evaluation=attempt['evaluation'];diagnosis=attempt['diagnosis']['value'];facts=[o['claim'] for o in diagnosis['observations']];causes=[h['cause'] for h in diagnosis['hypotheses']]
    text=lambda value:escape(json.dumps(value,ensure_ascii=False,indent=2))
    feedback_html=''
    if data['human_feedback']:
        feedback_html='<section><h2>Avis artistique en attente / commentaires de revue</h2><pre>'+text([event['body'] for event in data['human_feedback']])+'</pre><p>Ces commentaires ne valent pas approbation du candidat et ne modifient pas les mesures enregistrées.</p></section>'
    if data['automatic_pass']['final_audit']:
        feedback_html+='<section><h2>Inspection globale finale</h2><pre>'+text(data['automatic_pass']['final_audit']['value'])+'</pre><p>Diagnostic du modèle sur les vues de travail et frames fournies ; il ne remplace ni les contrôles indépendants ni l’avis artistique humain. Les défauts restants sont conservés dans le rapport.</p></section>'
    provenance='Images originales du rendu Unity.' if session['provider_mode']=='live' and all(c.get('provenance')=='live' for packet in [before,after] for c in packet['captures']) else 'Médias offline ou de test : aucune preuve de réparation live.'
    return '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Revue HDRP</title><style>
body{font:16px system-ui;background:#11151d;color:#edf2fa;margin:0 auto;padding:28px;max-width:1400px}p{line-height:1.6}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}figure{margin:0}img{width:100%;height:auto;background:#080b10}figcaption{padding:8px 0;color:#b9cbe2}section{margin-top:32px}pre{white-space:pre-wrap;background:#1d2532;padding:16px;border-radius:8px}h1{font-size:28px}h2{font-size:18px}a{color:#8ac9ff}@media(max-width:700px){.pair{grid-template-columns:1fr}}
</style><h1>Revue de la correction HDRP</h1>'''+ '<p>Session '+escape(session_id)+' · essai '+str(attempt['ordinal'])+' · '+escape(session['provider_mode'])+'</p><p>Verdict du candidat : <b>'+escape(evaluation['verdict'])+'</b>. Version actuellement retenue : '+escape(session['best_version'])+'. Les images montrent le candidat archivé ; elles ne prouvent pas qu’il est encore actif dans Unity.</p>'+feedback_html+'<details><summary>Observations, hypothèses et patch réel</summary><h2>Observations</h2><pre>'+text(facts)+'</pre><h2>Hypothèses</h2><pre>'+text(causes)+'</pre><h2>Opérations</h2><pre>'+text(attempt['patch']['operations'])+'</pre></details>'+''.join(pairs)+'<section><h2>Évaluation séparée</h2><pre>'+text(evaluation)+'</pre><p>'+provenance+' Exposition et caméras comparées selon les conditions enregistrées. Aucun avis humain n’est déduit de l’opinion du modèle. Les vues de contrôle sont réservées à cette revue opérateur.</p></section></html>'
