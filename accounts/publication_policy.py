"""Published programs can only be changed through staff management."""
from urllib.parse import urlencode
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse


def change_request_url(program):
    return reverse('accounts:support_create') + '?' + urlencode({
        'category': 'program', 'event': program.published_event_id, 'change': '1'})


def published_change_response(request, program):
    url = change_request_url(program)
    if request.method == 'GET':
        messages.info(request, 'برنامه منتشر شده است؛ درخواست هر تغییر را از طریق تیکت برای ادمین ارسال کنید.')
        return redirect(url)
    return render(request, 'accounts/program_locked.html', {'program': program, 'change_url': url}, status=403)
