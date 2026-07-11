import json
from collections import Counter

file = 'data_clean.json'
try:
    with open(file, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    file = 'data.json'
    with open(file, 'r', encoding='utf-8') as f:
        data = json.load(f)

pairs = []
for obj in data:
    if obj.get("model") == "matches.matchseat":
        pairs.append((obj["fields"]["match"], obj["fields"]["seat"], obj["pk"]))

counter = Counter((m, s) for m, s, pk in pairs)
dupes = [(m, s, c) for (m, s), c in counter.items() if c > 1]

print("file:", file)
print("MatchSeat rows:", len(pairs))
print("duplicate groups:", len(dupes))

for m, s, c in dupes[:50]:
    pks = [pk for mm, ss, pk in pairs if mm == m and ss == s]
    print(f"match={m}, seat={s}, count={c}, pks={pks}")
