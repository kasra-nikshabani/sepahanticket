import json
import hashlib

input_file = 'data_dump_no_matchseat.json'
output_file = 'data_dump_clean.json'

with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

seen = set()
unique_data = []

for obj in data:
    model = obj['model']
    fields = obj['fields']

    # کلید یکتا بر اساس مدل
    if model == 'wallet.wallet':
        # هر کاربر فقط یک کیف پول داره
        key = ('wallet', fields['user_id'])
    elif model == 'matches.matchseat':
        # هر صندلی در هر مسابقه یکتاست
        key = ('matchseat', fields['match_id'], fields['seat_id'])
    else:
        # برای بقیه مدل‌ها، از pk استفاده کن
        pk = obj.get('pk')
        if pk is not None:
            key = (model, pk)
        else:
            # اگه pk نبود، از هش تمام فیلدها استفاده کن
            fields_str = json.dumps(fields, sort_keys=True, ensure_ascii=False)
            fields_hash = hashlib.md5(fields_str.encode('utf-8')).hexdigest()
            key = (model, fields_hash)

    if key not in seen:
        seen.add(key)
        unique_data.append(obj)

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(unique_data, f, indent=2, ensure_ascii=False)

print(f"تعداد کل رکوردها: {len(data)}")
print(f"تعداد رکوردهای یکتا: {len(unique_data)}")
print(f"تعداد رکوردهای تکراری حذف شده: {len(data) - len(unique_data)}")