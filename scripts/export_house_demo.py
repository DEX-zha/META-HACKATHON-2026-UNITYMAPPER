"""Export real run evidence and labelled viewing copies for a presentation."""
import argparse
from pathlib import Path
import html
import json
import shutil
import sqlite3
import subprocess


def encode(images, destination, fps):
    if not images:
        return
    frames=destination.parent/('.frames-'+destination.stem)
    frames.mkdir(exist_ok=True)
    try:
        for n,source in enumerate(images):
            shutil.copyfile(source,frames/f'{n:06d}{source.suffix}')
        subprocess.run(['ffmpeg','-v','error','-y','-framerate',str(fps),'-i',str(frames/('%06d'+images[0].suffix)),
                        '-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1',
                        '-r','24','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-an',str(destination)],check=True)
    finally:
        shutil.rmtree(frames)


def export(root,run,output):
    state=root/'.hdrp-agent';output.mkdir(parents=True,exist_ok=True)
    def artifact(digest):return state/'artifacts'/digest[:2]/digest
    c=sqlite3.connect(state/'global.sqlite3');c.row_factory=sqlite3.Row
    action=c.execute('select * from house_actions where run_id=?',(run,)).fetchone()
    if not action:raise ValueError('Unknown run')
    request=json.loads(action['request']);checkpoint=json.loads(action['checkpoint'])
    (output/'prompt.txt').write_text(request['parameters']['brief']+'\n')
    (output/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2))
    events=[dict(r) for r in c.execute('select id,kind,body,created_at from events where subject=? order by id',(action['id'],))]
    for event in events:event['body']=json.loads(event['body'])
    (output/'events.json').write_text(json.dumps(events,indent=2))
    stages=[];evolution=[];sam=[];sam_highlights=[]
    for command in c.execute('select id,status,result from commands where session_id=? order by rowid',(action['session_id'],)):
        result=json.loads(command['result'] or '{}');digest=result.get('details_artifact_hash')
        if not digest:continue
        proof=json.loads(artifact(digest).read_text())
        if proof.get('schema_version')!='house-native.v1':continue
        folder=output/f'stage-{len(stages)+1:02d}';folder.mkdir(exist_ok=True)
        (folder/'native-proof.json').write_text(json.dumps(proof,indent=2))
        stage=dict(command_id=command['id'],command_status=command['status'],scene_path=proof['scene_path'],instance_count=len(proof['instances']),selected=proof['scene_path']==checkpoint.get('scene_path'),images=[],sam=[])
        for cap in proof.get('captures',[]):
            target=folder/(cap['key']+'.png');shutil.copyfile(artifact(cap['artifact_hash']),target);stage['images'].append(str(target.relative_to(output)))
            relative=Path(cap.get('file',''))
            overlay=state/'house/runs'/run/relative.parent/('sam-'+relative.name)
            if overlay.is_file():
                target=folder/('sam-'+cap['key']+'.png');shutil.copyfile(overlay,target);stage['sam'].append(str(target.relative_to(output)));sam.append(target)
        if stage['images']:evolution.append(output/stage['images'][0])
        segmentation_hash=checkpoint.get('segmentation_receipts',{}).get(proof['scene_version'])
        if segmentation_hash and stage['sam']:
            scores={}
            for segmentation in json.loads(artifact(segmentation_hash).read_text()):
                for region in segmentation['regions']:
                    x0,y0,x1,y1=region['bbox_xyxy'];key=segmentation['capture_hash'];scores[key]=scores.get(key,0)+(x1-x0)*(y1-y0)
            ranked=sorted(proof['captures'],key=lambda cap:scores.get(cap['artifact_hash'],0),reverse=True)
            for cap in ranked:
                image=folder/('sam-'+cap['key']+'.png')
                if image.exists() and scores.get(cap['artifact_hash'],0)>0:
                    sam_highlights.append(image);break
        stages.append(stage)
    # These clips are explicitly still-image montages, not continuous camera footage.
    encode(evolution,output/'01-evolution-montage.mp4',.5)
    encode(sam,output/'02-sam-views-montage.mp4',1)
    selected=next((s for s in reversed(stages) if s['selected']),None)
    if selected:
        overview=selected['images'][:4];details=selected['images'][4:]
        highlights=overview+[details[round(n*(len(details)-1)/max(1,min(4,len(details))-1))] for n in range(min(4,len(details)))] if details else overview
        encode([output/i for i in dict.fromkeys(highlights)],output/'03-selected-room-views.mp4',.5)
    encode(sam_highlights[-6:],output/'04-sam-highlights.mp4',.5)
    live=output/'live-frames.json';recordings=[]
    if live.exists():
        frames=json.loads(live.read_text())['frames'];groups=[]
        for frame in frames:
            if not groups or frame['elapsed_seconds']-groups[-1][-1]['elapsed_seconds']>3:groups.append([])
            groups[-1].append(frame)
        for n,group in enumerate(groups):
            if len(group)<5:continue
            dest=output/f'live-segment-{n+1:02d}.mp4'
            # Native frames retained in capture order. No synthetic/interpolated frames.
            encode([output/'live-frames'/f['file'] for f in group],dest,5)
            recordings.append(dict(file=dest.name,frames=len(group),source_duration=group[-1]['elapsed_seconds']-group[0]['elapsed_seconds'],playback_fps=5,note='Native live frame sequence, sampled and retimed to 5 fps; gaps split; not a real-time screen recording'))
    summary=dict(run_id=run,state=action['state'],quality_state=checkpoint.get('quality_state'),stop_reason=checkpoint.get('stop_reason'),stages=stages,recordings=recordings,unresolved=checkpoint.get('unresolved',[]),correction_blockers=checkpoint.get('correction_blockers',[]))
    (output/'manifest.json').write_text(json.dumps(summary,indent=2))
    cards=[]
    for n,stage in enumerate(stages):
        cards.append(f'<section><h2>Stage {n+1} · {stage["instance_count"]} instances'+(' · Selected result' if stage['selected'] else ' · Candidate')+'</h2><p>'+html.escape(stage['scene_path'])+'</p><div class="grid">'+''.join('<figure><a href="'+i+'"><img loading="lazy" src="'+i+'"></a><figcaption>'+html.escape(Path(i).name)+'</figcaption></figure>' for i in stage['images']+stage['sam'])+'</div></section>')
    videos=''.join('<figure><video controls preload="metadata" src="'+p.name+'"></video><figcaption>'+p.name+'</figcaption></figure>' for p in sorted(output.glob('*.mp4')))
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>UnityMapper · Bedroom demonstration</title><style>body{background:#101722;color:#edf3fa;font:16px system-ui;margin:40px auto;max-width:1400px;padding:0 24px}h1{font-size:36px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}figure{margin:0 0 24px}img,video{width:100%;border-radius:12px}figcaption,p{color:#aebed0}section{margin-top:48px}a{color:#78b5ff}pre{white-space:pre-wrap;background:#1a2535;padding:24px;border-radius:12px}</style><h1>UnityMapper · Bedroom demonstration</h1><p>Run '+run+' · '+html.escape(str(action['state']))+' · Quality: '+html.escape(str(checkpoint.get('quality_state')))+' </p><p>Original native renders and actual SAM mask overlays. Montages show discrete views; live segments contain sampled native camera frames. Intermediate or rejected candidates are not final results.</p><p><a href="manifest.json">Evidence manifest</a> · <a href="events.json">Agent decisions and progress</a> · <a href="prompt.txt">Exact prompt</a></p><pre>'+html.escape(request['parameters']['brief'])+'</pre><div class="grid">'+videos+'</div>'+''.join(cards))
    print(json.dumps(dict(output=str(output),stages=len(stages),recordings=len(recordings),state=action['state'],quality=checkpoint.get('quality_state'))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args()
    export(Path.cwd(),args.run,Path(args.output).resolve())
