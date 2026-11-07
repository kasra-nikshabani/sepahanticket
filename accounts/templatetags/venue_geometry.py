from django import template
from accounts.venue_layout import curve_point, curve_padding

register = template.Library()


@register.filter
def curved_row(row):
    seats = row.get('seats', [])
    curvature = row.get('curvature', 0)
    return {**curve_padding(curvature, len(seats)), 'cells': [
        {'number': number, **curve_point(curvature, index, len(seats))}
        for index, number in enumerate(seats)]}
