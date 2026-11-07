from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from accounts.models import User
from matches.models import Event, Match, Stadium, Block, Row, Seat
from .models import Ticket


class DigitalTicketTests(TestCase):
    def setUp(self):
        self.media=TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override=override_settings(MEDIA_ROOT=self.media.name)
        override.enable(); self.addCleanup(override.disable)
        self.user=User.objects.create_user(username='digital-owner')
        self.other=User.objects.create_user(username='digital-other')
        self.venue=Stadium.objects.create(name='سالن نمایش', city='تهران', capacity=1)
        block=Block.objects.create(stadium=self.venue, name='همکف', price=100000)
        row=Row.objects.create(block=block, number=1)
        seat=Seat.objects.create(row=row, number=1)
        event=Event.objects.create(title='نمایش تست', category='theater')
        self.match=Match.objects.create(event=event, stadium=self.venue, date_time=timezone.now()+timedelta(days=1))
        with patch.object(Ticket,'generate_qr_code'), patch('tickets.tasks.enqueue_pdf_generation'):
            self.ticket=Ticket.objects.create(user=self.user, match=self.match, seat=seat,
                match_seat=self.match.match_seats.get(seat=seat), full_name='دارندهٔ بلیط', national_code='', price=100000, status='paid')
        self.client.force_login(self.user)
        self.url=reverse('tickets:digital_ticket',args=[self.ticket.pk])
        self.qr_url=reverse('tickets:ticket_qr',args=[self.ticket.pk])

    def test_owner_can_open_pass_and_gate_compatible_qr_without_pdf(self):
        response=self.client.get(self.url)
        self.assertContains(response, 'دارندهٔ بلیط')
        self.assertContains(response, self.qr_url)
        self.assertTrue(response.context['can_enter'])
        response=self.client.get(self.qr_url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/png')
        self.assertIn('no-store',response['Cache-Control'])
        image=Image.open(BytesIO(response.content))
        self.assertEqual(image.format,'PNG')
        self.assertEqual(self.ticket.gate_qr_payload, f'Ticket:{self.ticket.ticket_number}|Match:{self.match.pk}|Seat:{self.ticket.seat_id}|User:{self.user.username}')

    def test_other_users_and_guests_cannot_access_pass_or_qr(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.client.get(self.qr_url).status_code,404)
        self.client.logout()
        self.assertEqual(self.client.get(self.qr_url).status_code,302)

    def test_cancelled_used_ended_and_pending_tickets_have_no_entry_qr(self):
        for state in ['cancelled','used','ended','pending']:
            self.ticket.status='paid'; self.ticket.is_used=False
            self.match.date_time=timezone.now()+timedelta(days=1)
            if state in ['cancelled','pending']: self.ticket.status=state
            if state=='used': self.ticket.is_used=True
            if state=='ended': self.match.date_time=timezone.now()-timedelta(days=2)
            Ticket.objects.filter(pk=self.ticket.pk).update(status=self.ticket.status,is_used=self.ticket.is_used)
            self.match.save()
            self.assertEqual(self.client.get(self.qr_url).status_code,404)
            response=self.client.get(self.url)
            if state=='pending': self.assertEqual(response.status_code,404)
            else:
                self.assertFalse(response.context['can_enter'])
                self.assertNotContains(response,'alt="کد QR ورود این بلیط"')

    @override_settings(DEBUG=True)
    def test_local_pdf_download_serves_real_authorized_bytes(self):
        self.ticket.pdf_file.save('sample.pdf',ContentFile(b'%PDF-1.4 sample'),save=False)
        Ticket.objects.filter(pk=self.ticket.pk).update(pdf_file=self.ticket.pdf_file.name)
        url=reverse('tickets:download_ticket_pdf',args=[self.ticket.pk])
        response=self.client.get(url)
        self.assertEqual(b''.join(response.streaming_content),b'%PDF-1.4 sample')
        self.assertIn('attachment',response['Content-Disposition'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code,404)
