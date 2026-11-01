"""Inventory explicit scene prefab records and group ancestry.
Counts are serialized records, not resolved runtime mesh/object totals. Nested
prefab contents, hidden-state inheritance and final lighting need native review.
Run with the project Python environment (PyYAML required).
"""
from pathlib import Path
import re,json,collections,yaml
import argparse
parser=argparse.ArgumentParser(description='Read-only serialized Unity house reference audit (does not open or modify Unity).')
parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]/'unity/HDRPValidation')
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'.hdrp-agent/reports/house-worn-night')
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
root=args.project;path=root/'Assets/AtmosphericHouse/Scenes/House_worn_night.unity'
text=path.read_text();docs=[]
for m in re.finditer(r'^--- !u!(\d+) &(\d+)[^\n]*\n(.*?)(?=^--- !u!|\Z)',text,re.M|re.S):
 d=yaml.safe_load(m[3]);docs.append((int(m[1]),m[2],next(iter(d.values()))))
guids={}
for p in (root/'Assets/AtmosphericHouse').rglob('*.meta'):
 m=re.search(r'^guid: (\w+)',p.read_text(errors='ignore'),re.M)
 if m:guids[m[1]]=str(p.relative_to(root))[:-5]
counts=collections.Counter();instances=[];names=[]
for kind,id,d in docs:
 if kind==1001:
  source=guids.get(d.get('m_SourcePrefab',{}).get('guid'),str(d.get('m_SourcePrefab')));counts[source]+=1
  mods=d.get('m_Modification',{});instances.append(dict(id=id,source=source,parent=mods.get('m_TransformParent'),overrides=mods.get('m_Modifications')))
 if kind==1:names.append(d.get('m_Name'))
out=dict(source=str(path),serialized_types=dict(collections.Counter(k for k,_,_ in docs)),prefab_counts=dict(counts.most_common()),groups=names,instances=instances)
(args.output/'serialized-audit.json').write_text(json.dumps(out,indent=2))
print('Types',out['serialized_types']);print('Groups',names);print('Prefab instances',sum(counts.values()),'unique',len(counts));print('\n'.join(f'{n:4} {p}' for p,n in counts.most_common(100)))
byid={id:(kind,d) for kind,id,d in docs};group_rooms=['Kitchen','Office','Bedroom_master','Bathroom_upstairs','Bathroom_downstairs','Laundry_room','Bedroom_girl','Guest_room','TV_room','Hallway_upstairs','Hallway_downstairs','Living_room','Dining_room','Basement_props','Porch']
def ancestry(tid):
 out=[];seen=set()
 while tid and str(tid)!='0' and str(tid) not in seen:
  tid=str(tid);seen.add(tid);kind,d=byid.get(tid,(None,{}))
  if kind==4:
   go=byid.get(str(d.get('m_GameObject',{}).get('fileID')),(None,{}))[1]
   if go.get('m_Name'):out.append(go['m_Name'])
   if 'm_Father' in d:tid=d['m_Father']['fileID']
   else:tid=byid.get(str(d.get('m_PrefabInstance',{}).get('fileID')),(None,{}))[1].get('m_Modification',{}).get('m_TransformParent',{}).get('fileID')
  else:break
 return out
rooms=collections.defaultdict(list);cats=collections.Counter();overrides=collections.Counter();lights=[];materials=collections.Counter()
for x in instances:
 ancestors=ancestry((x.get('parent') or {}).get('fileID'));x['ancestors']=ancestors
 room=next((a for a in ancestors if a in group_rooms),'Structure / shared / other');rooms[room].append(x['source'])
 source=x['source'];category=source.split('/Prefabs/')[-1].split('/')[0];cats[category]+=1
 for m in x.get('overrides') or []:
  overrides[m.get('propertyPath')]+=1
  if 'm_Materials' in m.get('propertyPath',''):
   g=m.get('objectReference',{}).get('guid');materials[guids.get(g,str(g))]+=1
for kind,id,d in docs:
 if kind==108:
  go=byid.get(str(d.get('m_GameObject',{}).get('fileID')),(None,{}))[1]
  lights.append(dict(name=go.get('m_Name'),type=d.get('m_Type'),intensity=d.get('m_Intensity'),range=d.get('m_Range'),color=d.get('m_Color'),shadows=d.get('m_Shadows'),lightmapping=d.get('m_Lightmapping')))
summary=dict(categories=dict(cats),rooms={k:dict(count=len(v),unique=len(set(v)),prefabs=dict(collections.Counter(v).most_common())) for k,v in rooms.items()},explicit_lights=lights,overrides=dict(overrides.most_common()),material_overrides=dict(materials.most_common()),stairs={k:v for k,v in counts.items() if any(w in k.lower() for w in ['stair','rail','ladder'])})
(args.output/'semantic-audit.json').write_text(json.dumps(summary,indent=2));print('CATEGORIES',dict(cats));print('ROOMS',[(k,len(v)) for k,v in rooms.items()]);print('STAIRS',summary['stairs']);print('LIGHTS',[(x['name'],x['type'],x['lightmapping']) for x in lights]);print('MATERIALS',materials.most_common(12))
