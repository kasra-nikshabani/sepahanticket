// بستن سایدبار با کلیک بیرون
document.addEventListener('click', function(e) {
    const sidebar = document.querySelector('.admin-sidebar');
    const toggle = document.getElementById('sidebarToggle');
    if (window.innerWidth <= 992 && sidebar && toggle) {
        if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
            sidebar.classList.add('sidebar-collapsed');
        }
    }
});