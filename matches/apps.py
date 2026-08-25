from django.apps import AppConfig

class MatchesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'matches'

    def ready(self):
        import matches.signals
        # لوگوهای تیم (Match.home_team_logo/away_team_logo) از پنل ادمین
        # آپلود می‌شن؛ خیلی از ادمین‌ها با آیفون عکس می‌گیرن که پیش‌فرض HEIC
        # ذخیره می‌کنه -- Pillow خودش HEIC رو نمی‌فهمه، این پلاگین اون رو به
        # فرمت‌های شناخته‌شده (JPEG/PNG/...) اضافه می‌کنه تا آپلود مستقیم
        # قبول بشه، بدون نیاز به تبدیل دستی توسط کاربر.
        import pillow_heif
        pillow_heif.register_heif_opener()