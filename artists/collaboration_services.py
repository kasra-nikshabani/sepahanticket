from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from accounts.notifications import notify
from .models import (CollaborationOpportunity as Opportunity, CollaborationApplication as Application,
    CollaborationStatusChange as StatusChange)


def public_opportunities():
    return Opportunity.objects.filter(status=Opportunity.Status.PUBLISHED, deadline__gte=timezone.localdate(), owner__is_active=True)


def private_application_url(application):
    return reverse('artists:application_detail', args=[application.pk])


def notify_application(application, recipient, title, body, key):
    if recipient.is_active:
        notify(recipient, 'artist', title, body, private_application_url(application), key)


@transaction.atomic
def change_application_status(application_id, actor, action):
    # All choices lock the opportunity first, so simultaneous selections share one capacity lock.
    reference = Application.objects.only('opportunity_id').get(pk=application_id)
    opportunity = Opportunity.objects.select_for_update().select_related('owner').get(pk=reference.opportunity_id)
    application = Application.objects.select_for_update().select_related('applicant').get(pk=application_id)
    status = Application.Status
    terminal = (status.ACCEPTED, status.DECLINED, status.WITHDRAWN)
    if opportunity.status == Opportunity.Status.PAUSED:
        raise ValueError('این فراخوان توسط مدیریت متوقف شده است؛ برای پیگیری تیکت ارسال کنید.')
    if not opportunity.owner.is_active or not application.applicant.is_active:
        raise ValueError('حساب یکی از طرفین غیرفعال است.')
    if actor.pk == opportunity.owner_id:
        transitions = {
            status.SUBMITTED: (status.REVIEWING, status.INVITED, status.SELECTED, status.DECLINED),
            status.REVIEWING: (status.INVITED, status.SELECTED, status.DECLINED),
            status.INVITED: (status.SELECTED, status.DECLINED),
            status.SELECTED: (status.DECLINED,),
        }
        if opportunity.status not in (Opportunity.Status.PUBLISHED, Opportunity.Status.CLOSED):
            raise ValueError('برای بررسی متقاضیان، فراخوان باید تأیید مدیریت شده باشد.')
        if action not in transitions.get(application.status, ()):
            raise ValueError('این تغییر وضعیت در مرحلهٔ فعلی مجاز نیست.')
        if action == status.SELECTED and opportunity.applications.filter(status__in=[status.SELECTED, status.ACCEPTED]).count() >= opportunity.positions:
            raise ValueError('تعداد افراد منتخب به ظرفیت فراخوان رسیده است.')
        recipient = application.applicant
    elif actor.pk == application.applicant_id:
        if action == 'accept' and application.status == status.SELECTED:
            if opportunity.status not in (Opportunity.Status.PUBLISHED, Opportunity.Status.CLOSED):
                raise ValueError('فراخوان در انتظار بررسی مدیریت است.')
            action = status.ACCEPTED
        elif action == 'withdraw' and application.status not in terminal:
            action = status.WITHDRAWN
        else:
            raise ValueError('این تغییر وضعیت برای درخواست شما مجاز نیست.')
        recipient = opportunity.owner
    else:
        raise PermissionError('این درخواست متعلق به شما نیست.')
    application.status = action
    application.save(update_fields=['status', 'updated_at'])
    change = StatusChange.objects.create(application=application, actor=actor, status=action)
    notify_application(application, recipient, 'وضعیت درخواست همکاری تغییر کرد',
        f'«{opportunity.title}»؛ {application.get_status_display()}.', f'collaboration-status:{change.pk}')
    return application
