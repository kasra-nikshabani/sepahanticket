"""Cross-feature totals, calendar boundaries and staff-only overview queries."""
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from artists.models import ArtistProfile, CollaborationOpportunity, CollaborationReport
from education.models import Course, Enrollment, Lesson
from matches.models import Block, Event, Match, Row, Seat, Stadium
from studios.models import Booking, Studio, StudioSlot
from tickets.models import Ticket
from wallet.models import Transaction, Wallet
from .models import EventSubmission, SiteSettings, SupportTicket, User


@override_settings(CULTURAL_PLATFORM=True, SESSION_COOKIE_SECURE=False, TIME_ZONE='Asia/Tehran')
class ManagementOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.make_aware(datetime(2026, 10, 10, 12))
        cls.midnight = timezone.make_aware(datetime(2026, 10, 10))
        with patch('django.utils.timezone.now', return_value=cls.now):
            cls.admin = User.objects.create_user(username='overview-admin', is_staff=True, is_superuser=True, user_type='admin')
            cls.owners = [User.objects.create_user(username=f'overview-owner-{i}') for i in range(6)]
            cls.owner, cls.buyer = cls.owners[:2]
            cls.inactive = User.objects.create_user(username='overview-inactive', is_active=False)
            cls.venue = Stadium.objects.create(name='سالن نمای کلی', capacity=8)
            block = Block.objects.create(stadium=cls.venue, name='همکف')
            row = Row.objects.create(block=block, number=1)
            seats = [Seat.objects.create(row=row, number=i) for i in range(1, 6)]
            cls.event = Event.objects.create(title='نمایش نمونه', category='theater')
            cls.session = Match.objects.create(event=cls.event, stadium=cls.venue, date_time=cls.now+timedelta(days=3))
            sport = Event.objects.create(title='خارج از سامانهٔ فرهنگی', category='sport')
            sport_session = Match.objects.create(event=sport, stadium=cls.venue, date_time=cls.now+timedelta(days=4))
            Ticket.objects.bulk_create([
                Ticket(user=cls.buyer, match=cls.session, seat=seats[0], full_name='خریدار بلیط', price=1200000, status='paid'),
                Ticket(user=cls.buyer, match=cls.session, seat=seats[1], full_name='خریدار رایگان', price=0, status='paid'),
                Ticket(user=cls.buyer, match=cls.session, seat=seats[2], price=99000000, status='cancelled'),
                Ticket(user=cls.buyer, match=cls.session, seat=seats[3], price=88000000, status='admin_assigned'),
                Ticket(user=cls.buyer, match=cls.session, seat=seats[4], price=77000000, status='pending'),
                Ticket(user=cls.buyer, match=sport_session, seat=seats[0], price=66000000, status='paid'),
            ])
            cls.paid_ticket = Ticket.objects.get(match=cls.session, status='paid', price=1200000)
            Ticket.objects.filter(pk=cls.paid_ticket.pk).update(purchase_date=cls.midnight+timedelta(minutes=15))
            cls.course = Course.objects.create(owner=cls.owner, title='آموزش منتشرشده', kind='recorded', status='published')
            free_course = Course.objects.create(owner=cls.owner, title='آموزش رایگان', kind='recorded', status='published')
            refunded_course = Course.objects.create(owner=cls.owner, title='آموزش بازپرداخت‌شده', kind='recorded')
            cls.enrollment = Enrollment.objects.create(course=cls.course, learner=cls.buyer, course_title=cls.course.title, learner_name='هنرجوی امروز', paid_rial=3000000)
            old = Enrollment.objects.create(course=cls.course, learner=cls.owners[2], course_title=cls.course.title, paid_rial=4000000)
            Enrollment.objects.filter(pk=old.pk).update(purchased_at=cls.now-timedelta(days=45))
            free = Enrollment.objects.create(course=free_course, learner=cls.buyer, course_title=free_course.title, paid_rial=0)
            Enrollment.objects.filter(pk=free.pk).update(purchased_at=cls.now-timedelta(days=1))
            Enrollment.objects.create(course=refunded_course, learner=cls.buyer, course_title=refunded_course.title, status='refunded', paid_rial=55000000)
            cls.studio = Studio.objects.create(owner=cls.owner, title='پلاتوی منتشرشده', status='published', booking_open=True)
            cls.booking = Booking.objects.create(studio=cls.studio, renter=cls.buyer, studio_title=cls.studio.title,
                renter_name='رزروکننده', starts_at=cls.now+timedelta(days=1), ends_at=cls.now+timedelta(days=1, hours=1), hours=1, paid_rial=2000000)
            old_booking = Booking.objects.create(studio=cls.studio, renter=cls.buyer, studio_title=cls.studio.title,
                starts_at=cls.now+timedelta(days=2), ends_at=cls.now+timedelta(days=2, hours=1), hours=1, paid_rial=8000000)
            Booking.objects.filter(pk=old_booking.pk).update(created_at=cls.now-timedelta(days=20))
            Booking.objects.create(studio=cls.studio, renter=cls.buyer, studio_title='رزرو لغوشده',
                starts_at=cls.now+timedelta(days=1), ends_at=cls.now+timedelta(days=1, hours=1), hours=1, paid_rial=44000000, status='cancelled')
            cls.submission = EventSubmission.objects.create(owner=cls.owner, title='درخواست نمایش', category='theater', status='submitted', submitted_at=cls.now-timedelta(days=3))
            cls.pending_course = Course.objects.create(owner=cls.owner, title='درخواست آموزش', kind='recorded', status='pending', submitted_at=cls.now-timedelta(days=2))
            cls.pending_studio = Studio.objects.create(owner=cls.owner, title='درخواست پلاتو', status='pending', submitted_at=cls.now-timedelta(days=1))
            cls.pending_artist = ArtistProfile.objects.create(owner=cls.owners[2], display_name='درخواست هنرمند', status='pending')
            ArtistProfile.objects.filter(pk=cls.pending_artist.pk).update(updated_at=cls.now-timedelta(days=4))
            cls.pending_opportunity = CollaborationOpportunity.objects.create(owner=cls.owner, title='درخواست فراخوان', status='pending')
            CollaborationOpportunity.objects.filter(pk=cls.pending_opportunity.pk).update(updated_at=cls.now-timedelta(days=5))
            cls.open_opportunity = CollaborationOpportunity.objects.create(owner=cls.owner, title='فراخوان باز', status='published', deadline=cls.now.date())
            CollaborationOpportunity.objects.create(owner=cls.owner, title='فراخوان پایان‌یافته', status='published', deadline=cls.now.date()-timedelta(days=1))
            CollaborationOpportunity.objects.create(owner=cls.inactive, title='فراخوان غیرفعال', status='published', deadline=cls.now.date()+timedelta(days=5))
            CollaborationReport.objects.create(opportunity=cls.open_opportunity, reporter=cls.buyer, reason='گزارش باز')
            CollaborationReport.objects.create(opportunity=cls.open_opportunity, reporter=cls.buyer, reason='گزارش رسیدگی‌شده', resolved_at=cls.now)
            cls.support = SupportTicket.objects.create(requester=cls.buyer, category='general', subject='پشتیبانی کاربران')
            SupportTicket.objects.create(requester=cls.buyer, category='program', studio=cls.studio, subject='پشتیبانی رزرو')
            SupportTicket.objects.create(requester=cls.buyer, category='general', subject='تیکت بسته‌شده', status='closed')
            cls.failed = Lesson.objects.create(course=cls.pending_course, title='فایل ناموفق', state='failed', source='private.mp4')
            Lesson.objects.create(course=refunded_course, title='فایل پیش‌نویس ناموفق', state='failed', source='draft.mp4')
            Lesson.objects.create(course=cls.course, title='فایل در صف', state='queued', source='queued.mp4')
            cls.in_person = Course.objects.create(owner=cls.owner, title='کلاس آینده', kind='class', status='published', start_date=(cls.now+timedelta(days=2)).date(), start_time=time(10))

    def setUp(self):
        cache.clear(); SiteSettings._local_cache=(0.0, None)
        SiteSettings.get_solo()
        self.client.force_login(self.admin)
        self.frozen=patch('django.utils.timezone.now', return_value=self.now)
        self.frozen.start(); self.addCleanup(self.frozen.stop)

    def overview(self, **params):
        response=self.client.get(reverse('management:dashboard'), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_totals_combine_rial_snapshots_and_exclude_other_states_and_sports(self):
        response=self.overview()
        finance=response.context['finance']
        self.assertEqual(finance['total_revenue'], 18200000)
        self.assertEqual(finance['total_count'], 7)
        self.assertEqual(finance['today_revenue'], 6200000)
        self.assertEqual(finance['today_count'], 4)
        self.assertEqual(finance['period_revenue'], 6200000)
        self.assertEqual(finance['period_count'], 5)
        self.assertEqual([c['revenue'] for c in finance['channels']], [1200000,7000000,10000000])
        self.assertContains(response,'۱٬۸۲۰٬۰۰۰')
        self.assertNotContains(response,'خارج از سامانهٔ فرهنگی')

    def test_period_and_local_midnight_chart_have_complete_dates_and_real_totals(self):
        response=self.overview(days='30')
        self.assertEqual(response.context['overview_days'],30)
        self.assertEqual(response.context['finance']['period_revenue'],14200000)
        chart=response.context['overview_chart']; self.assertEqual(len(chart),30)
        self.assertEqual(chart[-1]['day'].date(),self.now.date())
        self.assertEqual(chart[-1]['revenue'],6200000)
        self.assertEqual(chart[-1]['count'],4)
        self.assertEqual(sum(day['revenue'] for day in chart),14200000)
        self.assertContains(response,'۱۴۰۵/۰۷/۱۸')
        self.assertEqual(self.overview(days='999').context['overview_days'],7)

    def test_report_window_includes_start_and_excludes_next_midnight(self):
        start=self.midnight-timedelta(days=6)
        Ticket.objects.filter(pk=self.paid_ticket.pk).update(purchase_date=start)
        self.assertEqual(self.overview().context['overview_chart'][0]['ticket'],1200000)
        Ticket.objects.filter(pk=self.paid_ticket.pk).update(purchase_date=start-timedelta(microseconds=1))
        self.assertEqual(self.overview().context['finance']['period_revenue'],5000000)
        Ticket.objects.filter(pk=self.paid_ticket.pk).update(purchase_date=self.midnight+timedelta(days=1))
        self.assertEqual(self.overview().context['finance']['period_revenue'],5000000)

    def test_pending_work_is_separated_and_oldest_publication_first(self):
        response=self.overview()
        self.assertEqual(response.context['publication_count'],5)
        self.assertEqual(response.context['attention_count'],9)
        self.assertEqual(response.context['pending_total'],8)
        self.assertEqual([r['kind'] for r in response.context['review_queue']],['فراخوان','هنرمند','برنامه','آموزش','پلاتو'])
        self.assertEqual(response.context['failed_lesson_count'],1)
        self.assertEqual(response.context['processing_lesson_count'],1)
        self.assertNotContains(response,'فایل پیش‌نویس ناموفق')
        for item in response.context['attention']:
            with self.subTest(url=item['url']): self.assertEqual(self.client.get(item['url']).status_code,200)
        for item in response.context['review_queue']:
            with self.subTest(url=item['url']): self.assertEqual(self.client.get(item['url']).status_code,200)

    def test_public_metrics_exclude_hidden_inactive_and_closed_inventory(self):
        ArtistProfile.objects.create(owner=self.owners[3], display_name='هنرمند عمومی', status='approved', looking_for_work=True)
        ArtistProfile.objects.create(owner=self.owners[4], display_name='هنرمند پنهان', status='approved', looking_for_work=True, is_visible=False)
        ArtistProfile.objects.create(owner=self.inactive, display_name='هنرمند غیرفعال', status='approved', looking_for_work=True)
        inactive_studio=Studio.objects.create(owner=self.inactive,title='پلاتوی حساب غیرفعال',status='published')
        for i,state,booking,studio in [(1,'open',None,self.studio),(2,'closed',None,self.studio),(3,'open',self.booking,self.studio),(4,'open',None,inactive_studio),(5,'open',None,self.pending_studio)]:
            StudioSlot.objects.create(studio=studio,starts_at=self.now+timedelta(days=4,hours=i),ends_at=self.now+timedelta(days=4,hours=i+1),state=state,booking=booking,price_toman=100)
        response=self.overview()
        metrics={item['title']:{metric['label']:metric['value'] for metric in item['metrics']} for item in response.context['modules']}
        self.assertEqual(metrics['هنرمندان']['پروفایل عمومی'],1)
        self.assertEqual(metrics['هنرمندان']['آمادهٔ همکاری'],1)
        self.assertEqual(metrics['پلاتو']['پلاتو منتشرشده'],1)
        self.assertEqual(metrics['پلاتو']['ساعت قابل رزرو'],1)
        self.assertEqual(metrics['فرصت‌های همکاری']['فراخوان باز'],1)
        self.assertEqual(metrics['پشتیبانی']['تیکت منتظر پاسخ'],2)

    def test_recent_sales_and_upcoming_are_sorted_across_all_features(self):
        response=self.overview()
        self.assertEqual({item['key'] for item in response.context['recent_sales']},{'ticket','education','studio'})
        self.assertNotContains(response,'آموزش بازپرداخت‌شده')
        self.assertNotContains(response,'رزرو لغوشده')
        upcoming=response.context['upcoming']
        self.assertEqual({item['kind'] for item in upcoming},{'سانس برنامه','آغاز کلاس','رزرو پلاتو'})
        self.assertEqual([item['date'] for item in upcoming],sorted(item['date'] for item in upcoming))

    def test_staff_only_no_cache_and_no_business_changes_on_get_or_post(self):
        models=[Ticket,Enrollment,Booking,Transaction,Wallet,EventSubmission,SupportTicket,LogEntry]
        before=[model.objects.count() for model in models]
        response=self.overview(); self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.post(reverse('management:dashboard'),{'action':'approve'}).status_code,405)
        self.assertEqual([model.objects.count() for model in models],before)
        for client in [Client(),self.client]:
            if client is self.client: client.force_login(self.buyer)
            self.assertEqual(client.get(reverse('management:dashboard')).status_code,302)

    def test_queue_sizes_and_queries_stay_bounded_as_records_grow(self):
        self.overview()
        with CaptureQueriesContext(connection) as first: self.overview()
        for i in range(16):
            Course.objects.create(owner=self.owner,title=f'آموزش منتظر {i}',kind='recorded',status='pending')
            Lesson.objects.create(course=self.pending_course,title=f'فایل ناموفق {i}',source='private.mp4',state='failed')
        with CaptureQueriesContext(connection) as second: response=self.overview()
        self.assertLessEqual(len(second),len(first)+1)
        self.assertLessEqual(len(second),65)
        self.assertLessEqual(len(response.context['review_queue']),6)
        self.assertEqual(len(response.context['failed_lessons']),3)
        self.assertLessEqual(len(response.context['recent_sales']),6)


@override_settings(CULTURAL_PLATFORM=True, SESSION_COOKIE_SECURE=False)
class EmptyManagementOverviewTests(TestCase):
    def test_empty_platform_has_zero_totals_and_complete_empty_states(self):
        cache.clear(); SiteSettings._local_cache=(0.0,None)
        admin=User.objects.create_user(username='empty-overview-admin',is_staff=True,is_superuser=True,user_type='admin')
        self.client.force_login(admin)
        response=self.client.get(reverse('management:dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['finance']['total_revenue'],0)
        self.assertEqual(response.context['attention_count'],0)
        self.assertEqual(response.context['overview_users']['total'],0)
        self.assertEqual(len(response.context['overview_chart']),7)
        self.assertTrue(all(day['height']==0 for day in response.context['overview_chart']))
        self.assertContains(response,'خرید یا رزروی ثبت نشده است')
        self.assertContains(response,'درخواست انتشاری در انتظار نیست')
