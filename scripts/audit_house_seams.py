"""Read native-exported candidate geometry; report geometric upper-seam evidence."""
import argparse
import json
from pathlib import Path
from hdrp_agent.house_seams import audit,seam_rays,validate_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geometry',type=Path)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('native_receipt',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    geometry=json.loads(args.geometry.read_text());manifest_bytes=args.manifest.read_bytes()
    proof=json.loads(args.native_receipt.read_text());manifest=validate_source(geometry,manifest_bytes,proof)
    building=manifest['building'];report=audit(geometry['meshes'],seam_rays(building['boundaries'],building['rooms']))
    report.update(scene_path=geometry['scene_path'],scene_sha256=geometry['scene_sha256'],geometry_file=str(args.geometry),manifest_file=str(args.manifest),native_receipt_file=str(args.native_receipt),manifest_hash=proof['manifest_hash'])
    # Never overwrite a previous diagnostic report.
    with args.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(samples=report['samples'],counts=report['counts'],lighting_qualified=False)))


if __name__=='__main__':main()
