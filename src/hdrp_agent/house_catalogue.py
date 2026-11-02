"""Native prefab measurements and separately evidenced functional semantics."""
import json
from .domain import AgentError, canonical
from .house_domain import AssetSemantics


class Catalogue:
    def __init__(self, houses):self.store=houses.store

    def import_measurements(self, rows):
        assets=[]
        for row in rows:
            value=dict(row)
            # Geometry export cannot assert an intended semantic front.
            if any(k in value for k in ('forward','front_status','front_evidence','support_regions','use_volumes','sockets','placement_modes','placement_evidence')):
                raise AgentError('SEMANTICS_UNQUALIFIED','Native geometry is not a reviewed functional orientation')
            if any(s.get('supports_items') or s.get('qualification') not in {'geometry_candidate','unavailable'} for s in value.get('surfaces',[])):
                raise AgentError('SEMANTICS_UNQUALIFIED','Native measurements cannot qualify support use')
            assets.append(AssetSemantics.model_validate(value))
        if len({a.prefab_guid for a in assets})!=len(assets):raise AgentError('INVALID_INPUT','Duplicate measured prefab')
        with self.store.tx() as c:
            for a in assets:
                previous=c.execute('SELECT body FROM asset_semantics WHERE prefab_guid=? AND dependency_hash=?',(a.prefab_guid,a.dependency_hash)).fetchone()
                if previous:
                    old=json.loads(previous[0]);new=a.model_dump(mode='json')
                    if any(old[k]!=new[k] for k in ('bounds_center','bounds_size','surfaces')):raise AgentError('STALE_EVIDENCE','Same dependency hash has conflicting geometry')
                else:c.execute('INSERT INTO asset_semantics VALUES(?,?,?)',(a.prefab_guid,a.dependency_hash,canonical(a.model_dump(mode='json'))))
        return len(assets)

    def get(self,guid,dependency_hash):
        with self.store.tx() as c:row=c.execute('SELECT body FROM asset_semantics WHERE prefab_guid=? AND dependency_hash=?',(guid,dependency_hash)).fetchone()
        if not row:raise AgentError('SEMANTICS_UNQUALIFIED','Prefab dependency hash is not measured')
        return json.loads(row[0])

    def qualify_front(self,guid,dependency_hash,forward,evidence,*,status="qualified"):
        if status not in {"qualified","not_applicable"} or (status=="not_applicable" and forward is not None):raise AgentError("SEMANTICS_UNQUALIFIED","Invalid reviewed orientation status")
        if not evidence or any(not isinstance(e,dict) or e.get('kind') not in {'reviewed_multiview','trusted_annotation','qualified_recipe'} or not e.get('reference') or not e.get('reviewer') for e in evidence):raise AgentError('SEMANTICS_UNQUALIFIED','Functional front needs reviewed evidence, not an implicit prefab axis')
        with self.store.tx() as c:
            row=c.execute('SELECT body FROM asset_semantics WHERE prefab_guid=? AND dependency_hash=?',(guid,dependency_hash)).fetchone()
            if not row:raise AgentError('SEMANTICS_UNQUALIFIED','Prefab must be measured first')
            data=json.loads(row[0]);data.update(forward=forward,front_status=status,front_evidence=[canonical(e) for e in evidence]);a=AssetSemantics.model_validate(data)
            c.execute('UPDATE asset_semantics SET body=? WHERE prefab_guid=? AND dependency_hash=?',(canonical(a.model_dump(mode='json')),guid,dependency_hash))
            self.store.event(c,guid,'house.front_qualified',dict(dependency_hash=dependency_hash,forward=forward,evidence=evidence))
        return a.model_dump(mode='json')

    def require_functional(self,guid,dependency_hash):
        a=self.get(guid,dependency_hash)
        if a['front_status'] not in {'qualified','not_applicable'}:raise AgentError('SEMANTICS_UNQUALIFIED','Functional front is not qualified')
        return a

    def qualify_placement(self,guid,dependency_hash,modes,evidence):
        if not modes or not evidence or any(not isinstance(e,dict) or e.get('kind') not in {'reviewed_multiview','trusted_annotation'} or not e.get('reference') or not e.get('reviewer') or e.get('dependency_hash')!=dependency_hash for e in evidence):
            raise AgentError('SEMANTICS_UNQUALIFIED','Placement needs exact-prefab reviewed evidence')
        with self.store.tx() as c:
            row=c.execute('SELECT body FROM asset_semantics WHERE prefab_guid=? AND dependency_hash=?',(guid,dependency_hash)).fetchone()
            if not row:raise AgentError('SEMANTICS_UNQUALIFIED','Prefab must be measured first')
            data=json.loads(row[0]);data.update(placement_modes=list(dict.fromkeys(modes)),placement_evidence=[canonical(e) for e in evidence])
            asset=AssetSemantics.model_validate(data)
            c.execute('UPDATE asset_semantics SET body=? WHERE prefab_guid=? AND dependency_hash=?',(canonical(asset.model_dump(mode='json')),guid,dependency_hash))
            self.store.event(c,guid,'house.placement_qualified',dict(dependency_hash=dependency_hash,modes=modes,evidence=evidence))
        return asset.model_dump(mode='json')

    def qualify_support(self,guid,dependency_hash,surface_id,rectangle,roles,evidence):
        from .house_supports import footprint_supported
        from .house_domain import SupportRegion
        if not evidence or any(not isinstance(e,dict) or e.get('kind') not in {'reviewed_multiview','trusted_annotation','qualified_recipe'} or not e.get('reference') or not e.get('reviewer') for e in evidence):
            raise AgentError('SEMANTICS_UNQUALIFIED','Support needs reviewed semantic evidence')
        region=SupportRegion(surface_id=surface_id,rectangle_xz=rectangle,roles=roles,evidence=[canonical(e) for e in evidence])
        with self.store.tx() as c:
            row=c.execute('SELECT body FROM asset_semantics WHERE prefab_guid=? AND dependency_hash=?',(guid,dependency_hash)).fetchone()
            if not row:raise AgentError('SEMANTICS_UNQUALIFIED','Prefab must be measured first')
            data=json.loads(row[0]);surface=next((s for s in data['surfaces'] if s['id']==surface_id),None)
            if surface is None or not footprint_supported(surface.get('triangles',[]),rectangle):
                raise AgentError('SEMANTICS_UNQUALIFIED','Support footprint leaves measured surface or crosses a hole')
            regions=data.setdefault('support_regions',[])
            record=region.model_dump(mode='json')
            if record not in regions:regions.append(record)
            asset=AssetSemantics.model_validate(data)
            c.execute('UPDATE asset_semantics SET body=? WHERE prefab_guid=? AND dependency_hash=?',(canonical(asset.model_dump(mode='json')),guid,dependency_hash))
            self.store.event(c,guid,'house.support_qualified',dict(dependency_hash=dependency_hash,region=record))
        return asset.model_dump(mode='json')

    def import_reviews(self,document,views_directory):
        """Apply explicit operator reviews only to the exact measured/rendered prefab."""
        import hashlib
        from pathlib import Path
        directory=Path(views_directory).resolve()
        manifest={r['prefab_guid']:r for r in json.loads((directory/'manifest.json').read_text())}
        if document.get('schema_version')!='house-functional-reviews.v1':
            raise AgentError('INVALID_INPUT','Unknown functional review schema')
        prepared=[]
        for row in document['reviews']:
            guid=row['prefab_guid'];native=manifest.get(guid)
            if not native or native['dependency_hash']!=row['dependency_hash']:
                raise AgentError('STALE_EVIDENCE','Functional preview no longer matches prefab')
            path=directory/native['file']
            if path.resolve().parent!=directory or path.is_symlink() or not path.is_file():
                raise AgentError('OUT_OF_SCOPE','Review image must be an owned file')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['image_sha256']:
                raise AgentError('STALE_EVIDENCE','Reviewed preview image changed')
            data=self.get(guid,row['dependency_hash'])
            evidence=dict(kind='reviewed_multiview',reference=row['image_sha256'],reviewer=document['reviewer'],note=row['note'])
            data.update(forward=row['forward'],front_status=row.get('front_status','qualified'),front_evidence=[canonical(evidence)])
            AssetSemantics.model_validate(data)
            from .house_supports import footprint_supported
            from .house_domain import SupportRegion
            for region in row.get('support_regions',[]):
                SupportRegion(**region,evidence=[canonical(evidence)])
                surface=next((s for s in data['surfaces'] if s['id']==region['surface_id']),None)
                if surface is None or not footprint_supported(surface.get('triangles',[]),region['rectangle_xz']):
                    raise AgentError('SEMANTICS_UNQUALIFIED','Reviewed support is outside actual mesh surface')
            prepared.append((row,evidence))
        for row,evidence in prepared:
            self.qualify_front(row['prefab_guid'],row['dependency_hash'],row['forward'],[evidence],status=row.get('front_status','qualified'))
            for region in row.get('support_regions',[]):
                self.qualify_support(row['prefab_guid'],row['dependency_hash'],region['surface_id'],region['rectangle_xz'],region['roles'],[evidence])
        return len(prepared)
