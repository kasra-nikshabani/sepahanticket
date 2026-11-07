import io
import tempfile
import uuid
from datetime import time,timedelta
from unittest.mock import patch
import jdatetime
from PIL import Image
from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,TransactionTestCase,Client,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User,SiteSettings,SupportTicket,Notification
from wallet.models import Wallet,Transaction
from .models import Studio,StudioSlot,Booking,StudioPhoto
from .forms import StudioForm,ScheduleForm
from .services import book_slots,build_schedule,change_slot,cancel_booking,publication_errors


def jalali(day): return jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d')


@override_settings(CULTURAL_PLATFORM=True,SESSION_COOKIE_SECURE=False)
class StudioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(username='studio-owner',password='test',first_name='صاحب',last_name='پلاتو')
        cls.renter=User.objects.create_user(username='studio-renter',password='test',first_name='هنرمند',last_name='نمونه',phone_number='09121112345')
        cls.other=User.objects.create_user(username='studio-other',password='test')
        cls.admin=User.objects.create_user(username='studio-admin',password='test',is_staff=True,is_superuser=True,user_type='admin')
        cls.studio=Studio.objects.create(owner=cls.owner,title='پلاتوی تمرین',city='تهران',district='مرکز',address='نشانی واقعی پلاتو',description='فضای تمرین هنری',amenities='آینه و سیستم صوت',rules='ورود سر ساعت',area=80,capacity=15,hourly_price=100,cover='studios/example.jpg',status='published',published_at=timezone.now())
        cls.day=timezone.localdate()+timedelta(days=7)
        build_schedule(cls.studio.pk,cls.day,cls.day,time(10),time(15),[cls.day.weekday()],100)

    def setUp(self):
        cache.clear();SiteSettings._local_cache=(0.0,None)
        settings=SiteSettings.get_solo();settings.wallet_enabled=True;settings.wallet_charge_enabled=True;settings.save()
        Wallet.objects.filter(user=self.renter).update(balance=100000)
        Wallet.objects.filter(user=self.other).update(balance=100000)
        self.client.force_login(self.renter)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.temp.name);self.override.enable();self.addCleanup(self.override.disable)
        self.studio.refresh_from_db()

    def slots(self): return list(self.studio.slots.values_list('pk',flat=True))
    def book(self,ids=None,user=None,total=None,token=None):
        ids=ids or self.slots()[:2]
        return book_slots(user or self.renter,self.studio.pk,ids,total if total is not None else 100*len(ids),'نام اعلامی رزروکننده',token or uuid.uuid4())[0]
    def review(self,action,note='پیام مدیریت',**data):
        self.studio.refresh_from_db()
        return self.client.post(reverse('management:studio_detail',args=[self.studio.pk]),{'version':self.studio.updated_at.isoformat(),'action':action,'note':note,**data})

    def test_public_catalogue_only_approved_active_owner(self):
        Studio.objects.create(owner=self.owner,title='محرمانه',status='pending')
        response=self.client.get(reverse('studios:catalogue'))
        self.assertContains(response,self.studio.title);self.assertNotContains(response,'محرمانه')
        self.owner.is_active=False;self.owner.save()
        self.assertNotContains(self.client.get(reverse('studios:catalogue')),self.studio.title)

    def test_calendar_renders_jalali_dates_and_changes_selected_day(self):
        from urllib.parse import quote
        from tickets.templatetags.persian_filters import to_persian
        for route in [self.studio.get_absolute_url(),reverse('studios:manage',args=[self.studio.pk])]:
            if 'manage' in route: self.client.force_login(self.owner)
            response=self.client.get(route)
            expected=jalali(self.day)
            self.assertContains(response,to_persian(expected))
            self.assertContains(response,'?day='+quote(expected,safe='/')+'#studio-calendar')
            self.assertNotContains(response,'?day=#studio-calendar')
            tomorrow=self.day+timedelta(days=1)
            response=self.client.get(route,{'day':to_persian(jalali(tomorrow))})
            if 'manage' in route:
                self.assertContains(response,'value="'+to_persian(jalali(tomorrow))+'"')
                self.assertEqual(response.context['selected_day'].date(),tomorrow)
            else:
                self.assertEqual(response.context['selected_day'].date(), self.day)
                self.assertEqual([day.date() for day in response.context['calendar_days']], [self.day])
                self.assertNotContains(response, 'id="studio-day"')
                fragment = self.client.get(route, HTTP_X_STUDIO_CALENDAR='1')
                self.assertContains(fragment, 'data-ajax-calendar')
                self.assertNotContains(fragment, '<html')

    def test_normalized_persian_search_city_and_empty_result(self):
        response=self.client.get(reverse('studios:catalogue'),{'q':'آینه','city':'تهران'})
        self.assertContains(response,self.studio.title)
        self.assertNotContains(self.client.get(reverse('studios:catalogue'),{'q':'ناموجود'}),self.studio.title)

    def test_draft_private_except_owner_admin(self):
        self.studio.status='draft';self.studio.save()
        self.assertEqual(self.client.get(self.studio.get_absolute_url()).status_code,404)
        self.client.force_login(self.owner);self.assertEqual(self.client.get(self.studio.get_absolute_url()).status_code,200)

    def test_owner_only_management_and_slot_edit(self):
        self.assertEqual(self.client.get(reverse('studios:manage',args=[self.studio.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('studios:slot_edit',args=[self.studio.pk,self.slots()[0]]),{'state':'closed','price':100}).status_code,404)

    def test_images_and_gallery_saved_and_submit_needs_complete_info(self):
        self.client.force_login(self.owner)
        data=io.BytesIO();Image.new('RGB',(12,12),'green').save(data,format='PNG')
        response=self.client.post(reverse('studios:create'),{'title':'فضای تازه','city':'تهران','hourly_price':'۱۵۰','cover':SimpleUploadedFile('room.png',data.getvalue(),content_type='image/png'),'gallery':[SimpleUploadedFile('detail.png',data.getvalue(),content_type='image/png')]})
        self.assertEqual(response.status_code,302)
        created=Studio.objects.get(title='فضای تازه');self.assertEqual(created.status,'draft');self.assertEqual(created.photos.count(),1)
        self.client.post(reverse('studios:submit',args=[created.pk]));created.refresh_from_db();self.assertEqual(created.status,'draft')

    def test_image_validation_rejects_fake_image(self):
        form=StudioForm({'title':'فضا','hourly_price':100}, {'cover':SimpleUploadedFile('room.png',b'not-an-image',content_type='image/png')})
        self.assertFalse(form.is_valid());self.assertIn('cover',form.errors)

    def test_publication_requires_photo_and_future_schedule(self):
        self.assertEqual(publication_errors(self.studio),[])
        self.studio.cover='';self.assertTrue(publication_errors(self.studio))
        self.studio.cover='image.png';self.studio.slots.update(state='closed');self.assertTrue(publication_errors(self.studio))

    def test_submit_review_revision_notification_and_publish(self):
        self.studio.published_at=None;self.studio.status='draft';self.studio.save()
        self.client.force_login(self.owner)
        self.client.post(reverse('studios:submit',args=[self.studio.pk]));self.studio.refresh_from_db();self.assertEqual(self.studio.status,'pending')
        self.client.force_login(self.admin);self.review('revision')
        self.studio.refresh_from_db();self.assertEqual(self.studio.status,'revision');self.assertTrue(Notification.objects.filter(recipient=self.owner,kind='review').exists())
        self.studio.status='pending';self.studio.save();self.review('approve')
        self.studio.refresh_from_db();self.assertEqual(self.studio.status,'published');self.assertIsNotNone(self.studio.published_at);self.assertTrue(LogEntry.objects.exists())

    def test_review_stale_version_and_missing_reason_rejected(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('management:studio_detail',args=[self.studio.pk]),{'version':'old','action':'pause','note':'پیام'})
        self.assertContains(response,'اطلاعات تغییر کرده')
        response=self.review('pause',note='');self.assertContains(response,'علت تصمیم')
        self.studio.refresh_from_db();self.assertEqual(self.studio.status,'published')

    def test_published_owner_metadata_locked_but_schedule_editable(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('studios:edit',args=[self.studio.pk]),{'title':'تغییر'}).status_code,302)
        self.studio.refresh_from_db();self.assertEqual(self.studio.title,'پلاتوی تمرین')
        self.client.post(reverse('studios:slot_edit',args=[self.studio.pk,self.slots()[0]]),{'state':'blocked','price':'۲۰۰','note':'نام خصوصی'})
        slot=self.studio.slots.first();self.assertEqual(slot.state,'blocked');self.assertEqual(slot.price_toman,200)

    def test_build_schedule_weekdays_and_skip_existing(self):
        original=self.slots();count,skip=build_schedule(self.studio.pk,self.day,self.day,time(10),time(17),[self.day.weekday()],250)
        self.assertEqual((count,skip),(2,5));self.assertEqual(StudioSlot.objects.get(pk=original[0]).price_toman,100)
        self.assertEqual(self.studio.slots.last().price_toman,250)

    def test_schedule_invalid_range_non_hourly_and_no_matching_day(self):
        for args in [(self.day,self.day+timedelta(days=90),time(10),time(12),[self.day.weekday()]),(self.day,self.day,time(10,30),time(12),[self.day.weekday()]),(self.day,self.day,time(13),time(12),[self.day.weekday()]),(self.day,self.day,time(10),time(12),[(self.day.weekday()+1)%7])]:
            with self.assertRaises(ValueError): build_schedule(self.studio.pk,*args,100)
        form=ScheduleForm({'start_date':jalali(self.day),'end_date':jalali(self.day),'weekdays':[str(self.day.weekday())],'start_time':'10:30','end_time':'12:00','price':'۱۰۰'})
        self.assertFalse(form.is_valid())

    def test_paid_booking_rial_conversion_snapshot_and_owner_notification(self):
        booking=self.book();self.assertEqual(booking.paid_rial,2000);self.assertEqual(booking.hours,2);self.assertEqual(booking.slots.count(),2)
        self.assertEqual(Wallet.objects.get(user=self.renter).balance,98000)
        self.assertEqual(Transaction.objects.get(transaction_type='studio_rental').amount,-2000)
        self.assertTrue(Notification.objects.filter(recipient=self.owner,kind='purchase').exists())

    def test_duplicate_request_idempotent_no_second_charge(self):
        token=uuid.uuid4();first=self.book(token=token);second=self.book(token=token)
        self.assertEqual(first.pk,second.pk);self.assertEqual(Booking.objects.count(),1)
        self.assertEqual(Transaction.objects.filter(transaction_type='studio_rental').count(),1)
        with self.assertRaises(ValueError): self.book(ids=self.slots()[2:4],token=token)
        with self.assertRaises(ValueError): self.book(token=token,user=self.other)

    def test_reserved_slot_cannot_be_booked_again_or_changed(self):
        self.book()
        with self.assertRaises(ValueError): self.book(user=self.other)
        with self.assertRaises(ValueError): change_slot(self.studio.pk,self.slots()[0],'blocked',200)
        self.assertEqual(Wallet.objects.get(user=self.other).balance,100000)

    def test_blocked_closed_past_slots_cannot_be_booked(self):
        for state in ['blocked','closed']:
            self.studio.slots.filter(pk=self.slots()[0]).update(state=state)
            with self.assertRaises(ValueError): self.book()
        self.studio.slots.update(state='open')
        slot=self.studio.slots.first();slot.starts_at=timezone.now()-timedelta(hours=2);slot.ends_at=slot.starts_at+timedelta(hours=1);slot.save()
        with self.assertRaises(ValueError): self.book(ids=[slot.pk])

    def test_noncontiguous_duplicate_and_foreign_slots_rejected(self):
        for ids in [[self.slots()[0],self.slots()[2]],[self.slots()[0],self.slots()[0]],[self.slots()[0],9999999]]:
            with self.assertRaises(ValueError): self.book(ids=ids)
        other=Studio.objects.create(owner=self.other,title='پلاتوی دیگر')
        slot=StudioSlot.objects.create(studio=other,starts_at=self.studio.slots.first().starts_at,ends_at=self.studio.slots.first().ends_at,price_toman=100)
        with self.assertRaises(ValueError): self.book(ids=[slot.pk])

    def test_price_change_wallet_disabled_insufficient_balance_no_charge(self):
        with self.assertRaises(ValueError): self.book(total=1)
        Wallet.objects.filter(user=self.renter).update(balance=1)
        with self.assertRaises(ValueError): self.book()
        settings=SiteSettings.get_solo();settings.wallet_enabled=False;settings.save()
        with self.assertRaises(ValueError): self.book()
        self.assertFalse(Booking.objects.exists());self.assertFalse(Transaction.objects.filter(transaction_type='studio_rental').exists())

    def test_owner_paused_inactive_and_closed_booking_rejected(self):
        with self.assertRaises(ValueError): self.book(user=self.owner)
        for changes in [{'status':'paused'},{'status':'published','booking_open':False}]:
            Studio.objects.filter(pk=self.studio.pk).update(**changes)
            with self.assertRaises(ValueError): self.book()
        Studio.objects.filter(pk=self.studio.pk).update(status='published',booking_open=True)
        self.owner.is_active=False;self.owner.save()
        with self.assertRaises(ValueError): self.book()

    def test_refund_once_restores_wallet_and_releases_slots(self):
        booking=self.book();cancel_booking(booking.pk,'تعطیلی پلاتو')
        self.assertEqual(Wallet.objects.get(user=self.renter).balance,100000);self.assertEqual(self.studio.slots.filter(booking__isnull=False).count(),0)
        with self.assertRaises(ValueError): cancel_booking(booking.pk,'دوباره')
        self.assertEqual(Transaction.objects.filter(transaction_type='refund').count(),1)
        self.book(user=self.other)

    def test_failed_slot_claim_rolls_back_payment_and_booking(self):
        from django.db.models.query import QuerySet
        original=QuerySet.update
        def fail_claim(query,*args,**kwargs):
            if query.model==StudioSlot and 'booking' in kwargs:return 0
            return original(query,*args,**kwargs)
        with patch.object(QuerySet,'update',fail_claim):
            with self.assertRaises(ValueError): self.book()
        self.assertFalse(Booking.objects.exists());self.assertEqual(Wallet.objects.get(user=self.renter).balance,100000)
        self.assertFalse(Transaction.objects.filter(transaction_type='studio_rental').exists())

    def test_checkout_uses_post_validates_terms_and_tampering(self):
        url=reverse('studios:checkout',args=[self.studio.pk])
        response=self.client.get(url,{'slots':self.slots()[:2]});self.assertEqual(response.status_code,200)
        token=response.context['form']['token'].value()
        data={'slots':self.slots()[:2],'token':token,'total':'۲۰۰','renter_name':'نام هنرمند'}
        self.assertEqual(self.client.post(url,data).status_code,200);self.assertFalse(Booking.objects.exists())
        data['accept_rules']='on';data['total']='۱'
        self.assertContains(self.client.post(url,data),'قیمت یا ساعت‌های انتخابی تغییر')
        data['total']='۲۰۰';self.assertEqual(self.client.post(url,data).status_code,302);self.assertEqual(Booking.objects.count(),1)

    def test_public_calendar_never_discloses_renter_or_private_note(self):
        booking=self.book();change_slot(self.studio.pk,self.slots()[2],'blocked',100,'یادداشت محرمانه')
        response=Client().get(self.studio.get_absolute_url(),{'day':jalali(self.day)})
        self.assertContains(response,'رزرو شده');self.assertNotContains(response,booking.renter_name);self.assertNotContains(response,'یادداشت محرمانه');self.assertNotContains(response,self.renter.phone_number)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('studios:manage',args=[self.studio.pk]),{'day':jalali(self.day)})
        self.assertContains(response,booking.renter_name);self.assertContains(response,'یادداشت محرمانه')

    def test_pause_preserves_existing_booking_and_private_learner_access(self):
        booking=self.book();self.client.force_login(self.admin);self.review('pause')
        booking.refresh_from_db();self.assertEqual(booking.status,'confirmed')
        self.client.force_login(self.renter);self.assertContains(self.client.get(reverse('studios:my_bookings')),self.studio.title)
        self.assertEqual(self.client.get(self.studio.get_absolute_url()).status_code,200)
        self.assertEqual(Client().get(self.studio.get_absolute_url()).status_code,404)

    def test_panel_staff_only_cross_studio_refund_and_audit(self):
        self.assertEqual(self.client.get(reverse('management:studios')).status_code,302)
        booking=self.book();other=Studio.objects.create(owner=self.other,title='فضای دیگر')
        self.client.force_login(self.admin)
        response=self.client.post(reverse('management:studio_detail',args=[other.pk]),{'version':other.updated_at.isoformat(),'action':'refund','note':'علت','booking_id':str(booking.pk)})
        self.assertEqual(response.status_code,404)
        response=self.client.get(reverse('management:studio_detail',args=[self.studio.pk]))
        from html.parser import HTMLParser
        class VersionParser(HTMLParser):
            versions=[]
            def handle_starttag(parser,tag,attrs):
                attrs=dict(attrs)
                if tag=='input' and attrs.get('name')=='version': parser.versions.append(attrs.get('value'))
        parser=VersionParser();parser.feed(response.content.decode())
        self.studio.refresh_from_db()
        self.assertTrue(parser.versions)
        self.assertTrue(all(value==self.studio.updated_at.isoformat() for value in parser.versions))
        response=self.client.post(reverse('management:studio_detail',args=[self.studio.pk]),{'version':parser.versions[-1],'action':'refund','note':'لغو با هماهنگی','booking_id':booking.pk})
        self.assertEqual(response.status_code,302)
        booking.refresh_from_db();self.assertEqual(booking.status,'cancelled');self.assertTrue(LogEntry.objects.exists())

    def test_support_scoped_owner_or_actual_renter_and_bound_to_studio(self):
        url=reverse('accounts:support_create')+'?studio='+str(self.studio.pk)
        self.assertEqual(self.client.get(url).status_code,404)
        self.book();response=self.client.post(url,{'category':'general','subject':'لغو رزرو','body':'درخواست لغو'})
        self.assertEqual(response.status_code,302)
        ticket=SupportTicket.objects.get();self.assertEqual(ticket.studio,self.studio);self.assertEqual(ticket.category,'program');self.assertIsNone(ticket.event_id)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('management:support_detail',args=[ticket.pk])),reverse('management:studio_detail',args=[self.studio.pk]))
        self.client.force_login(self.other);self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.owner);self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(reverse('accounts:support_create')+'?studio=invalid').status_code,404)

    def test_csrf_and_get_do_not_mutate_or_refund(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('studios:submit',args=[self.studio.pk])).status_code,405)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.renter)
        self.assertEqual(csrf.post(reverse('studios:checkout',args=[self.studio.pk]),{}).status_code,403)
        self.assertFalse(Booking.objects.exists())

    def test_all_pages_render_without_external_services(self):
        self.book()
        for name,args in [('catalogue',[]),('detail',[self.studio.pk]),('my_bookings',[])]:self.assertEqual(self.client.get(reverse('studios:'+name,args=args)).status_code,200)
        self.client.force_login(self.owner)
        for name,args in [('my_studios',[]),('create',[]),('manage',[self.studio.pk]),('slot_edit',[self.studio.pk,self.slots()[2]])]:self.assertEqual(self.client.get(reverse('studios:'+name,args=args)).status_code,200)
        self.client.force_login(self.admin)
        for name,args in [('studios',[]),('studio_detail',[self.studio.pk])]: self.assertEqual(self.client.get(reverse('management:'+name,args=args)).status_code,200)


@override_settings(CULTURAL_PLATFORM=True)
class ConcurrentStudioTests(TransactionTestCase):
    """Exercise two database connections competing for the same inventory/money."""
    def setUp(self):
        cache.clear();SiteSettings._local_cache=(0.0,None)
        settings=SiteSettings.get_solo();settings.wallet_enabled=True;settings.save()
        self.owner=User.objects.create_user(username='concurrent-studio-owner')
        self.a=User.objects.create_user(username='concurrent-studio-a')
        self.b=User.objects.create_user(username='concurrent-studio-b')
        for user in [self.a,self.b]:Wallet.objects.filter(user=user).update(balance=10000)
        self.studio=Studio.objects.create(owner=self.owner,title='فضای همزمانی',status='published')
        starts=timezone.now()+timedelta(days=1)
        self.slot=StudioSlot.objects.create(studio=self.studio,starts_at=starts,ends_at=starts+timedelta(hours=1),price_toman=100)

    def compete(self,operations):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from time import sleep
        from django.db import connections,OperationalError,close_old_connections
        barrier=Barrier(2)
        def run(operation):
            close_old_connections();barrier.wait()
            try:
                for attempt in range(30):
                    try:operation();return 'success'
                    except ValueError:return 'rejected'
                    except OperationalError:
                        if attempt==29:raise
                        sleep(.01)
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run,operations))

    def test_two_users_compete_for_one_slot_only_one_payment(self):
        results=self.compete([lambda:book_slots(self.a,self.studio.pk,[self.slot.pk],100,'هنرمند اول',uuid.uuid4()),
                              lambda:book_slots(self.b,self.studio.pk,[self.slot.pk],100,'هنرمند دوم',uuid.uuid4())])
        self.assertCountEqual(results,['success','rejected'])
        self.assertEqual(Booking.objects.filter(status='confirmed').count(),1)
        self.assertEqual(Transaction.objects.filter(transaction_type='studio_rental').count(),1)
        self.assertEqual(sum(Wallet.objects.get(user=user).balance for user in [self.a,self.b]),19000)

    def test_two_refunds_compete_only_one_credit(self):
        booking=book_slots(self.a,self.studio.pk,[self.slot.pk],100,'هنرمند',uuid.uuid4())[0]
        results=self.compete([lambda:cancel_booking(booking.pk,'لغو اول'),lambda:cancel_booking(booking.pk,'لغو دوم')])
        self.assertCountEqual(results,['success','rejected'])
        self.assertEqual(Transaction.objects.filter(transaction_type='refund').count(),1)
        self.assertEqual(Wallet.objects.get(user=self.a).balance,10000)
