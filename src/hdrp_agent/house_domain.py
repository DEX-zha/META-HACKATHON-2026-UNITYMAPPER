"""House v1 contracts. Observations, intended designs and native proofs remain distinct."""
from math import hypot
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Id = Annotated[str, Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$')]
Vector2 = tuple[float, float]
Vector3 = tuple[float, float, float]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, validate_assignment=True)


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError('Duplicate '+label)


class Requirement(Contract):
    id: Id
    scope_id: Id
    role: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1)
    priority: Literal['mandatory', 'preferred', 'optional'] = 'mandatory'
    provenance: Literal['user', 'observed', 'inferred', 'creative']
    status: Literal['pending', 'satisfied', 'unavailable', 'waived'] = 'pending'
    fulfilled_by: list[Id] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode='after')
    def completeness(self):
        unique(self.fulfilled_by, 'fulfilling instance')
        if self.priority == 'mandatory' and self.status == 'waived':
            raise ValueError('Mandatory requirements cannot be waived by the planner')
        if self.status == 'satisfied' and (len(self.fulfilled_by) < self.quantity or not self.evidence_ids):
            raise ValueError('Satisfaction requires instances and verified evidence')
        if self.status in {'unavailable', 'waived'} and not self.reason:
            raise ValueError('Unmet requirement needs an explicit reason')
        return self


class RoomProgram(Contract):
    id: Id
    floor_id: Id
    purpose: str = Field(min_length=1)
    style: str = ''
    occupancy: int = Field(default=1, ge=1)
    group_ids: list[Id] = Field(default_factory=list)


class HouseProgram(Contract):
    schema_version: Literal['house.v1'] = 'house.v1'
    id: Id
    project_id: Id
    run_id: Id
    brief: str = Field(min_length=1, max_length=16000)
    creative_policy: Literal['brief_guided', 'reference_guided'] = 'brief_guided'
    reference_hashes: list[str] = Field(default_factory=list)
    rooms: list[RoomProgram] = Field(min_length=1)
    requirements: list[Requirement] = Field(min_length=1)

    @model_validator(mode='after')
    def identities(self):
        unique([r.id for r in self.rooms], 'room')
        unique([r.id for r in self.requirements], 'requirement')
        unique([self.id]+[r.id for r in self.rooms]+list({r.floor_id for r in self.rooms})+[g for r in self.rooms for g in r.group_ids], 'scope identity')
        scopes={self.id}|{r.id for r in self.rooms}|{r.floor_id for r in self.rooms}|{g for r in self.rooms for g in r.group_ids}
        if any(r.scope_id not in scopes for r in self.requirements):
            raise ValueError('Requirement refers to an unknown scope')
        return self


class Floor(Contract):
    id: Id
    elevation_m: float
    ceiling_height_m: float = Field(gt=0)
    slab_thickness_m: float = Field(gt=0)


class RoomGeometry(Contract):
    id: Id
    floor_id: Id
    polygon: list[Vector2] = Field(min_length=4)

    @model_validator(mode='after')
    def orthogonal_polygon(self):
        points=self.polygon
        unique(points,'polygon vertex')
        edges=list(zip(points,points[1:]+points[:1]))
        for a,b in edges:
            if (abs(a[0]-b[0])<1e-7)==(abs(a[1]-b[1])<1e-7):
                raise ValueError('Room polygon must have nonzero orthogonal edges')
        area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))/2
        if area<.01:raise ValueError('Empty room polygon')
        # Nonadjacent orthogonal edges must not cross or touch.
        for i,(a,b) in enumerate(edges):
            for j,(c,d) in enumerate(edges):
                if j<=i+1 or (i==0 and j==len(edges)-1):continue
                if max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1])):
                    raise ValueError('Self-intersecting room polygon')
        return self


class Boundary(Contract):
    id: Id
    floor_id: Id
    start: Vector2
    end: Vector2
    room_ids: list[Id] = Field(min_length=1,max_length=2)
    @model_validator(mode='after')
    def line(self):
        unique(self.room_ids,'boundary room')
        if (abs(self.start[0]-self.end[0])<1e-7)==(abs(self.start[1]-self.end[1])<1e-7):
            raise ValueError('Boundary must be a nonzero orthogonal segment')
        return self


class Portal(Contract):
    id: Id
    boundary_id: Id
    spaces: list[Id] = Field(min_length=2,max_length=2)
    interval_m: Vector2
    height_m: float = Field(gt=0)
    kind: Literal['door','window','passage'] = 'door'
    @model_validator(mode='after')
    def interval(self):
        unique(self.spaces,'portal space')
        if not 0<=self.interval_m[0]<self.interval_m[1]:raise ValueError('Invalid portal interval')
        return self


class VerticalConnection(Contract):
    id: Id
    from_floor: Id
    to_floor: Id
    stair_prefab_guid: str
    landing_start: Vector3
    landing_end: Vector3
    void_min: Vector3
    void_max: Vector3


def inside(point, polygon):
    x,z=point;crossings=0
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>z)!=(b[1]>z) and x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]:crossings+=1
    return crossings%2==1


def polygons_overlap(a,b):
    xs=sorted({p[0] for p in a+b});zs=sorted({p[1] for p in a+b})
    return any(inside(((x+y)/2,(z+w)/2),a) and inside(((x+y)/2,(z+w)/2),b) for x,y in zip(xs,xs[1:]) for z,w in zip(zs,zs[1:]))


def on_room_edge(boundary,polygon):
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if all(min(a[axis],b[axis])-1e-5<=p[axis]<=max(a[axis],b[axis])+1e-5 for p in (boundary.start,boundary.end) for axis in (0,1)):
            return True
    return False


class BuildingIR(Contract):
    schema_version: Literal['building.v1'] = 'building.v1'
    id: Id
    floors: list[Floor] = Field(min_length=1)
    rooms: list[RoomGeometry] = Field(min_length=1)
    boundaries: list[Boundary] = Field(default_factory=list)
    portals: list[Portal] = Field(default_factory=list)
    vertical_connections: list[VerticalConnection] = Field(default_factory=list)
    @model_validator(mode='after')
    def bindings(self):
        for name in ('floors','rooms','boundaries','portals','vertical_connections'):unique([v.id for v in getattr(self,name)],name)
        floors={f.id:f for f in self.floors};rooms={r.id:r for r in self.rooms};walls={b.id:b for b in self.boundaries}
        if any(r.floor_id not in floors for r in self.rooms):raise ValueError('Unknown room floor')
        unique([f.elevation_m for f in self.floors],'floor elevation')
        levels=sorted(self.floors,key=lambda f:f.elevation_m)
        for lower,upper in zip(levels,levels[1:]):
            if lower.elevation_m+lower.ceiling_height_m>upper.elevation_m-upper.slab_thickness_m+1e-6:raise ValueError('Floor height volumes overlap')
        for i,room in enumerate(self.rooms):
            for other in self.rooms[i+1:]:
                if room.floor_id==other.floor_id and polygons_overlap(room.polygon,other.polygon):raise ValueError('Room footprints overlap')
        for i,b in enumerate(self.boundaries):
            axis=0 if abs(b.start[0]-b.end[0])>1e-7 else 1
            fixed=1-axis
            for other in self.boundaries[i+1:]:
                if b.floor_id==other.floor_id and abs(b.start[fixed]-other.start[fixed])<1e-7 and abs(b.start[fixed]-other.end[fixed])<1e-7:
                    if max(min(b.start[axis],b.end[axis]),min(other.start[axis],other.end[axis]))<min(max(b.start[axis],b.end[axis]),max(other.start[axis],other.end[axis]))-1e-7:raise ValueError('Physical boundaries overlap; shared wall needs one identity')
            if b.floor_id not in floors or any(r not in rooms or rooms[r].floor_id!=b.floor_id for r in b.room_ids):raise ValueError('Invalid boundary rooms')
            if any(not on_room_edge(b,rooms[r].polygon) for r in b.room_ids):raise ValueError('Boundary is detached from room edge')
        for p in self.portals:
            b=walls.get(p.boundary_id)
            if b is None:raise ValueError('Portal has no boundary')
            expected=set(b.room_ids)|({'exterior'} if len(b.room_ids)==1 else set())
            if set(p.spaces)!=expected:raise ValueError('Portal spaces differ from boundary adjacency')
            if p.interval_m[1]>hypot(b.end[0]-b.start[0],b.end[1]-b.start[1])+1e-6:raise ValueError('Portal escapes boundary')
            if p.height_m>floors[b.floor_id].ceiling_height_m:raise ValueError('Portal escapes ceiling')
            for other in self.portals:
                if p.id!=other.id and p.boundary_id==other.boundary_id and max(p.interval_m[0],other.interval_m[0])<min(p.interval_m[1],other.interval_m[1]):raise ValueError('Portals overlap')
        for v in self.vertical_connections:
            if v.from_floor==v.to_floor or v.from_floor not in floors or v.to_floor not in floors:raise ValueError('Invalid floor connection')
            if any(a>=b for a,b in zip(v.void_min,v.void_max)):raise ValueError('Empty stair void')
            if abs(v.landing_start[1]-floors[v.from_floor].elevation_m)>.1 or abs(v.landing_end[1]-floors[v.to_floor].elevation_m)>.1:raise ValueError('Landing differs from floor elevation')
        return self


class SupportRegion(Contract):
    surface_id: Id
    rectangle_xz: tuple[float, float, float, float]
    roles: list[str] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def positive_area(self):
        x0,z0,x1,z1=self.rectangle_xz
        if x1<=x0 or z1<=z0:raise ValueError('Support region must have positive area')
        return self


class AssetSemantics(Contract):
    schema_version: Literal['asset-semantics.v1'] = 'asset-semantics.v1'
    prefab_guid: Annotated[str,Field(pattern=r'^[a-f0-9]{32}$')]
    dependency_hash: str = Field(min_length=16)
    prefab_path: str = Field(pattern=r'^Assets/.+\.prefab$')
    bounds_center: Vector3
    bounds_size: Vector3
    forward: Vector3 | None = None
    up: Vector3 = (0,1,0)
    front_status: Literal['unknown','hypothesis','qualified','not_applicable'] = 'unknown'
    front_evidence: list[str] = Field(default_factory=list)
    surfaces: list[dict] = Field(default_factory=list)
    support_regions: list[SupportRegion] = Field(default_factory=list)
    use_volumes: list[dict] = Field(default_factory=list)
    sockets: list[dict] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    measurement_evidence: str | None = None
    @model_validator(mode='after')
    def qualification(self):
        if '..' in self.prefab_path.split('/'):raise ValueError('Asset path traversal')
        if any(x<0 for x in self.bounds_size):raise ValueError('Negative bounds')
        if self.front_status=='qualified' and (not self.front_evidence or self.forward is None):raise ValueError('Qualified front requires semantic evidence')
        for vector in (self.forward,self.up):
            if vector is not None and abs(sum(x*x for x in vector)-1)>1e-4:raise ValueError('Semantic axes must be unit vectors')
        if self.forward is not None and abs(sum(a*b for a,b in zip(self.forward,self.up)))>1e-4:raise ValueError('Forward and up must be orthogonal')
        return self
