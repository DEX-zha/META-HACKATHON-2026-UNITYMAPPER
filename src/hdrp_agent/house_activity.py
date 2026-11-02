"""Public decisions extracted from structured outputs, never private model reasoning."""


def model_summary(schema, value):
    if schema == 'ModelHouseCatalogueChoice':
        return value.get('summary', '') + '\nSelected: ' + ', '.join(value.get('selected', []))
    if schema == 'ModelHouseAssetReview':
        return value.get('summary', '') + '\nFront: ' + value.get('front', 'unknown') + '; reviewed supports: ' + ', '.join(value.get('supports', []))
    if schema == 'ModelHouseOutline':
        return '\n'.join(f"{r['purpose']}: {r['width_m']} × {r['depth_m']} m, floor {r['floor_index']}. {r['brief']}" for r in value.get('rooms', []))
    if schema == 'ModelHouseRoomV2':
        lines=[]
        for group in value.get('groups', []):
            assets=', '.join(i['asset'] for i in group.get('items', []))
            lines.append(f"{group['id']}: {group['description']} — {assets}. Proposed anchor: {group.get('anchor_m')}; rotation: {group.get('yaw_deg')}°.")
        lines.extend('Unresolved: '+s for s in value.get('unresolved', []))
        return '\n'.join(lines)
    if schema == 'ModelHouseInspection':
        lines=[value.get('summary', '')]
        lines.extend(f"{o['kind']} · {o['message']} — proposed action: {o['suggested_action']} ({o['instance_id'] or 'room'})." for o in value.get('observations', []))
        return '\n'.join(lines)
    return ''
