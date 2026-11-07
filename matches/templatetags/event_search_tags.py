from django import template
from matches.event_search import CATEGORIES, PERIODS, public_cities, search_options

register = template.Library()


@register.inclusion_tag('events/_search.html', takes_context=True)
def event_search_box(context):
    request = context.get('request')
    match = getattr(request, 'resolver_match', None)
    params = request.GET if match and match.view_name in ('matches:home', 'matches:event_catalogue') else {}
    return {'search': search_options(params), 'search_cities': public_cities(),
            'search_categories': CATEGORIES, 'search_periods': PERIODS}
