import json
import sys

input_file = 'seats_full.json'
output_file = 'seats_full_clean.json'

print("در حال خواندن فایل ...")
with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"تعداد کل رکوردها: {len(data)}")

seen = set()
unique_data = []

for obj in data:
    model = obj.get('model')
    fields = obj.get('fields', {})

    if model == 'matches.matchseat':
        key = (fields.get('match_id'), fields.get('seat_id'))
    else:
        pk = obj.get('pk')
        if pk is not None:
            key = (model, pk)
        else:
            # اگر pk نبود، از ترکیب مدل و فیلدها استفاده کن
            key = (model, tuple(sorted(fields.items())))

    if key not in seen:
        seen.add(key)
        unique_data.append(obj)

print(f"تعداد رکوردهای یکتا: {len(unique_data)}")
print(f"تعداد حذف شده: {len(data) - len(unique_data)}")

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(unique_data, f, indent=2, ensure_ascii=False)

print("فایل پاک‌شده با نام seats_full_clean.json ذخیره شد.")
