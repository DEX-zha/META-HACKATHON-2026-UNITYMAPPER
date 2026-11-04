"""Make captioned and clean presentation clips from a frozen native run snapshot."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess


def prepare(run, output):
    root = Path.cwd()
    state = root / '.hdrp-agent'
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state / 'global.sqlite3')
    db.row_factory = sqlite3.Row
    action = db.execute('select * from house_actions where run_id=?', (run,)).fetchone()
    if not action:
        raise ValueError('Unknown run')
    checkpoint = json.loads(action['checkpoint'])
    request = json.loads(action['request'])
    def artifact(digest):
        return state / 'artifacts' / digest[:2] / digest
    accepted = {x.get('scene_path') for x in checkpoint.get('zone_history', []) + checkpoint.get('iterations', []) if x.get('status') == 'accepted'}
    accepted.add(checkpoint.get('scene_path'))
    stages = []
    for row in db.execute('select result from commands where session_id=? order by rowid', (action['session_id'],)):
        digest = json.loads(row['result'] or '{}').get('details_artifact_hash')
        if not digest:
            continue
        proof = json.loads(artifact(digest).read_text())
        if proof.get('schema_version') == 'house-native.v1' and proof.get('scene_path') in accepted and proof.get('captures'):
            stages.append(proof)
    selected = next(p for p in reversed(stages) if p['scene_path'] == checkpoint['scene_path'])
    def sample(items, count):
        return [items[round(i * (len(items)-1) / max(1, count-1))] for i in range(min(count, len(items)))]
    shots = []
    def add(path, chapter, proof, capture):
        shots.append({'source': str(path), 'chapter': chapter, 'scene_path': proof['scene_path'], 'capture_key': capture['key'], 'artifact_hash': capture['artifact_hash']})
    for proof in sample(stages, 6):
        cap = proof['captures'][0]
        add(artifact(cap['artifact_hash']), 'Building the room', proof, cap)
    masks = []
    for proof in stages:
        for cap in proof['captures']:
            relative = Path(cap.get('file', ''))
            overlay = state / 'house/runs' / run / relative.parent / ('sam-' + relative.name)
            if overlay.exists():
                masks.append((overlay, proof, cap))
    for overlay, proof, cap in sample(masks, 5):
        add(overlay, 'Visual inspection | SAM', proof, cap)
    caps = selected['captures']
    for cap in caps[:4] + sample(caps[4:], 5):
        add(artifact(cap['artifact_hash']), 'Retained room | Work in progress', selected, cap)
    if not shots:
        raise ValueError('No native captures available')
    frames = output / 'presentation-frames'
    frames.mkdir(exist_ok=True)
    for i, shot in enumerate(shots):
        dest = frames / f'{i:03d}.png'
        shutil.copyfile(shot['source'], dest)
        shot['exported_frame'] = str(dest.relative_to(output))
        shot['start_seconds'] = i * 2
        shot['duration_seconds'] = 2
    clean = output / 'presentation-clean-1080p.mp4'
    titled = output / 'presentation-titled-1080p.mp4'
    base = ['ffmpeg', '-v', 'error', '-y']
    codec = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-an', '-movflags', '+faststart']
    subprocess.run(base + ['-framerate', '1/2', '-i', str(frames / '%03d.png'), '-frames:v', str(len(shots)*48), '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1', '-r', '24'] + codec + [str(clean)], check=True)
    from PIL import Image, ImageDraw, ImageFont
    title_frames = output / 'presentation-titled-frames'
    title_frames.mkdir(exist_ok=True)
    font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    for i, shot in enumerate(shots):
        with Image.open(frames / f'{i:03d}.png') as source:
            frame = source.convert('RGB').resize((1920, 1080), Image.Resampling.LANCZOS)
        overlay = Image.new('RGBA', frame.size)
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, 1920, 112), fill=(0, 0, 0, 140))
        draw.text((48, 15), 'UNITYMAPPER', font=ImageFont.truetype(font_path, 25), fill=(220, 225, 235, 255))
        draw.text((48, 51), shot['chapter'], font=ImageFont.truetype(font_path, 35), fill='white')
        Image.alpha_composite(frame.convert('RGBA'), overlay).convert('RGB').save(title_frames / f'{i:03d}.png')
    subprocess.run(base + ['-framerate', '1/2', '-i', str(title_frames / '%03d.png'), '-frames:v', str(len(shots)*48), '-r', '24'] + codec + [str(titled)], check=True)
    (output / 'presentation-prompt.txt').write_text(request['parameters']['brief'] + '\n')
    metadata = dict(run_id=run, snapshot_state=action['state'], quality_state=checkpoint.get('quality_state'), selected_scene=selected['scene_path'], instances=len(selected['instances']), duration_seconds=len(shots)*2, shots=shots)
    (output / 'presentation-manifest.json').write_text(json.dumps(metadata, indent=2))
    (output / 'presentation-notes.txt').write_text('Real native Unity captures and actual SAM overlays, arranged as a still-image montage. No generated replacement images or relighting. Original 1280x720 captures upscaled to 1920x1080, 24 fps, silent. Each shot lasts 2 seconds. The clean version has no titles.\nThis development run required service fixes and recoveries; this clip is not evidence of an uninterrupted autonomous run. The retained room is a work in progress, not a final artistic qualification. Intermediate/rejected candidates remain in the full evidence gallery.\nSnapshot scene: ' + selected['scene_path'] + '\nRun: ' + run + '\n')
    print(json.dumps({k:v for k,v in metadata.items() if k != 'shots'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.run, args.output.resolve())
