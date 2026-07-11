import json
from collections import defaultdict, Counter

with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

matchseat_rows = []
for obj in data:
    if obj.get("model") == "matches.matchseat":
        match_id = obj["fields"]["match"]
        seat_id = obj["fields"]["seat"]
        pk = obj["pk"]
        matchseat_rows.append({
            "pk": pk,
            "match": match_id,
            "seat": seat_id,
            "obj": obj,
        })

print("total matchseat rows:", len(matchseat_rows))

pair_map = defaultdict(list)
pk_map = defaultdict(list)

for row in matchseat_rows:
    pair_map[(row["match"], row["seat"])].append(row["pk"])
    pk_map[row["pk"]].append((row["match"], row["seat"]))

duplicate_pairs = {k: v for k, v in pair_map.items() if len(v) > 1}
duplicate_pks = {k: v for k, v in pk_map.items() if len(v) > 1}

print("duplicate (match,seat) groups:", len(duplicate_pairs))
for i, (k, v) in enumerate(duplicate_pairs.items()):
    if i >= 20:
        break
    print("PAIR", k, "PKS", v)

print("duplicate pk groups:", len(duplicate_pks))
for i, (k, v) in enumerate(duplicate_pks.items()):
    if i >= 20:
        break
    print("PK", k, "PAIRS", v)

target = (4, 1)
print("\nRows for target (4,1):")
for row in matchseat_rows:
    if (row["match"], row["seat"]) == target:
        print(json.dumps(row["obj"], ensure_ascii=False, indent=2))
