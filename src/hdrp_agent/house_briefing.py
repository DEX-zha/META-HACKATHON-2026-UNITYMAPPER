"""Room programming policy: infer inhabited uses without overriding user intent."""
from .domain import canonical
from .house_planning import RECIPES
from .house_floor_details import floor_detail

ROOM_POLICY = '''Design an inhabited room, not just the single furniture item named by its purpose.
First fulfil explicit requests and exclusions. Furnished is the default unless the user asks for empty,
minimal, shell-only, or an exact inventory. Infer useful complementary activities from the room purpose:
- office: work equipment, library/storage with books, greenery, and a reading or visitor corner when space allows;
- living room: seating, reading/storage, plants, and useful personal details;
- bedroom: sleeping, bedside storage, clothes storage, optional reading and greenery;
- kitchen/dining: preparation/eating first, storage and restrained useful details.
Choose a coherent subset for the actual dimensions and style, not every possible item. A bed in an office
is a mixed-use/guest-room decision: only include it when the brief suggests sleeping or guests. Do not
invent a bedroom in every office. Avoid adding a television just to create a reading corner.
The global user brief is the source of explicit requests; the generated room brief is not a user quote. The core room function and explicitly requested groups are mandatory; inferred complements are preferred or optional even if they appear in the generated room description. Place the
primary function first, then storage and complementary uses, then decoration. Preserve circulation;
never resize prefabs or enlarge an explicitly dimensioned room just to fit extra decoration.
For an inhabited game office, explicitly plan a floor layer: a rug near seating and, if the brief allows lived-in clutter, one or more coherent paper clusters near work/storage. Use available floor_assets in detail_assets; these are whole floor prefabs placed separately from tabletop props. Prefer smaller clusters that fit the room; do not carpet every gap. Clean/professional means restrained clutter, not no personal objects; horror/abandoned can use more. Respect explicit empty/minimal/clean-floor exclusions.
Select plants as freestanding plant groups, libraries as library groups, seating corners as reading
or lounge groups. Small books and stationery belong in detail_assets on qualified supports. Use Book_set_A for upright books in a library, Book_set_I for a tabletop stack, Notebook and Pencil_holder for work surfaces. Include books with a library rather than leaving it bare. Do not
put large floor furniture in detail_assets. Use only catalogue names. Prefer qualified assets for inferred decoration; unqualified assets can retain an explicit requested need but cannot yet be placed. Do not repeat groups without
an activity/occupancy reason. Unavailable wall art, rugs or lighting must remain explicit needs when
requested; do not replace them with unrelated props. Leave calm areas rather than filling every gap.'''


def room_prompt(room,brief,assets):
    catalogue=dict(room=room,brief=brief,
        floor_assets=[dict(name=n,size_m=a['bounds_size']) for n,a in assets.items() if floor_detail(n,a)],
        qualified_assets=[n for n,a in assets.items() if a.get('front_status') in {'qualified','not_applicable'}],
        unqualified_assets=[n for n,a in assets.items() if a.get('front_status') not in {'qualified','not_applicable'} and not floor_detail(n,a)])
    return ROOM_POLICY+'\nRecipes: '+canonical({k:[s[1] for s in v] for k,v in RECIPES.items()})+'\ncustom retains an unsupported explicit need. Native placement checks decide what fits. Room and brief: '+canonical(catalogue)
