"""صفحات نباید برای باز شدن به اینترنت بین‌الملل وابسته باشند.

فونت، آیکون، بوت‌استرپ و نمودار از خود پروژه سرو می‌شوند. اگر قالب دوباره
به یک CDN خارجی وصل شود، با اینترنت داخلی همان صفحه ناقص یا خالی می‌ماند.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'
ASSET_URL = re.compile(
    r"""(?:src|href)\s*=\s*['"](?:https?:)?//[^'"]+""",
    re.IGNORECASE,
)


class LocalAssetTests(SimpleTestCase):
    def test_templates_load_scripts_and_styles_from_this_site(self):
        leaks = []
        for path in sorted(TEMPLATES.rglob('*.html')):
            text = path.read_text(encoding='utf-8')
            for match in ASSET_URL.finditer(text):
                leaks.append(f'{path.relative_to(TEMPLATES)}: {match.group(0)}')
        self.assertEqual(leaks, [])
