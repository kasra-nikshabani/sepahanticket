import json

with open('full_dump.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

seen = set()
unique_data = []

for obj in data:
    model = obj['model']
    fields = obj['fields']

    # کلید یکتا برای مدل‌های مشکل‌ساز
    if model == 'wallet.wallet':
        key = ('wallet', fields['user_id'])
    elif model == 'matches.matchseat':
        key = ('matchseat', fields['match_id'], fields['seat_id'])
    else:
        # برای بقیه، از pk استفاده کن
        pk = obj.get('pk')
        if pk is not None:
            key = (model, pk)
        else:
            # اگر pk نبود، از ترکیب مدل و فیلدها استفاده کن
            key = (model, tuple(sorted(fields.items())))

    if key not in seen:
        seen.add(key)
        unique_data.append(obj)

with open('full_dump_clean.json', 'w', encoding='utf-8') as f:
    json.dump(unique_data, f, indent=2, ensure_ascii=False)

print(f"تعداد کل: {len(data)}")
print(f"تعداد یکتا: {len(unique_data)}")
print(f"حذف شده: {len(data) - len(unique_data)}")