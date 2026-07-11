import json
from collections import defaultdict

INPUT = "data.json"
OUTPUT = "data_matchseat_strict.json"

def as_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value

with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

# اول همه رکوردهای matchseat را جدا می‌کنیم.
matchseat = []
others = []

for obj in data:
    if obj.get("model") == "matches.matchseat":
        pk = as_int(obj.get("pk"))
        match_id = as_int(obj["fields"]["match"])
        seat_id = as_int(obj["fields"]["seat"])

        obj["pk"] = pk
        obj["fields"]["match"] = match_id
        obj["fields"]["seat"] = seat_id

        matchseat.append(obj)
    else:
        others.append(obj)

print("original total:", len(data))
print("original matchseat:", len(matchseat))

# برای هر pk فقط اولین رکورد را نگه می‌داریم.
by_pk = {}
removed_same_pk = []

for obj in matchseat:
    pk = obj["pk"]
    if pk in by_pk:
        removed_same_pk.append(obj)
        continue
    by_pk[pk] = obj

step1 = list(by_pk.values())

# برای هر pair فقط اولین رکورد را نگه می‌داریم.
by_pair = {}
removed_same_pair = []

for obj in step1:
    pair = (obj["fields"]["match"], obj["fields"]["seat"])
    if pair in by_pair:
        removed_same_pair.append(obj)
        continue
    by_pair[pair] = obj

clean_matchseat = list(by_pair.values())

# ترتیب کلی fixture را حفظ می‌کنیم ولی فقط matchseatهای مجاز را وارد می‌کنیم.
allowed_pks = {obj["pk"] for obj in clean_matchseat}
allowed_pairs = {(obj["fields"]["match"], obj["fields"]["seat"]) for obj in clean_matchseat}

cleaned = []
seen_pk = set()
seen_pair = set()

for obj in data:
    if obj.get("model") != "matches.matchseat":
        cleaned.append(obj)
        continue

    pk = as_int(obj.get("pk"))
    match_id = as_int(obj["fields"]["match"])
    seat_id = as_int(obj["fields"]["seat"])
    pair = (match_id, seat_id)

    if pk not in allowed_pks or pair not in allowed_pairs:
        continue
    if pk in seen_pk or pair in seen_pair:
        continue

    obj["pk"] = pk
    obj["fields"]["match"] = match_id
    obj["fields"]["seat"] = seat_id

    seen_pk.add(pk)
    seen_pair.add(pair)
    cleaned.append(obj)

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)

print("cleaned total:", len(cleaned))
print("cleaned matchseat:", len(seen_pk))
print("removed same pk:", len(removed_same_pk))
print("removed same pair:", len(removed_same_pair))

print("\nTarget pair (4,1) in cleaned:")
for obj in cleaned:
    if obj.get("model") == "matches.matchseat":
        if (obj["fields"]["match"], obj["fields"]["seat"]) == (4, 1):
            print(obj)

print("\nPK 99231 in cleaned:")
for obj in cleaned:
    if obj.get("model") == "matches.matchseat" and obj.get("pk") == 99231:
        print(obj)
