// بستن کشوی سایدبار موبایل با کلیک بیرون
// (قبلاً این‌جا کلاس sidebar-collapsed اضافه می‌شد که یک قانون CSS قدیمی و
// متعارض در style.css را فعال می‌کرد -- درست همان کلاسی که سیستم کشوی جدید
// در base.html (mobile-open) استفاده نمی‌کند، پس این دو با هم تداخل داشتند
// و باز/بسته شدن منو غیرقابل‌اعتماد می‌شد.)
document.addEventListener('click', function (e) {
    const sidebar = document.querySelector('.admin-sidebar');
    const toggle = document.getElementById('sidebarToggle');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (window.innerWidth <= 767.98 && sidebar && toggle) {
        if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
            sidebar.classList.remove('mobile-open');
            if (backdrop) backdrop.classList.remove('show');
        }
    }
});