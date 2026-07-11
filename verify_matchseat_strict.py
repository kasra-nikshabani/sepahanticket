import json
from collections import defaultdict

with open("data_matchseat_strict.json", "r", encoding="utf-8") as f:
    data = json.load(f)

pairs = defaultdict(list)
pks = defaultdict(list)

for obj in data:
    if obj.get("model") != "matches.matchseat":
        continue

    pk = obj["pk"]
    pair = (obj["fields"]["match"], obj["fields"]["seat"])

    pairs[pair].append(pk)
    pks[pk].append(pair)

dup_pairs = {k: v for k, v in pairs.items() if len(v) > 1}
dup_pks = {k: v for k, v in pks.items() if len(v) > 1}

print("matchseat count:", sum(len(v) for v in pairs.values()))
print("duplicate pair groups:", len(dup_pairs))
print("duplicate pk groups:", len(dup_pks))
print("target pair (4,1):", pairs.get((4, 1), []))
print("target pk 99231:", pks.get(99231, []))

if dup_pairs:
    print("sample duplicate pairs:")
    for k, v in list(dup_pairs.items())[:10]:
        print(k, v)

if dup_pks:
    print("sample duplicate pks:")
    for k, v in list(dup_pks.items())[:10]:
        print(k, v)
