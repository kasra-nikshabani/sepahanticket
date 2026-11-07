"""Education lifecycle, money, ownership and private playback regression tests."""
import re
import subprocess
import tempfile
import uuid
from datetime import time, timedelta
from pathlib import Path
from unittest.mock import patch

import jdatetime
from django.contrib.admin.models import LogEntry
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification, SiteSettings, SupportTicket, User
from wallet.models import Transaction, Wallet, get_withdrawable_amount
from .checks import private_media_check
from .forms import CourseForm, LessonForm
from .models import Course, Enrollment, Lesson, LessonProgress, PrivateEducationStorage
from .playback import cookie_name
from .services import enroll, publication_errors, refund_enrollment
from .video import ffmpeg_binary, process_video, stream_directory


@override_settings(CULTURAL_PLATFORM=True, SESSION_COOKIE_SECURE=False)
class EducationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username='education-teacher', password='test')
        cls.student = User.objects.create_user(username='education-student', password='test', first_name='هنرجو', last_name='نمونه', email='private@example.com', phone_number='09121112345')
        cls.other = User.objects.create_user(username='education-other', password='test')
        cls.admin = User.objects.create_user(username='education-admin', password='test', is_staff=True, is_superuser=True, user_type='admin')
        cls.course = Course.objects.create(owner=cls.teacher, kind='recorded', title='تمرین بازیگری', teacher_name='مدرس عمومی',
            summary='معرفی کوتاه', description='توضیحات کامل', outcomes='آموزش بیان و بدن', price_toman=100,
            status='published', submitted_at=timezone.now(), published_at=timezone.now())
        cls.lesson = Lesson.objects.create(course=cls.course, title='درس اول', source='sources/private.mp4', state='ready', duration_seconds=120)
        cls.lesson.stream_revision = cls.lesson.revision
        cls.lesson.save()
        cls.classroom = Course.objects.create(owner=cls.teacher, kind='class', title='کلاس بیان', teacher_name='مدرس عمومی',
            summary='معرفی کوتاه', description='دربارهٔ کلاس', outcomes='بیان', price_toman=100, status='published',
            published_at=timezone.now(), city='تهران', address='نشانی آموزشگاه', schedule='هشت جلسه شنبه‌ها',
            start_date=timezone.localdate()+timedelta(days=10), start_time=time(18), end_date=timezone.localdate()+timedelta(days=30), end_time=time(20),
            registration_deadline=timezone.localdate()+timedelta(days=9), capacity=1)

    def setUp(self):
        cache.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.setting = override_settings(EDUCATION_PRIVATE_ROOT=Path(self.temp.name)/'private', MEDIA_ROOT=Path(self.temp.name)/'public')
        self.setting.enable(); self.addCleanup(self.setting.disable)
        SiteSettings._local_cache = (0.0, None)
        settings_row = SiteSettings.get_solo()
        settings_row.wallet_enabled = True; settings_row.wallet_charge_enabled = True; settings_row.save()
        self.client.force_login(self.student)
        directory = stream_directory(self.lesson.pk, self.lesson.stream_revision)
        directory.mkdir(parents=True)
        (directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\nsegment_000000.ts\n')
        (directory/'key.bin').write_bytes(b'1234567890123456')
        (directory/'segment_000000.ts').write_bytes(b'encrypted-data')

    def credit(self, user=None, amount=5000):
        Wallet.objects.filter(user=user or self.student).update(balance=amount)

    def buy(self, course=None, user=None):
        return enroll(user or self.student, (course or self.course).pk, '100', 'نام اعلامی هنرجو')[0]

    def review(self, action, course=None, note='پیام مدیریت', **extra):
        course = course or self.course
        course.refresh_from_db()
        return self.client.post(reverse('management:education_detail', args=[course.pk]),
            {'version': course.updated_at.isoformat(), 'action': action, 'note': note, **extra})

    def class_data(self, course=None, **changes):
        course = course or self.classroom
        jalali = lambda d: jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')
        data = {'kind': course.kind, 'title': course.title, 'teacher_name': course.teacher_name, 'subject':'acting', 'level':'all',
            'summary':course.summary, 'description':course.description, 'outcomes':course.outcomes, 'price_toman': str(course.price_toman),
            'city':course.city, 'address':course.address, 'schedule':course.schedule, 'capacity':str(course.capacity),
            'start_date':jalali(course.start_date), 'start_time':'18:00', 'end_date':jalali(course.end_date), 'end_time':'20:00',
            'registration_deadline':jalali(course.registration_deadline), 'version':course.updated_at.isoformat(), 'action':'save'}
        data.update(changes)
        return data

    def authorize(self, lesson=None, client=None):
        return (client or self.client).post(reverse('education:authorize', args=[(lesson or self.lesson).pk]))

    def test_public_catalogue_only_approved_active_accounts(self):
        Course.objects.create(owner=self.other, kind='recorded', title='پیش‌نویس خصوصی')
        response = self.client.get(reverse('education:catalogue'))
        self.assertContains(response, self.course.title)
        self.assertNotContains(response, 'پیش‌نویس خصوصی')
        self.teacher.is_active=False; self.teacher.save()
        self.assertNotContains(self.client.get(reverse('education:catalogue')), self.course.title)

    def test_catalogue_persian_search_and_kind_filter(self):
        response = self.client.get(reverse('education:catalogue'), {'q':'بازيگري', 'kind':'recorded'})
        self.assertContains(response, self.course.title)
        self.assertNotContains(response, self.classroom.title)

    def test_draft_hidden_from_other_users(self):
        self.course.status='draft'; self.course.save()
        self.assertEqual(self.client.get(self.course.get_absolute_url()).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.course.get_absolute_url()).status_code, 200)

    def test_incomplete_draft_can_be_saved(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('education:create'), {'kind':'recorded', 'title':'آموزش تازه', 'subject':'acting','level':'all','price_toman':'۰','action':'save'})
        self.assertEqual(response.status_code,302)
        course=Course.objects.get(title='آموزش تازه')
        self.assertEqual(course.owner,self.teacher)
        self.assertEqual(course.status,'draft')
        self.assertIsNone(course.submitted_at)

    def test_incomplete_submission_is_rejected(self):
        self.client.force_login(self.teacher)
        response=self.client.post(reverse('education:create'), {'kind':'recorded','title':'ناتمام','subject':'acting','level':'all','price_toman':'0','action':'submit'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Course.objects.filter(title='ناتمام').exists())

    def test_class_submit_then_approve_and_notification(self):
        self.classroom.published_at=None; self.classroom.status='draft'; self.classroom.save()
        self.client.force_login(self.teacher)
        data=self.class_data(action='submit')
        self.assertEqual(self.client.post(reverse('education:edit', args=[self.classroom.pk]),data).status_code,302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.status,'pending')
        self.assertEqual(self.client.get(reverse('management:education_detail',args=[self.classroom.pk])).status_code,302)
        self.client.force_login(self.admin)
        self.assertEqual(self.review('approve',self.classroom,note='').status_code,302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.status,'published')
        self.assertIsNotNone(self.classroom.published_at)
        self.assertTrue(LogEntry.objects.filter(user=self.admin).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.teacher,kind='publication').exists())

    def test_type_locked_after_first_submission(self):
        self.classroom.submitted_at=timezone.now(); self.classroom.published_at=None;self.classroom.save()
        form=CourseForm(self.class_data(kind='recorded'),instance=self.classroom)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['kind'],'class')

    def test_stale_edit_does_not_overwrite(self):
        self.classroom.published_at=None;self.classroom.status='draft';self.classroom.save()
        self.client.force_login(self.teacher)
        data=self.class_data(title='عنوان قدیمی')
        self.classroom.title='عنوان تازه';self.classroom.save()
        response=self.client.post(reverse('education:edit',args=[self.classroom.pk]),data)
        self.assertContains(response,'اطلاعات در صفحهٔ دیگری تغییر کرده')
        self.classroom.refresh_from_db();self.assertEqual(self.classroom.title,'عنوان تازه')

    def test_published_owner_edit_and_lesson_edit_blocked(self):
        self.client.force_login(self.teacher)
        for name,args in [('edit',[self.course.pk]),('lesson_edit',[self.course.pk,self.lesson.pk]),('lesson_create',[self.course.pk])]:
            for method in [self.client.get,self.client.post]:
                self.assertEqual(method(reverse('education:'+name,args=args)).status_code,404)

    def test_teacher_cannot_manage_another_course(self):
        for name in ['manage','edit','lesson_create']:
            self.assertEqual(self.client.get(reverse('education:'+name,args=[self.course.pk])).status_code,404)

    def test_paid_enrollment_rial_conversion_and_duplicate_is_idempotent(self):
        self.credit()
        enrollment=self.buy()
        repeat,created=enroll(self.student,self.course.pk,'999','دیگری')
        self.assertEqual(enrollment.pk,repeat.pk);self.assertFalse(created)
        self.assertEqual(Enrollment.objects.count(),1)
        self.assertEqual(Wallet.objects.get(user=self.student).balance,4000)
        self.assertEqual(enrollment.paid_rial,1000)
        self.assertEqual(Transaction.objects.filter(transaction_type='education_purchase').count(),1)
        self.assertEqual(Notification.objects.filter(kind='purchase').count(),2)

    def test_insufficient_balance_rolls_back_everything(self):
        with self.assertRaisesMessage(ValueError,'موجودی'):
            self.buy()
        self.assertEqual(Enrollment.objects.count(),0)
        self.assertEqual(Transaction.objects.count(),0)
        self.assertEqual(Notification.objects.count(),0)

    def test_changed_price_rejected_without_charge(self):
        self.credit()
        with self.assertRaisesMessage(ValueError,'قیمت'):
            enroll(self.student,self.course.pk,'99','هنرجو')
        self.assertEqual(Wallet.objects.get(user=self.student).balance,5000)

    def test_disabled_wallet_blocks_paid_but_not_free(self):
        self.credit(); settings_row=SiteSettings.get_solo()
        settings_row.wallet_enabled=False;settings_row.save()
        with self.assertRaisesMessage(ValueError,'غیرفعال'):
            self.buy()
        self.course.price_toman=0;self.course.save()
        row,_=enroll(self.student,self.course.pk,'0','هنرجو')
        self.assertEqual(row.paid_rial,0)
        self.assertFalse(Transaction.objects.exists())

    def test_class_capacity_prevents_second_charge(self):
        self.credit();self.credit(self.other)
        self.buy(self.classroom)
        with self.assertRaisesMessage(ValueError,'ظرفیت'):
            self.buy(self.classroom,self.other)
        self.assertEqual(Wallet.objects.get(user=self.other).balance,5000)
        self.assertEqual(self.classroom.enrollments.count(),1)

    def test_past_class_or_deadline_blocks_registration(self):
        self.credit()
        self.classroom.registration_deadline=timezone.localdate()-timedelta(days=1);self.classroom.save()
        with self.assertRaisesMessage(ValueError,'مهلت'):
            self.buy(self.classroom)
        self.classroom.registration_deadline=timezone.localdate();self.classroom.start_date=timezone.localdate()-timedelta(days=1);self.classroom.save()
        with self.assertRaisesMessage(ValueError,'مهلت'):
            self.buy(self.classroom)

    def test_owner_cannot_purchase_own_course(self):
        self.credit(self.teacher)
        with self.assertRaisesMessage(ValueError,'مدرس'):
            self.buy(user=self.teacher)

    def test_refund_exactly_once_restores_wallet_revokes_access(self):
        self.credit(); row=self.buy()
        self.assertEqual(self.authorize().status_code,200)
        manifest=self.authorize().json()['manifest']
        refund_enrollment(row.pk)
        self.assertEqual(Wallet.objects.get(user=self.student).balance,5000)
        self.assertEqual(self.client.get(manifest).status_code,404)
        with self.assertRaisesMessage(ValueError,'قبلاً'):
            refund_enrollment(row.pk)
        self.assertEqual(Transaction.objects.filter(transaction_type='refund').count(),1)

    def test_refund_frees_class_place_and_reenroll_is_new_payment(self):
        self.credit();self.credit(self.other)
        row=self.buy(self.classroom);refund_enrollment(row.pk)
        self.buy(self.classroom,self.other)
        self.assertEqual(self.classroom.enrollments.filter(status='active').count(),1)
        self.assertEqual(Wallet.objects.get(user=self.student).balance,5000)
        row=self.buy();refund_enrollment(row.pk);self.buy()
        self.assertEqual(Wallet.objects.get(user=self.student).balance,4000)
        self.assertEqual(self.course.enrollments.count(),1)

    def test_purchase_and_refund_do_not_create_extra_withdrawable_credit(self):
        self.student.wallet.add_balance(5000,reference_id='gateway-demo')
        row=self.buy();refund_enrollment(row.pk)
        self.assertEqual(get_withdrawable_amount(self.student),0)
        self.assertEqual(Wallet.objects.get(user=self.teacher).balance,0)

    def test_real_checkout_and_missing_balance_feedback(self):
        url=reverse('education:checkout',args=[self.course.pk])
        self.assertContains(self.client.get(url),'شارژ کیف پول و بازگشت')
        self.assertEqual(self.client.post(url,{'price':'100','learner_name':'هنرجوی آزمایشی'}).status_code,200)
        self.assertFalse(Enrollment.objects.exists())
        self.credit()
        self.assertRedirects(self.client.post(url,{'price':'100','learner_name':'هنرجوی آزمایشی'}),reverse('education:my_learning'))

    def test_wallet_charge_return_only_internal_urls(self):
        target=reverse('education:checkout',args=[self.course.pk])
        response=self.client.get(reverse('wallet:charge'),{'next':target})
        self.assertEqual(response.context['charge_next'],target)
        for next_url in ['https://evil.example','//evil.example','/\\evil.example','javascript:alert(1)']:
            self.assertEqual(self.client.get(reverse('wallet:charge'),{'next':next_url}).context['charge_next'],reverse('wallet:dashboard'))

    def test_teacher_roster_has_declared_name_but_no_private_contacts(self):
        self.credit();self.buy()
        self.client.force_login(self.teacher)
        response=self.client.get(reverse('education:manage',args=[self.course.pk]))
        self.assertContains(response,'نام اعلامی هنرجو')
        self.assertContains(response,'فروش ثبت‌نام‌های فعال')
        self.assertNotContains(response,'private@example.com')
        self.assertNotContains(response,'09121112345')
        self.assertNotContains(response,'۰۹۱۲۱۱۱۲۳۴۵')

    def test_admin_rejects_stale_review_and_requires_reason(self):
        self.client.force_login(self.admin)
        url=reverse('management:education_detail',args=[self.course.pk])
        self.assertContains(self.client.post(url,{'action':'pause','note':'','version':self.course.updated_at.isoformat()}),'علت تصمیم')
        self.assertContains(self.client.post(url,{'action':'pause','note':'دلیل','version':'old'}),'اطلاعات آموزش تغییر کرده')
        self.course.refresh_from_db();self.assertEqual(self.course.status,'published')

    def test_revision_notify_and_admin_cannot_approve_unready_course(self):
        self.course.status='pending';self.course.save()
        self.lesson.state='queued';self.lesson.save()
        self.client.force_login(self.admin)
        response=self.review('approve',note='')
        self.assertContains(response,'آماده‌سازی همهٔ ویدئوها')
        self.assertEqual(self.review('revision',note='ویدئو را اصلاح کنید').status_code,302)
        self.course.refresh_from_db();self.assertEqual(self.course.status,'revision')
        self.assertTrue(Notification.objects.filter(recipient=self.teacher,kind='review').exists())

    def test_pending_recorded_requires_latest_revision_ready(self):
        self.lesson.revision=uuid.uuid4();self.lesson.save()
        self.assertTrue(publication_errors(self.course))

    def test_staff_only_panel_and_refund_action(self):
        self.credit();row=self.buy()
        url=reverse('management:education_detail',args=[self.course.pk])
        self.assertEqual(self.client.post(url,{'action':'refund','enrollment_id':str(row.pk)}).status_code,302)
        row.refresh_from_db();self.assertEqual(row.status,'active')
        self.client.force_login(self.admin)
        self.assertEqual(self.review('refund',enrollment_id=str(row.pk)).status_code,302)
        row.refresh_from_db();self.assertEqual(row.status,'refunded')

    def test_roster_refund_form_target_works_and_get_is_readonly(self):
        self.credit();row=self.buy();self.client.force_login(self.admin)
        url=reverse('management:education_detail',args=[self.course.pk])+'?action=refund'
        self.assertEqual(self.client.get(url).status_code,200)
        row.refresh_from_db();self.assertEqual(row.status,'active')
        self.course.refresh_from_db()
        self.assertEqual(self.client.post(url,{'version':self.course.updated_at.isoformat(),'enrollment_id':str(row.pk),'note':'لغو هنرجو'}).status_code,302)
        row.refresh_from_db();self.assertEqual(row.status,'refunded')

    def test_cross_course_refund_and_invalid_uuid_rejected(self):
        self.credit();row=self.buy(self.classroom);self.client.force_login(self.admin)
        self.assertEqual(self.review('refund',enrollment_id=str(row.pk)).status_code,404)
        self.assertEqual(self.review('refund',enrollment_id='invalid').status_code,404)
        row.refresh_from_db();self.assertEqual(row.status,'active')

    def test_sales_pause_keeps_existing_buyer_access(self):
        self.credit();self.buy();self.credit(self.other)
        self.client.force_login(self.admin)
        self.review('close_sales')
        with self.assertRaisesMessage(ValueError,'بسته'):
            self.buy(user=self.other)
        self.review('pause')
        self.client.force_login(self.student)
        self.assertEqual(self.authorize().status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.course.get_absolute_url()).status_code,404)

    def test_explicit_content_suspend_revokes_existing_buyer(self):
        self.credit();self.buy();self.client.force_login(self.admin)
        self.review('suspend_access');self.client.force_login(self.student)
        self.assertEqual(self.authorize().status_code,404)
        self.client.force_login(self.admin);self.review('restore_access');self.client.force_login(self.student)
        self.assertEqual(self.authorize().status_code,200)

    def test_unbought_video_and_source_never_public(self):
        self.assertEqual(self.client.get(self.lesson.get_absolute_url()).status_code,404)
        self.assertEqual(self.authorize().status_code,404)
        with self.assertRaises(ValueError): _=self.lesson.source.url
        self.assertNotContains(self.client.get(self.course.get_absolute_url()),'sources/private.mp4')

    def test_sample_only_when_published_and_active(self):
        self.lesson.is_preview=True;self.lesson.save()
        self.assertEqual(self.authorize().status_code,200)
        self.course.status='draft';self.course.save()
        self.assertEqual(self.authorize().status_code,404)
        self.course.status='published';self.course.save();self.lesson.is_active=False;self.lesson.save()
        self.assertEqual(self.authorize().status_code,404)

    def test_owner_and_admin_can_preview_before_publication(self):
        self.course.status='draft';self.course.save()
        for user in [self.teacher,self.admin]:
            self.client.force_login(user)
            self.assertEqual(self.authorize().status_code,200)
            self.assertEqual(self.client.get(self.lesson.get_absolute_url()).status_code,200)

    def test_valid_stream_needs_login_authorization_cookie_and_current_rights(self):
        self.credit();self.buy()
        asset=reverse('education:stream',args=[self.lesson.pk,self.lesson.stream_revision,'index.m3u8'])
        self.assertEqual(self.client.get(asset).status_code,404)
        response=self.authorize()
        cookie=response.cookies[cookie_name(self.lesson)]
        self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Strict')
        self.assertIn('/learn/stream/',cookie['path'])
        response=self.client.get(asset)
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['Cross-Origin-Resource-Policy'],'same-origin')
        self.assertIn(b'#EXTM3U',b''.join(response.streaming_content))
        self.client.logout();self.assertEqual(self.client.get(asset).status_code,404)

    def test_playback_cookie_is_bound_to_user_and_session(self):
        self.credit();self.buy()
        response=self.authorize();manifest=response.json()['manifest'];cookie=self.client.cookies[cookie_name(self.lesson)].value
        another=Client();another.force_login(self.student);another.cookies[cookie_name(self.lesson)]=cookie
        self.assertEqual(another.get(manifest).status_code,404)
        self.credit(self.other);self.buy(user=self.other)
        another.force_login(self.other);another.cookies[cookie_name(self.lesson)]=cookie
        self.assertEqual(another.get(manifest).status_code,404)

    def test_expired_tampered_cookie_and_old_revision_rejected(self):
        self.credit();self.buy();response=self.authorize();manifest=response.json()['manifest']
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+200):
            self.assertEqual(self.client.get(manifest).status_code,404)
        self.client.cookies[cookie_name(self.lesson)]='tampered'
        self.assertEqual(self.client.get(manifest).status_code,404)
        self.authorize();self.lesson.stream_revision=uuid.uuid4();self.lesson.save()
        self.assertEqual(self.client.get(manifest).status_code,404)

    def test_stream_allowlist_and_private_key_and_segments(self):
        self.credit();self.buy();self.authorize()
        for asset,expected in [('key.bin',200),('segment_000000.ts',200),('source.mp4',404),('keyinfo.txt',404),('segment_0.ts',404)]:
            response=self.client.get(reverse('education:stream',args=[self.lesson.pk,self.lesson.stream_revision,asset]))
            self.assertEqual(response.status_code,expected)
            if expected==200: response.close()

    def test_progress_requires_enrollment_and_clamps_position(self):
        url=reverse('education:progress',args=[self.lesson.pk])
        self.lesson.is_preview=True;self.lesson.save()
        self.assertEqual(self.client.post(url,{'position':'30'}).status_code,404)
        self.credit();self.buy()
        self.assertEqual(self.client.post(url,{'position':'999999'}).status_code,200)
        self.assertEqual(LessonProgress.objects.get().position_seconds,120)
        self.assertEqual(self.client.post(url,{'position':'invalid'}).status_code,400)
        self.client.post(url,{'action':'complete'})
        self.assertTrue(LessonProgress.objects.get().completed)
        response=self.client.get(reverse('education:my_learning'))
        self.assertEqual(response.context['page_obj'][0].percent,100)
        self.client.post(url,{'action':'incomplete'})
        self.assertFalse(LessonProgress.objects.get().completed)

    def test_continue_uses_recent_unfinished_lesson(self):
        self.credit();row=self.buy()
        second=Lesson.objects.create(course=self.course,title='درس دوم',order=2,state='ready',stream_revision=uuid.uuid4())
        LessonProgress.objects.create(enrollment=row,lesson=second,position_seconds=20)
        response=self.client.get(reverse('education:my_learning'))
        self.assertEqual(response.context['page_obj'][0].first_lesson.pk,second.pk)

    def test_csrf_and_post_only_mutations(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.student)
        self.assertEqual(client.post(reverse('education:authorize',args=[self.lesson.pk])).status_code,403)
        self.assertEqual(client.post(reverse('education:checkout',args=[self.course.pk])).status_code,403)
        for name in ['authorize','progress','retry']:
            self.assertEqual(self.client.get(reverse('education:'+name,args=[self.lesson.pk])).status_code,405)

    def test_forms_do_not_render_private_file_urls_and_validate_upload(self):
        self.assertIn('type="file"',str(LessonForm(instance=self.lesson)))
        uploaded=SimpleUploadedFile('attack.mp4',b'<html>not video</html>',content_type='video/mp4')
        form=LessonForm({'title':'درس','order':'۱','is_active':'on'}, {'source':uploaded},instance=Lesson(course=self.course))
        self.assertFalse(form.is_valid());self.assertIn('source',form.errors)
        valid=SimpleUploadedFile('video.mp4',b'\x00\x00\x00\x18ftypisom'+b'0'*30,content_type='video/mp4')
        with override_settings(EDUCATION_MAX_VIDEO_BYTES=10):
            form=LessonForm({'title':'درس','order':'1'}, {'source':valid},instance=Lesson(course=self.course))
            self.assertFalse(form.is_valid());self.assertIn('source',form.errors)

    def test_upload_draft_lesson_queued_and_cannot_be_added_to_class(self):
        self.course.status='draft';self.course.published_at=None;self.course.save()
        self.client.force_login(self.teacher)
        upload=SimpleUploadedFile('video.mp4',b'\x00\x00\x00\x18ftypisom'+b'0'*30,content_type='video/mp4')
        response=self.client.post(reverse('education:lesson_create',args=[self.course.pk]),{'title':'ویدئوی تازه','order':'۲','source':upload,'is_active':'on'})
        self.assertEqual(response.status_code,302)
        lesson=Lesson.objects.get(title='ویدئوی تازه')
        self.assertEqual(lesson.state,'queued')
        self.assertTrue(Path(lesson.source.path).is_relative_to(Path(self.temp.name)/'private'))
        self.classroom.published_at=None;self.classroom.save()
        self.assertEqual(self.client.get(reverse('education:lesson_create',args=[self.classroom.pk])).status_code,404)

    def test_retry_rotates_revision_and_preserves_last_good_stream(self):
        self.course.status='draft';self.course.published_at=None;self.course.save()
        self.lesson.state='failed';self.lesson.save()
        old_revision=self.lesson.revision;old_stream=self.lesson.stream_revision
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse('education:retry',args=[self.lesson.pk])).status_code,302)
        self.lesson.refresh_from_db()
        self.assertNotEqual(self.lesson.revision,old_revision);self.assertEqual(self.lesson.stream_revision,old_stream)
        self.assertEqual(self.lesson.state,'queued')

    def test_private_storage_config_cannot_be_public(self):
        with override_settings(EDUCATION_PRIVATE_ROOT=Path(self.temp.name)/'public'/'videos'):
            self.assertEqual(private_media_check(None)[0].id,'education.E001')
        self.assertEqual(private_media_check(None),[])

    def test_class_old_recorded_lessons_are_not_playable(self):
        self.lesson.course=self.classroom;self.lesson.save();self.client.force_login(self.teacher)
        self.assertEqual(self.authorize().status_code,404)

    def test_education_support_links_request_to_course_and_admin(self):
        self.client.force_login(self.teacher)
        url=reverse('accounts:support_create')+'?education='+str(self.course.pk)
        self.assertContains(self.client.get(url),self.course.title)
        response=self.client.post(url,{'subject':'تغییر قیمت دوره','body':'لطفاً قیمت را بررسی کنید','category':'general'})
        self.assertEqual(response.status_code,302)
        ticket=SupportTicket.objects.get()
        self.assertEqual(ticket.course,self.course)
        self.assertEqual(ticket.category,'program')
        self.assertIsNone(ticket.event_id)
        self.client.force_login(self.admin)
        response=self.client.get(reverse('management:support_detail',args=[ticket.pk]))
        self.assertContains(response,reverse('management:education_detail',args=[self.course.pk]))
        self.course.refresh_from_db();self.assertEqual(self.course.price_toman,100)

    def test_course_support_scoped_to_owner_or_active_learner(self):
        url=reverse('accounts:support_create')+'?education='+str(self.course.pk)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.post(url,{'subject':'درخواست','body':'خصوصی'}).status_code,404)
        self.credit();row=self.buy()
        self.assertEqual(self.client.get(url).status_code,200)
        refund_enrollment(row.pk)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(reverse('accounts:support_create')+'?education=invalid').status_code,404)

    def test_course_support_search_in_management(self):
        self.client.force_login(self.teacher)
        self.client.post(reverse('accounts:support_create')+'?education='+str(self.course.pk),{'subject':'پیگیری','body':'لطفاً بررسی کنید'})
        self.client.force_login(self.admin)
        response=self.client.get(reverse('management:support'),{'q':self.course.title})
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        self.assertContains(response,self.course.title)

    def test_edit_lesson_metadata_does_not_revert_background_processing(self):
        self.course.status='draft';self.course.published_at=None;self.course.save()
        self.lesson.state='queued';self.lesson.save()
        original=LessonForm.is_valid
        def finish_background_job(form):
            valid=original(form)
            Lesson.objects.filter(pk=self.lesson.pk).update(state='ready',stream_revision=self.lesson.revision,duration_seconds=321)
            return valid
        self.client.force_login(self.teacher)
        with patch.object(LessonForm,'is_valid',finish_background_job):
            response=self.client.post(reverse('education:lesson_edit',args=[self.course.pk,self.lesson.pk]),{'title':'عنوان اصلاح‌شده','order':'۱','is_active':'on'})
        self.assertEqual(response.status_code,302)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.state,'ready')
        self.assertEqual(self.lesson.duration_seconds,321)
        self.assertEqual(self.lesson.title,'عنوان اصلاح‌شده')

    def test_native_admin_readonly_lesson_does_not_render_source_url(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin:education_lesson_change',args=[self.lesson.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'sources/private.mp4')

    def test_all_education_pages_render(self):
        self.credit();self.buy()
        for name,args in [('catalogue',[]),('detail',[self.course.pk]),('detail',[self.classroom.pk]),('my_learning',[]),('watch',[self.lesson.pk])]:
            self.assertEqual(self.client.get(reverse('education:'+name,args=args)).status_code,200)
        self.client.force_login(self.teacher)
        for name,args in [('my_teaching',[]),('create',[]),('manage',[self.course.pk])]:
            self.assertEqual(self.client.get(reverse('education:'+name,args=args)).status_code,200)
        self.client.force_login(self.admin)
        for name,args in [('education',[]),('education_detail',[self.course.pk]),('education_detail',[self.classroom.pk])]:
            self.assertEqual(self.client.get(reverse('management:'+name,args=args)).status_code,200)
        for name,args in [('edit',[self.course.pk]),('lesson_edit',[self.course.pk,self.lesson.pk])]:
            self.assertEqual(self.client.get(reverse('education:'+name,args=args)).status_code,200)


class EducationPackagingTests(TestCase):
    def test_real_video_packaging_encrypts_segments_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(EDUCATION_PRIVATE_ROOT=Path(directory)/'private'):
            clip=Path(directory)/'clip.mp4'
            subprocess.run([ffmpeg_binary(),'-y','-nostdin','-loglevel','error','-f','lavfi','-i','color=c=0x33452d:s=320x180:r=12','-t','2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(clip)],check=True,capture_output=True,timeout=20)
            teacher=User.objects.create_user(username='video-teacher')
            course=Course.objects.create(owner=teacher,kind='recorded',title='ویدئو')
            lesson=Lesson(course=course,title='درس')
            lesson.source.save('clip.mp4',ContentFile(clip.read_bytes()),save=True)
            self.assertTrue(process_video(lesson.pk))
            lesson.refresh_from_db();self.assertEqual(lesson.state,'ready')
            output=stream_directory(lesson.pk,lesson.stream_revision)
            self.assertEqual(len((output/'key.bin').read_bytes()),16)
            manifest=(output/'index.m3u8').read_text()
            self.assertIn('#EXT-X-KEY:METHOD=AES-128',manifest)
            self.assertNotIn(directory,manifest)
            self.assertFalse((output/'keyinfo.txt').exists())
            segment=(output/'segment_000000.ts').read_bytes()
            self.assertEqual(len(segment)%16,0)
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            iv = bytes.fromhex(re.search(r'IV=0x([0-9a-fA-F]+)',manifest).group(1))
            decoder=Cipher(algorithms.AES((output/'key.bin').read_bytes()),modes.CBC(iv)).decryptor()
            decoded=decoder.update(segment)+decoder.finalize()
            self.assertEqual([decoded[0],decoded[188],decoded[376]],[0x47,0x47,0x47])
            self.assertFalse(process_video(lesson.pk))
            self.assertGreaterEqual(lesson.duration_seconds,1)

    def test_invalid_source_fails_without_leaking_paths(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(EDUCATION_PRIVATE_ROOT=Path(directory)/'private'):
            teacher=User.objects.create_user(username='failed-teacher')
            course=Course.objects.create(owner=teacher,kind='recorded',title='ویدئو')
            lesson=Lesson(course=course,title='درس')
            lesson.source.save('bad.mp4',ContentFile(b'bad-data'),save=True)
            self.assertFalse(process_video(lesson.pk))
            lesson.refresh_from_db()
            self.assertEqual(lesson.state,'failed')
            self.assertNotIn(directory,lesson.processing_error)
            self.assertFalse(stream_directory(lesson.pk,lesson.revision).exists())
