import json
from collections import defaultdict

with open('data_matchseat_fixed.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

pair_map = defaultdict(list)
pk_map = defaultdict(list)

for obj in data:
    if obj.get("model") == "matches.matchseat":
        pair = (obj["fields"]["match"], obj["fields"]["seat"])
        pk = obj["pk"]
        pair_map[pair].append(pk)
        pk_map[pk].append(pair)

duplicate_pairs = {k: v for k, v in pair_map.items() if len(v) > 1}
duplicate_pks = {k: v for k, v in pk_map.items() if len(v) > 1}

print("duplicate pair groups:", len(duplicate_pairs))
print("duplicate pk groups:", len(duplicate_pks))

target = (4, 1)
print("target (4,1):", pair_map.get(target, []))
