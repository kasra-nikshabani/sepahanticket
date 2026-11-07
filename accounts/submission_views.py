from datetime import date, time
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .models import EventSubmission, SubmissionPhoto
from .submission_forms import FORMS, STEPS, CATEGORIES, ADMISSION_MODES, JalaliDate
from .submission_schedule import session_plan
from django import forms
from django.core.exceptions import ValidationError
from .venue_layout import layout_capacity
from .publication_policy import published_change_response
from matches.models import Stadium, Seat

FILE_FIELDS = ('poster', 'cover', 'teaser', 'license_image')


def _initial(submission):
    if not submission:
        return {}
    return {**submission.data, 'category': submission.category, 'title': submission.title,
            'venue_preset': submission.venue_id,
            **{key: getattr(submission, key) for key in FILE_FIELDS if getattr(submission, key)}}


def _saved_form(submission, number):
    initial = _initial(submission)
    form = FORMS[number](initial=initial)
    data = {key: field.prepare_value(initial.get(key)) for key, field in form.fields.items()
            if key not in FILE_FIELDS and key != 'photos'}
    return FORMS[number](data, initial=initial)


def _review(submission):
    if not submission:
        return []
    groups = []
    for number in range(1, 6):
        form = FORMS[number](initial=_initial(submission))
        rows = []
        for name, field in form.fields.items():
            quantity = submission.data.get('admission_mode') == 'quantity'
            if (name == 'prices' and quantity) or (name in ('ticket_capacity', 'ticket_price') and not quantity):
                continue
            if name in FILE_FIELDS or name in ('photos', 'confirm', 'seat_layout', 'venue_preset'):
                continue
            value = _initial(submission).get(name)
            if isinstance(value, bool):
                value = 'بله' if value else 'خیر'
            elif name == 'opening_sessions':
                try:
                    choices = session_plan(submission.data)
                    value = '\n'.join(item['label'] for item in choices if item['key'] in (value or [])) or 'همه سانس‌ها در شروع فروش بسته بمانند'
                except ValidationError:
                    value = 'انتخاب‌ها نیاز به بازبینی دارند'
            elif name == 'category':
                value = dict(CATEGORIES).get(value, '—')
            elif name == 'admission_mode':
                value = dict(ADMISSION_MODES).get(value or 'seated')
            elif name == 'venue_mode':
                value = {'preset': 'سالن آماده سامانه', 'custom': 'سالن و چیدمان پیشنهادی', 'online': 'برنامه آنلاین'}.get(value, '—')
            else:
                value = field.prepare_value(value)
            if value not in (None, ''):
                rows.append((field.label, value))
        if number == 2 and submission.data.get('venue_mode') == 'custom' and not quantity:
            rows.append(('تعداد صندلی‌های چیدمان پیشنهادی', layout_capacity(submission.data.get('seat_layout') or {})))
        groups.append({'number': number, 'title': STEPS[number - 1], 'rows': rows})
    return groups


@login_required
@never_cache
def wizard(request, submission_id=None, step=1):
    submission = None
    if submission_id:
        submission = get_object_or_404(EventSubmission, pk=submission_id, owner=request.user)
        if submission.published_event_id:
            return published_change_response(request, submission)
        if submission.status == 'submitted':
            if request.method == 'POST' and request.POST.get('action') == 'reopen':
                with transaction.atomic():
                    submission = EventSubmission.objects.select_for_update().get(pk=submission.pk, owner=request.user)
                    if submission.published_event_id:
                        return published_change_response(request, submission)
                    if submission.status == 'submitted':
                        submission.status = 'draft'
                        submission.save(update_fields=['status', 'updated_at'])
                messages.success(request, 'درخواست برای ویرایش به پیش‌نویس برگشت؛ پس از تغییرات، دوباره برای بررسی ارسال کن.')
                return redirect('accounts:event_submission_step', submission.pk, 1)
            return render(request, 'accounts/submission_done.html', {'submission': submission, 'review_groups': _review(submission)})
        if not 1 <= step <= 5:
            raise Http404
    initial = _initial(submission)
    category = request.GET.get('category')
    if not submission and category in dict(CATEGORIES):
        initial.update(category=category, prefix=dict(CATEGORIES)[category])
    form = FORMS[step](request.POST if request.method == 'POST' else None,
                       request.FILES if request.method == 'POST' else None, initial=initial,
                       partial=not (request.method == 'POST' and step == 5 and request.POST.get('action') == 'submit'),
                       lock_category=bool(submission and (submission.submitted_at or submission.published_event_id)))
    if request.method == 'POST' and step == 5 and request.POST.get('action') == 'submit':
        if form.is_valid() and not form.cleaned_data.get('confirm'):
            form.add_error('confirm', 'پیش از ارسال، صحت اطلاعات را تأیید کن.')
    if request.method == 'POST' and form.is_valid():
        photos = form.cleaned_data.get('photos', [])
        remove_ids = [int(value) for value in request.POST.getlist('remove_photos') if value.isdecimal()]
        existing_count = submission.photos.exclude(pk__in=remove_ids).count() if submission else 0
        if len(photos) + existing_count > 10:
            form.add_error('photos', 'مجموع عکس‌های صحنه نمی‌تواند بیشتر از ۱۰ عکس باشد؛ ابتدا عکس‌های قبلی را حذف کن.')
        else:
            with transaction.atomic():
                if submission:
                    submission = EventSubmission.objects.select_for_update().get(pk=submission.pk, owner=request.user)
                    if submission.published_event_id:
                        return published_change_response(request, submission)
                    if submission.status != 'draft':
                        return redirect('accounts:event_submission_step', submission.pk, 5)
                else:
                    submission = EventSubmission(owner=request.user, title=form.cleaned_data['title'], category=form.cleaned_data['category'])
                for key, value in form.cleaned_data.items():
                    if key in FILE_FIELDS:
                        if request.FILES.get(key):
                            setattr(submission, key, value)
                    elif key == 'venue_preset':
                        if step == 2:
                            submission.venue = value
                            submission.data[key] = value.pk if value else None
                    elif key not in ('photos', 'confirm'):
                        derived_venue = step == 2 and form.cleaned_data.get('venue_mode') == 'preset' and form.cleaned_data.get('venue_preset')
                        if key not in request.POST and not isinstance(value, bool) and not (derived_venue and key in ('city', 'venue', 'address')) and key not in ('venue_mode', 'admission_mode'):
                            continue
                        submission.data[key] = value.isoformat() if isinstance(value, (date, time)) else value
                if step == 1:
                    if 'title' in request.POST:
                        submission.title = form.cleaned_data['title']
                    if not submission.submitted_at:
                        submission.category = form.cleaned_data['category']
                    submission.data['category'] = submission.category
                if step == 5 and request.POST.get('action') == 'submit':
                    # Partial drafts can visit any section; submission requires every mandatory field.
                    for previous in range(1, 5):
                        check = _saved_form(submission, previous)
                        if not check.is_valid():
                            submission.save()
                            messages.error(request, f'پیش‌نویس ذخیره شد. برای ارسال نهایی، بخش «{STEPS[previous - 1]}» را کامل کن.')
                            return redirect('accounts:event_submission_step', submission.pk, previous)
                    submission.status = 'submitted'
                    submission.submitted_at = timezone.now()
                submission.completed_step = max(submission.completed_step, step)
                submission.save()
                for photo in photos:
                    SubmissionPhoto.objects.create(submission=submission, image=photo)
                # Removing photos is owner-scoped and only allowed on a validated draft POST.
                if step == 1:
                    for photo in submission.photos.filter(pk__in=remove_ids):
                        photo.image.delete(save=False)
                        photo.delete()
            if submission.status == 'submitted':
                return redirect('accounts:event_submission_step', submission.pk, 5)
            action = request.POST.get('action', 'next')
            target = max(step - 1, 1) if action == 'previous' else min(step + 1, 5)
            requested_step = request.POST.get('target_step', '')
            if requested_step in ('1', '2', '3', '4', '5'):
                target = int(requested_step)
            if action == 'save':
                messages.success(request, 'پیش‌نویس ذخیره شد؛ هر وقت خواستی می‌توانی ادامه بدهی.')
                target = step
            return redirect('accounts:event_submission_step', submission.pk, target)
    step_links = [{'number': n, 'title': title, 'current': n == step,
                   'done': bool(submission and _saved_form(submission, n).is_valid()),
                   'url': reverse('accounts:event_submission_step', args=[submission.pk, n])
                          if submission else None}
                  for n, title in enumerate(STEPS, 1)]
    return render(request, 'accounts/submission_wizard.html', {
        'form': form, 'step': step, 'step_title': STEPS[step - 1], 'step_links': step_links,
        'submission': submission, 'review_groups': _review(submission) if step == 5 else [],
        'recent_submissions': request.user.event_submissions.all()[:8] if not submission else [],
        'selected_type': {'key': category} if category in dict(CATEGORIES) else None,
        'is_online': bool(initial.get('is_online')),
        'venue_fields': ('admission_mode', 'ticket_capacity', 'venue_mode', 'venue_preset', 'city', 'venue', 'address', 'seat_layout'),
    })


@login_required
@require_GET
def venue_preset(request, venue_id):
    """Read-only reference layout, bounded independently of stadium size."""
    venue = get_object_or_404(Stadium, pk=venue_id)
    blocks = list(venue.blocks.filter(is_active=True).annotate(
        seat_count=Count('rows__seats', filter=Q(rows__is_active=True))).order_by('order', 'pk'))
    seats = Seat.objects.filter(row__block__stadium=venue, row__block__is_active=True,
                                row__is_active=True).order_by('row__block__order', 'row__block_id', 'row__number', 'number')
    total = seats.count()
    layout = {block.pk: {'id': block.pk, 'name': block.name, 'seat_count': block.seat_count, 'rows': {}} for block in blocks}
    for seat in seats.select_related('row')[:1200]:
        section = layout[seat.row.block_id]
        row = section['rows'].setdefault(seat.row.number, {'number': seat.row.number, 'seats': []})
        row['seats'].append({'number': seat.number, 'enabled': seat.is_available})
    for section in layout.values():
        section['rows'] = list(section['rows'].values())
        saved_section = next((item for item in venue.seating_layout.get('sections', []) if item['name'] == section['name']), {})
        saved_rows = {item['number']: item for item in saved_section.get('rows', [])}
        for row in section['rows']:
            saved = saved_rows.get(row['number'], {})
            by_number = {seat['number']: seat for seat in row['seats']}
            if saved.get('seats') and all(number is None or number in by_number for number in saved['seats']):
                row['seats'] = [by_number[number] if number is not None else None for number in saved['seats']]
            row.update({key: saved.get(key, default) for key, default in
                        [('curvature', 0), ('alignment', 'start'), ('offset', 0)]})
    return JsonResponse({'id': venue.pk, 'name': venue.name, 'city': venue.city, 'address': venue.address,
                         'capacity': venue.capacity, 'seat_count': total, 'sections': list(layout.values()),
                         'stage': venue.seating_layout.get('stage', 'top'),
                         'direction': venue.seating_layout.get('direction', 'rtl'), 'truncated': total > 1200})


@login_required
@require_GET
@never_cache
def asset(request, submission_id, kind, photo_id=None):
    queryset = EventSubmission.objects.all() if request.user.is_staff else EventSubmission.objects.filter(owner=request.user)
    submission = get_object_or_404(queryset, pk=submission_id)
    if kind == 'photo' and photo_id is not None:
        file = get_object_or_404(submission.photos, pk=photo_id).image
    elif kind in FILE_FIELDS:
        file = getattr(submission, kind)
    else:
        raise Http404
    if not file:
        raise Http404
    try:
        response = FileResponse(file.open('rb'))
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class ScheduleOptionsForm(forms.Form):
    start_date = JalaliDate()
    end_date = JalaliDate()
    time = forms.TimeField()
    second_time = forms.TimeField(required=False)
    third_time = forms.TimeField(required=False)


@login_required
@never_cache
@require_GET
def schedule_options(request):
    form = ScheduleOptionsForm(request.GET)
    if not form.is_valid():
        return JsonResponse({'error': 'تاریخ آغاز، پایان و ساعت اجرا را کامل و معتبر وارد کنید.'}, status=400)
    try:
        data = {key: value.isoformat() if hasattr(value, 'isoformat') else value for key, value in form.cleaned_data.items()}
        plan = session_plan(data)
    except ValidationError as error:
        return JsonResponse({'error': error.messages[0]}, status=400)
    return JsonResponse({'sessions': [{key: value for key, value in item.items() if key != 'date_time'} for item in plan]})
