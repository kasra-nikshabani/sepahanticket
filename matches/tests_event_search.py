from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from artists.models import ArtistCredit, ArtistProfile
from .models import Event, EventRating, Match, Stadium


class DiscoverySearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        cls.venue = Stadium.objects.create(name='تماشاخانهٔ کِیان', city='تهران', capacity=0)
        cls.other_venue = Stadium.objects.create(name='سالن فردا', city='اصفهان', capacity=0)
        cls.event = Event.objects.create(title='یک دیدار ۱۲', artists='هنرمند نمونه', organizer='گروه آبی', category='theater')
        cls.session = Match.objects.create(event=cls.event, stadium=cls.venue, date_time=cls.now + timedelta(days=2))
        cls.user = get_user_model().objects.create_user(username='search-fixture', email='private-account@example.test')
        cls.artist = ArtistProfile.objects.create(owner=cls.user, display_name='کسری هنرمند', city='تهران', specialty='کارگردان', status='approved')
        cls.catalogue = reverse('matches:event_catalogue')
        cls.api = reverse('matches:search_suggestions')

    def results(self, **params):
        return self.client.get(self.catalogue, params).context['page_obj'].object_list

    def test_normalizes_arabic_letters_diacritics_spaces_and_digits(self):
        for query in ('يك ديدار 12', 'یَک دیدار ١٢', 'یک\u200cدیدار ۱۲', '  یک    دیدار 12 '):
            with self.subTest(query=query):
                self.assertEqual([event.pk for event in self.results(q=query)], [self.event.pk])
        self.assertEqual(self.client.get(self.api, {'q': 'يك ديدار 12'}).json()['events'][0]['title'], self.event.title)

    def test_terms_can_match_title_artist_organizer_venue_and_city_together(self):
        for query in ('دیدار تهران', 'دیدار كيان', 'هنرمند آبی', 'تماشاخانه'):
            self.assertEqual([event.pk for event in self.results(q=query)], [self.event.pk])
        self.assertEqual(list(self.results(q='دیدار ناموجود')), [])

    def test_exact_title_precedes_prefix_and_artist_only_matches(self):
        exact = Event.objects.create(title='دیدار', category='theater')
        prefix = Event.objects.create(title='دیدار تازه', category='theater')
        indirect = Event.objects.create(title='برنامه دیگر', artists='دیدار', category='theater')
        ordered = [event.pk for event in self.results(q='دیدار')]
        self.assertEqual(ordered[:2], [exact.pk, prefix.pk])
        self.assertGreater(ordered.index(indirect.pk), ordered.index(self.event.pk))
        suggested = self.client.get(self.api, {'q': 'دیدار'}).json()['events']
        self.assertEqual(suggested[0]['title'], exact.title)

    def test_city_and_date_must_match_the_same_session(self):
        Match.objects.create(event=self.event, stadium=self.other_venue, date_time=self.now + timedelta(days=15))
        self.assertEqual(list(self.results(q='دیدار', city='اصفهان', period='week')), [])
        self.assertEqual(len(self.results(q='دیدار', city='اصفهان', period='month')), 1)
        self.assertEqual(self.client.get(self.api, {'q': 'دیدار', 'city': 'اصفهان', 'period': 'week'}).json()['events'], [])

    def test_today_boundary_uses_local_midnight(self):
        tomorrow = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        self.session.date_time = tomorrow
        self.session.save()
        self.assertEqual(list(self.results(q='دیدار', period='today')), [])
        self.session.date_time = timezone.now() + (tomorrow-timezone.now()) / 2
        self.session.save()
        self.assertEqual(len(self.results(q='دیدار', period='today')), 1)

    def test_filters_and_suggestions_never_expose_hidden_or_sport_events(self):
        for title, fields in [('دیدار مخفی', {'is_active': False}), ('دیدار ورزشی', {'category': 'sport'})]:
            event = Event.objects.create(title=title, **fields)
            Match.objects.create(event=event, stadium=self.venue, date_time=self.now+timedelta(days=1))
        data = self.client.get(self.api, {'q': 'دیدار'}).json()
        self.assertEqual([item['title'] for item in data['events']], [self.event.title])
        self.assertEqual(len(self.results(q='دیدار', sort='new')), 1)

    def test_past_only_and_cancelled_sessions_are_not_suggested(self):
        self.session.date_time = timezone.now()-timedelta(days=1)
        self.session.save()
        self.assertEqual(self.client.get(self.api, {'q': 'دیدار'}).json()['events'], [])
        self.session.date_time = self.now+timedelta(days=2)
        self.session.is_cancelled = True
        self.session.save()
        self.assertEqual(self.client.get(self.api, {'q': 'دیدار'}).json()['events'], [])

    def test_announced_programmes_without_sessions_are_searchable(self):
        event = Event.objects.create(title='اعلان تازه', category='concert')
        self.assertEqual([item.pk for item in self.results(q='اعلان')], [event.pk])
        self.assertEqual(self.client.get(self.api, {'q': 'اعلان'}).json()['events'][0]['venue'], 'سانس‌ها به‌زودی اعلام می‌شوند')
        self.assertEqual(list(self.results(q='اعلان', city='تهران')), [])

    def test_only_public_confirmed_artist_credits_are_searchable(self):
        credit = ArtistCredit.objects.create(event=self.event, artist=self.artist, role='کارگردان', status='pending')
        self.assertEqual(list(self.results(q='کسری')), [])
        credit.status = 'accepted'; credit.save()
        self.assertEqual(len(self.results(q='كسري')), 1)
        self.artist.is_visible=False; self.artist.save()
        self.assertEqual(list(self.results(q='کسری')), [])
        self.assertEqual(self.client.get(self.api, {'q': 'کسری'}).json()['artists'], [])

    def test_artist_suggestions_exclude_private_and_disabled_profiles(self):
        self.assertEqual(self.client.get(self.api, {'q': 'کسری'}).json()['artists'][0]['title'], self.artist.display_name)
        for fields in ({'status': 'pending'}, {'is_visible': False}):
            ArtistProfile.objects.filter(pk=self.artist.pk).update(**fields)
            self.assertEqual(self.client.get(self.api, {'q': 'کسری'}).json()['artists'], [])
            ArtistProfile.objects.filter(pk=self.artist.pk).update(status='approved', is_visible=True)
        self.user.is_active=False; self.user.save()
        self.assertEqual(self.client.get(self.api, {'q': 'کسری'}).json()['artists'], [])

    def test_programme_filters_apply_to_artist_suggestions(self):
        self.assertEqual(self.client.get(self.api, {'q': 'کسری', 'category': 'concert'}).json()['artists'], [])
        ArtistCredit.objects.create(event=self.event, artist=self.artist, role='کارگردان', status='accepted')
        self.assertEqual(len(self.client.get(self.api, {'q': 'کسری', 'city': 'تهران', 'period': 'week'}).json()['artists']), 1)
        self.assertEqual(self.client.get(self.api, {'q': 'کسری', 'city': 'اصفهان'}).json()['artists'], [])

    def test_artist_directory_continues_the_same_normalized_search(self):
        response = self.client.get(reverse('artists:directory'), {'q': 'كسري كارگردان تهران'})
        self.assertEqual([artist.pk for artist in response.context['page_obj']], [self.artist.pk])
        self.artist.is_visible=False; self.artist.save()
        response = self.client.get(reverse('artists:directory'), {'q': 'كسري'})
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_endpoint_is_bounded_get_only_and_does_not_cache_personal_queries(self):
        for number in range(9):
            Event.objects.create(title=f'دیدار {number}', category='event')
        response = self.client.get(self.api, {'q': 'دیدار'})
        self.assertEqual(len(response.json()['events']), 6)
        self.assertTrue(response.json()['has_more'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('email', response.content.decode())
        self.assertEqual(self.client.post(self.api, {'q': 'دیدار'}).status_code, 405)
        for query in ('', 'ی', '\u200c\u200c'):
            self.assertEqual(self.client.get(self.api, {'q': query}).json()['events'], [])

    def test_rating_sort_uses_real_ratings_without_duplicating_events(self):
        other = Event.objects.create(title='دیدار دوم', category='theater')
        Match.objects.create(event=other, stadium=self.venue, date_time=self.now+timedelta(days=4))
        EventRating.objects.create(event=self.event, user=self.user, score=4)
        EventRating.objects.create(event=other, user=self.user, score=5)
        items = list(self.results(q='دیدار', sort='rating'))
        self.assertEqual([item.pk for item in items], [other.pk, self.event.pk])
        self.assertEqual(items[0].rating_average, 5)

    def test_filter_removal_preserves_other_filters_and_sanitizes_parameters(self):
        response = self.client.get(self.catalogue, {'q': 'دیدار', 'category': 'theater', 'city': 'تهران', 'period': 'week', 'page': 100, 'unknown': 'private'})
        city_chip = next(chip for chip in response.context['active_filters'] if chip['label'].startswith('شهر:'))
        params = parse_qs(urlsplit(city_chip['url']).query)
        self.assertEqual(params['q'], ['دیدار'])
        self.assertEqual(params['period'], ['week'])
        self.assertNotIn('city', params)
        self.assertNotIn('page', params)
        self.assertNotIn('unknown', response.context['filter_query'])
        response = self.client.get(self.catalogue, {'q': 'دیدار', 'category': 'invalid', 'sort': 'invalid', 'period': 'invalid'})
        self.assertEqual(response.context['selected_sort'], 'relevance')
        self.assertEqual(response.context['selected_period'], '')
        self.assertEqual(response.context['selected_category'], '')

    def test_city_choices_only_include_public_upcoming_programmes(self):
        secret = Stadium.objects.create(name='سالن خصوصی', city='شهر خصوصی', capacity=0)
        hidden = Event.objects.create(title='پیش‌نویس', is_active=False)
        Match.objects.create(event=hidden, stadium=secret, date_time=self.now+timedelta(days=1))
        response = self.client.get(reverse('matches:home'))
        self.assertNotContains(response, 'شهر خصوصی')
        self.assertContains(response, 'discovery-panel')
        self.assertNotContains(response, 'filter-sidebar')

    def test_query_html_is_escaped_and_private_account_fields_are_not_searched(self):
        response = self.client.get(self.catalogue, {'q': '<script>alert(1)</script>'})
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertEqual(list(self.results(q='private-account@example.test')), [])
        self.assertEqual(self.client.get(self.api, {'q': 'private-account@example.test'}).json()['artists'], [])
