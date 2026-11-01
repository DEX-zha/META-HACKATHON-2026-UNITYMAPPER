"""Local operator commands; live inference requires explicit financial admission."""
import argparse
import json
from pathlib import Path

from . import __version__
from . import budget_cli
from .config import Settings
from .domain import AgentError, WORKSPACE
from .doctor import diagnose
from .store import Store


def main(argv=None):
    parser=argparse.ArgumentParser(prog='hdrp-agent',description='Unity HDRP scene inspection service')
    parser.add_argument('--version',action='version',version=__version__)
    parser.add_argument('--workspace',type=Path,default=WORKSPACE)
    parser.add_argument('--env-file',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    doctor=commands.add_parser('doctor');doctor.add_argument('--offline',action='store_true')
    serve=commands.add_parser('serve');serve.add_argument('--provider-mode',choices=['offline','live'],default='offline')
    commands.add_parser('validate-local',help='Verify saved J0 Unity captures, bake and restoration evidence')
    probe=commands.add_parser('probe',help='Financially admitted Meta core probes')
    probe.add_argument('--suite',choices=['core'],default='core');probe.add_argument('--max-usd',default='5');probe.add_argument('--reuse-spark-call',help='Reprocess a completed paid exact-request receipt without another inference')
    probe.add_argument('--reuse-sam-call',help='Reprocess a completed paid exact-image SAM receipt')
    reports=commands.add_parser('reports',help='Export durable operator evidence')
    reports_sub=reports.add_subparsers(dest='reports_command',required=True)
    report_export=reports_sub.add_parser('export');report_export.add_argument('session_id');report_export.add_argument('--output',type=Path,required=True)
    house=commands.add_parser('house',help='House v1 reference evidence and durable design tools')
    hs=house.add_subparsers(dest='house_command',required=True)
    atlas=hs.add_parser('atlas');atlas.add_argument('directory',type=Path)
    catalogue=hs.add_parser('import-catalogue');catalogue.add_argument('file',type=Path)
    review=hs.add_parser('import-reviews');review.add_argument('file',type=Path);review.add_argument('--views',type=Path,required=True)
    create=hs.add_parser('store-program');create.add_argument('file',type=Path)
    status=hs.add_parser('status');status.add_argument('run_id')
    budget_cli.add_commands(commands)
    args=parser.parse_args(argv)
    try:
        settings=Settings.load(args.workspace,getattr(args,'provider_mode','live' if args.command=='probe' else 'offline'),args.env_file)
        store=Store(settings.db_path)
        if args.command=='house':
            from .house_store import HouseStore
            from .house_catalogue import Catalogue
            from .house_atlas import inspect_atlas
            houses=HouseStore(store)
            if args.house_command=='atlas':
                result=inspect_atlas(args.directory)
                print(json.dumps({k:result[k] for k in ('status','resolved_prefab_roots','source_unchanged','visual_qualified')}));return 0
            if args.house_command=='import-catalogue':
                print(json.dumps(dict(imported=Catalogue(houses).import_measurements(json.loads(args.file.read_text())))));return 0
            if args.house_command=='import-reviews':
                count=Catalogue(houses).import_reviews(json.loads(args.file.read_text()),args.views);print(json.dumps(dict(reviewed=count)));return 0
            if args.house_command=='store-program':
                program=houses.create(json.loads(args.file.read_text()));print(json.dumps(dict(run_id=program['run_id'],requirements=len(program['requirements']))));return 0
            print(json.dumps(houses.snapshot(args.run_id),indent=2));return 0
        if args.command=='doctor':
            report=diagnose(settings);print(json.dumps(report,indent=2));return 0 if report['status']=='ready' else 2
        if args.command=='validate-local':
            from .local_validation import verify
            report=verify(settings);print(json.dumps(report,indent=2));return 0 if report['status']=='verified' else 2
        if args.command=='probe':
            from .probes import core
            print(json.dumps(core(settings,store,args.max_usd,args.reuse_spark_call,args.reuse_sam_call),indent=2));return 0
        if args.command=='reports':
            from .artifacts import ArtifactStore
            from .reporting import export
            print(json.dumps(export(settings,store,ArtifactStore(settings.state/'artifacts',store),args.session_id,args.output),indent=2));return 0
        if args.command=='serve':
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(settings),host='127.0.0.1',port=8765,workers=1,access_log=False)
            return 0
        print(json.dumps(budget_cli.execute(args,settings,store),indent=2));return 0
    except AgentError as exc:
        print(json.dumps(exc.as_dict()));return 2
