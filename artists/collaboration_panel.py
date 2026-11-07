from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from accounts.management_views import managed, show, paginate, audit
from accounts.notifications import notify
from .models import CollaborationOpportunity as Opportunity, CollaborationReport
from .collaboration_forms import OpportunityForm, OpportunityReviewForm, owned_events


@managed
def opportunities(request):
    rows = Opportunity.objects.select_related('owner').annotate(application_count=Count('applications', distinct=True),
        open_reports=Count('reports', filter=Q(reports__resolved_at__isnull=True), distinct=True)).order_by('-created_at', '-pk')
    query = request.GET.get('q', '').strip()[:100]
    state = request.GET.get('state', '')
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(project_name__icontains=query) | Q(organizer_name__icontains=query))
    if state in Opportunity.Status.values:
        rows = rows.filter(status=state)
    if request.GET.get('reports') == 'open':
        rows = rows.filter(open_reports__gt=0)
    return show(request, 'opportunities', 'opportunities', 'فرصت‌های همکاری', page_obj=paginate(request, rows),
        query=query, state=state, states=Opportunity.Status.choices,
        pending_count=Opportunity.objects.filter(status='pending').count(),
        report_count=CollaborationReport.objects.filter(resolved_at__isnull=True).count())


@managed
def opportunity_review(request, opportunity_id):
    opportunity = get_object_or_404(Opportunity.objects.select_related('owner', 'event'), pk=opportunity_id)
    form = OpportunityReviewForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        action = request.POST.get('action')
        note = form.cleaned_data['note'].strip()
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().select_related('owner', 'event').get(pk=opportunity.pk)
            if action == 'resolve_report':
                report = get_object_or_404(CollaborationReport.objects.select_for_update(),
                    pk=request.POST.get('report_id') if request.POST.get('report_id', '').isdigit() else None,
                    opportunity=opportunity, resolved_at__isnull=True)
                if not note:
                    form.add_error('note', 'نتیجهٔ رسیدگی را بنویسید.')
                else:
                    report.resolved_at = timezone.now()
                    report.resolved_by = request.user
                    report.resolution = note
                    report.save()
                    audit(request, report, 'گزارش فراخوان بررسی شد: ' + note)
                    notify(report.reporter, 'artist', 'گزارش فرصت همکاری بررسی شد', note,
                        reverse('artists:my_applications'), f'collaboration-report:{report.pk}:resolved')
                    messages.success(request, 'نتیجهٔ رسیدگی به گزارش ثبت شد.')
                    return redirect('management:opportunity_detail', opportunity.pk)
            elif action in ('approve', 'revision', 'pause', 'reopen'):
                validation = OpportunityForm(user=opportunity.owner, instance=opportunity)
                approval_data = model_to_dict(opportunity)
                approval_data['deadline'] = validation.fields['deadline'].prepare_value(opportunity.deadline)
                validation = OpportunityForm(approval_data, user=opportunity.owner, instance=opportunity)
                if action in ('revision', 'pause', 'reopen') and not note:
                    form.add_error('note', 'علت تصمیم را برای صاحب پروژه بنویسید.')
                elif action == 'approve' and (opportunity.status != 'pending' or not opportunity.deadline or opportunity.deadline < timezone.localdate() or not opportunity.owner.is_active):
                    form.add_error(None, 'فقط فراخوان در انتظار بررسیِ کاربر فعال با مهلت معتبر قابل انتشار است.')
                elif action == 'approve' and opportunity.event_id and not owned_events(opportunity.owner).filter(pk=opportunity.event_id).exists():
                    form.add_error(None, 'برنامهٔ مرتبط متعلق به صاحب این فراخوان نیست.')
                elif action == 'approve' and not validation.is_valid():
                    form.add_error(None, 'اطلاعات فراخوان کامل یا معتبر نیست؛ برای اصلاح به صاحب پروژه بازگردانید.')
                elif action == 'reopen' and opportunity.status != 'paused':
                    form.add_error(None, 'فقط فراخوان متوقف‌شده قابل بازگرداندن به بررسی است.')
                else:
                    opportunity.status = {'approve': 'published', 'revision': 'revision', 'pause': 'paused', 'reopen': 'revision'}[action]
                    opportunity.review_note = note
                    opportunity.reviewed_by = request.user
                    opportunity.reviewed_at = timezone.now()
                    opportunity.save()
                    audit(request, opportunity, f'بررسی فراخوان: {action}. {note}')
                    notify(opportunity.owner, 'artist', 'نتیجهٔ بررسی فراخوان همکاری',
                        f'«{opportunity.title}»؛ {opportunity.get_status_display()}. {note}',
                        reverse('artists:opportunity_manage', args=[opportunity.pk]),
                        f'collaboration-review:{opportunity.pk}:{opportunity.updated_at.isoformat()}')
                    messages.success(request, 'وضعیت فراخوان و پیام برای صاحب پروژه ثبت شد.')
                    return redirect('management:opportunity_detail', opportunity.pk)
            else:
                return HttpResponseBadRequest('عملیات نامعتبر است.')
    return show(request, 'opportunity_detail', 'opportunities', opportunity.title, opportunity=opportunity,
        form=form, applications=opportunity.applications.select_related('artist').order_by('-created_at'),
        reports=opportunity.reports.select_related('reporter', 'resolved_by'))
