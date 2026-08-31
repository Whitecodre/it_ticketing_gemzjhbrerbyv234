# apps/tickets/asset_import_transform.py
"""
Normalizes an arbitrary raw asset-inventory spreadsheet layout (a title
banner row, section-header rows carrying a Building/Floor location, blank
cells meaning "same person/department as the row above" within a bundle)
into a flat, one-row-per-device list ready for asset_import_commit.

Tuned against a real client inventory export shaped like:

    S/n | USER          | DEPARTMENT | DEVICE  | TAG               | TRACK #NO | Active | Not Active | Comments
    1   | name of user  | Account    | Monitor | HD GF ACC MNT 008 | ACC008    | Active |            | Functional
        |               | Account    | CPU     | HD GF ACC CPU 008 |           |        |            |
        |               | Account    | UPS     | HD GF ACC UPS 008 |           |        |            |

Only S/n, USER, TRACK #NO, Active/Not Active, and Comments are carried by a
bundle's first row — DEPARTMENT is (per this format) already repeated on
every row, so it needs no forward-filling. LOCATION has no column of its
own at all; it's conveyed entirely by section-header rows like "Ground
Floor" that appear above a block of department rows, so those are detected
by a floor/building keyword match and carried forward until the next one.

This module is intentionally heuristic and meant to be tuned further
against real files as they show up — it is not a general-purpose
spreadsheet parser.
"""
import re

from .models import Asset

# Section-header rows with none of these keywords are treated as decorative
# (e.g. a row just listing "HSE/Compliance/Operations" as a preview of what
# follows) rather than a location update, since every real data row already
# carries its own department value.
_FLOOR_KEYWORDS = ('floor', 'ground', 'annex', 'building', 'basement', 'mezzanine', 'office', 'block')

# Header row must contain at least one alias of each of these keys (case-
# insensitive, exact cell match) — narrow enough to not misfire on a
# banner/title row. Driven by _HEADER_ALIASES below rather than a hardcoded
# word list, so a header using an accepted synonym (e.g. "Item" instead of
# "Device") is still recognized.
_REQUIRED_HEADER_ALIAS_KEYS = ('device', 'tag')

_HEADER_ALIASES = {
    'sn': ['s/n', 'sn', 'sn', 's.n'],
    'user': ['user', 'name'],
    'department': ['department', 'dept'],
    'device': ['device', 'item'],
    'tag': ['tag', 'asset tag'],
    'track_no': ['track #no', 'track#no', 'track no', 'track_no', 'track#'],
    'active': ['active'],
    'not_active': ['not active'],
    'comments': ['comments', 'comment'],
}


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _find_header_row(raw_rows):
    for idx, row in enumerate(raw_rows):
        cells = {str(c).strip().lower() for c in row if not _is_blank(c)}
        if all(
            any(alias in cells for alias in _HEADER_ALIASES[key])
            for key in _REQUIRED_HEADER_ALIAS_KEYS
        ):
            return idx, row
    return None, None


def _build_column_index(header_row):
    lowered = [str(c).strip().lower() if c is not None else '' for c in header_row]
    index = {}
    for key, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                index[key] = lowered.index(alias)
                break
    return index


def _looks_like_location(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in _FLOOR_KEYWORDS)


def transform_raw_rows(raw_rows):
    """raw_rows: list of row tuples/lists, values only, in original sheet
    order (including the title banner, the real header row, section-header
    rows, and every data row). Returns a flat list of dicts:

        {name, category_name, tracking_id, track_no, department_name,
         location_name, assigned_to_name, status_hint, notes}

    where status_hint is 'ACTIVE' / 'NOT_ACTIVE' / '' — mapped to a real
    Asset.Status by resolve_status_hint(), kept separate here so the
    preview can show the raw signal untouched.
    """
    header_idx, header_row = _find_header_row(raw_rows)
    if header_row is None:
        return []

    col = _build_column_index(header_row)

    def cell(row, key):
        i = col.get(key)
        if i is None or i >= len(row):
            return None
        return row[i]

    normalized = []
    current_location = ''
    current_user = ''
    current_status_hint = ''
    current_comments = ''

    # A floor/building label can appear above the column-header row (e.g.
    # after a title banner but before "S/n | USER | ..."), in which case it
    # would otherwise never be seen since scanning starts after the header.
    for row in raw_rows[:header_idx]:
        for value in row:
            if _is_blank(value):
                continue
            text = str(value).strip()
            if _looks_like_location(text):
                current_location = text

    for row in raw_rows[header_idx + 1:]:
        if all(_is_blank(v) for v in row):
            continue

        device = cell(row, 'device')
        tag = cell(row, 'tag')
        no_device = _is_blank(device) and _is_blank(tag)

        if no_device:
            # A location banner is often typed into column A of its row —
            # the same position the S/n column occupies — so check for
            # floor/building text before treating the row as a bundle
            # start below, otherwise a location marker like "Ground Floor"
            # would be misread as a person's S/n value.
            location_text = None
            for value in row:
                if _is_blank(value):
                    continue
                text = str(value).strip()
                if _looks_like_location(text):
                    location_text = text
                    break
            if location_text:
                current_location = location_text
                continue

        sn = cell(row, 'sn')
        user = cell(row, 'user')
        # A non-blank S/n or USER marks the start of a new person's
        # bundle — subsequent rows with both blank inherit this person and
        # this row's status/comments (only a bundle's first row carries
        # them in the source format). Checked ahead of the "no device on
        # this row" branch below so a bundle's first row still updates the
        # current person/status/comments even when that first row itself
        # carries no device (device only appears on the rows under it).
        if not _is_blank(sn) or not _is_blank(user):
            if not _is_blank(user):
                current_user = str(user).strip()
            active = cell(row, 'active')
            not_active = cell(row, 'not_active')
            if not _is_blank(active):
                current_status_hint = 'ACTIVE'
            elif not _is_blank(not_active):
                current_status_hint = 'NOT_ACTIVE'
            else:
                current_status_hint = ''
            comments = cell(row, 'comments')
            current_comments = str(comments).strip() if not _is_blank(comments) else ''

        if no_device:
            # Not a device row and not a location marker either — a purely
            # decorative row (e.g. a department rundown). Nothing left to
            # do with it besides the bundle-start update above.
            continue

        department = cell(row, 'department')
        track_no = cell(row, 'track_no')
        device_name = str(device).strip() if not _is_blank(device) else ''

        normalized.append({
            'name': device_name,
            'category_name': device_name,
            'tracking_id': re.sub(r'\s+', '-', str(tag).strip()) if not _is_blank(tag) else '',
            'track_no': str(track_no).strip() if not _is_blank(track_no) else '',
            'department_name': str(department).strip() if not _is_blank(department) else '',
            'location_name': current_location,
            'assigned_to_name': current_user,
            'status_hint': current_status_hint,
            'notes': current_comments,
        })

    return normalized


def resolve_status_hint(status_hint):
    """Best-effort mapping from the raw Active/Not-Active signal to a real
    Asset.Status — adjustable later if a client's real meaning differs.
    ACTIVE -> IN_USE (someone has it and is using it); NOT_ACTIVE ->
    MAINTENANCE (flagged as not currently working, needs attention); no
    signal at all -> IN_STORE (the model's own default)."""
    if status_hint == 'ACTIVE':
        return Asset.Status.IN_USE
    if status_hint == 'NOT_ACTIVE':
        return Asset.Status.MAINTENANCE
    return Asset.Status.IN_STORE


def parse_track_no_slot(track_no):
    """Extract the trailing numeric slot from a short tag code like
    'ACC008' -> 8, or None if it doesn't end in digits."""
    if not track_no:
        return None
    match = re.search(r'(\d+)$', track_no)
    return int(match.group(1)) if match else None
