# tickets/utils.py
import requests
from django.core.cache import cache


def get_access_token():
    """دریافت توکن از API و ذخیره در کش"""
    token = cache.get('fan_token')
    if token:
        return token

    url = "https://fans.footballeticket.ir/api/v1/authenticate/login"
    payload = {
        "username": "sepahan",
        "password": "GemPNCM9bJtB"
    }

    response = requests.post(url, json=payload)
    if response.status_code == 200:
        data = response.json()
        token = data.get('token')
        cache.set('fan_token', token, timeout=3600)  # ۱ ساعت
        return token
    else:
        raise Exception("خطا در دریافت توکن")