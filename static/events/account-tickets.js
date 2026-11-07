
        document.addEventListener('DOMContentLoaded', function () {
            const checkboxes = document.querySelectorAll('.ticket-checkbox');
            if (!document.getElementById('selectAllBtn')) return;
            const digits = value => String(value).replace(/[0-9]/g, n => '۰۱۲۳۴۵۶۷۸۹'[n]);
            const selectAllBtn = document.getElementById('selectAllBtn');
            const deselectAllBtn = document.getElementById('deselectAllBtn');
            const downloadSelectedBtn = document.getElementById('downloadSelectedBtn');
            const shareSelectedBtn = document.getElementById('shareSelectedBtn');
            const selectedCountSpan = document.getElementById('selectedCount');
            const downloadForm = document.getElementById('downloadForm');
            const selectedContainer = document.getElementById('selectedTicketsContainer');

            function updateSelection() {
                const checked = document.querySelectorAll('.ticket-checkbox:checked');
                const count = checked.length;
                selectedCountSpan.textContent = `${digits(count)} بلیط انتخاب شده`;
                downloadSelectedBtn.disabled = count === 0;
                shareSelectedBtn.disabled = count === 0;

                document.querySelectorAll('.ticket-item').forEach(item => {
                    const cb = item.querySelector('.ticket-checkbox');
                    item.classList.toggle('selected', cb.checked);
                });

                selectedContainer.innerHTML = '';
                if (count > 0) {
                    checked.forEach(cb => {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = 'ticket_ids';
                        input.value = cb.value;
                        selectedContainer.appendChild(input);
                    });
                }
            }

            checkboxes.forEach(cb => {
                cb.addEventListener('change', updateSelection);
            });

            selectAllBtn.addEventListener('click', function () {
                checkboxes.forEach(cb => { if (!cb.disabled) cb.checked = true; });
                updateSelection();
            });

            deselectAllBtn.addEventListener('click', function () {
                checkboxes.forEach(cb => cb.checked = false);
                updateSelection();
            });

            downloadSelectedBtn.addEventListener('click', function () {
                if (document.querySelectorAll('.ticket-checkbox:checked').length > 0) {
                    downloadForm.submit();
                }
            });

            shareSelectedBtn.addEventListener('click', function () {
                const checked = document.querySelectorAll('.ticket-checkbox:checked');
                if (checked.length === 0) return;

                const cards = Array.from(checked).map(cb => cb.closest('.ticket-item'));
                const withLink = cards.filter(c => c.dataset.shareUrl);
                const withoutLink = cards.filter(c => !c.dataset.shareUrl);

                if (withLink.length === 0) {
                    alert('❌ لینک این بلیط(ها) هنوز آماده نشده. چند لحظه دیگر دوباره امتحان کنید.');
                    return;
                }

                const links = withLink.map(c => c.dataset.shareUrl);
                const shareData = links.length === 1
                    ? {
                        title: 'بلیط دیدآور',
                        text: '🎫 برای دانلود فایل PDF بلیط، لینک زیر را باز کنید:',
                        url: links[0],
                    }
                    : {
                        title: 'بلیط دیدآور',
                        text: `🎫 ${digits(links.length)} بلیط -- لینک دانلود هرکدام:\n${links.join('\n')}`,
                    };

                function fallbackCopy() {
                    const text = links.length === 1 ? links[0] : links.join('\n');
                    if (navigator.clipboard) {
                        navigator.clipboard.writeText(text).then(function () {
                            alert('✅ لینک بلیط در کلیپ‌بورد کپی شد.');
                        }).catch(function () {
                            prompt('لینک را کپی کنید:', text);
                        });
                    } else {
                        prompt('لینک را کپی کنید:', text);
                    }
                }

                if (navigator.share) {
                    navigator.share(shareData).catch(function (err) {
                        if (err.name !== 'AbortError') {
                            fallbackCopy();
                        }
                    });
                } else {
                    fallbackCopy();
                }

                if (withoutLink.length > 0) {
                    alert(`توجه: لینک ${digits(withoutLink.length)} بلیط دیگر هنوز آماده نشده و به اشتراک گذاشته نشد.`);
                }
            });

            // ===== Polling برای بلیط‌هایی که PDF‌شان هنوز در صف پس‌زمینه آماده می‌شود =====
            (function pollPendingPdfs() {
                let attempts = 0;
                const maxAttempts = 40; // با فاصله‌ی پلکانیِ پایین: چند دقیقه پوشش
                // ===== فاصله‌ی پرسش با عقب‌نشینی تدریجی =====
                // قبلاً هر ۳ ثانیه، تا ۲ دقیقه، بدون توجه به اینکه تب دیده می‌شود یا نه.
                // روز دربی این اندپوینت به ۷۱ درخواست بر ثانیه رسید. PDF معمولاً در چند
                // ثانیه‌ی اول آماده می‌شود، پس اول سریع می‌پرسیم و بعد فاصله را زیاد
                // می‌کنیم؛ و در تبِ مخفی اصلاً نمی‌پرسیم.
                function nextDelay() {
                    if (document.hidden) return 8000;
                    return Math.min(3000 + attempts * 700, 12000);
                }

                function pendingIds() {
                    return Array.from(document.querySelectorAll('.ticket-item:not([data-pdf-url])'))
                        .map(el => el.dataset.ticketId)
                        .filter(Boolean);
                }

                function tick() {
                    attempts++;
                    const ids = pendingIds();
                    if (ids.length === 0 || attempts > maxAttempts) return;

                    fetch(`${document.getElementById('ticketsGrid').dataset.pdfStatusUrl}?ids=${ids.join(',')}`)
                        .then(r => r.json())
                        .then(data => {
                            ids.forEach(id => {
                                const info = data[id];
                                if (!info || !info.ready) return;
                                const item = document.querySelector(`.ticket-item[data-ticket-id="${id}"]`);
                                if (!item) return;
                                item.dataset.pdfUrl = info.pdf_url;
                                item.dataset.shareUrl = info.share_url;
                                const slot = item.querySelector('.pdf-slot');
                                if (slot) {
                                    slot.outerHTML = `<a href="${info.pdf_url}" target="_blank" rel="noopener" class="account-btn pdf-slot"><i class="fas fa-file-pdf"></i> دانلود</a>`;
                                }
                            });
                            setTimeout(tick, nextDelay());
                        })
                        .catch(() => setTimeout(tick, 5000));
                }

                if (pendingIds().length > 0) {
                    setTimeout(tick, nextDelay());
                }
            })();
        });
