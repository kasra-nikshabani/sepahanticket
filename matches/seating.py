"""Project saved hall geometry onto live purchase inventory without changing seat IDs."""
from accounts.venue_layout import curve_padding, curve_point


def purchase_rows(rows, layout, block_name):
    section = next((section for section in layout.get('sections', [])
                    if section.get('name') == block_name), {})
    saved_rows = {row['number']: row for row in section.get('rows', [])}
    result = []
    for row in rows:
        saved = saved_rows.get(row['row_number'], {})
        seats = {seat['number']: seat for seat in row['seats']}
        positions = saved.get('seats') or list(seats)
        curvature = saved.get('curvature', 0)
        cells, seen = [], set()
        for index, number in enumerate(positions):
            seat = seats.get(number)
            if seat is None:
                cells.append(None)
            else:
                cells.append({**seat, **curve_point(curvature, index, len(positions))})
                seen.add(number)
        # Keep live seats visible if the saved plan predates an admin inventory change.
        cells.extend({**seat, 'y': 0, 'angle': 0}
                     for number, seat in seats.items() if number not in seen)
        result.append({**row, 'cells': cells, 'alignment': saved.get('alignment', 'center'),
                       'offset': saved.get('offset', 0),
                       **curve_padding(curvature, len(positions))})
    return result
