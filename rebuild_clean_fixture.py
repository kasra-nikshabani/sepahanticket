import json

with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

cleaned = []
seen_matchseat_pairs = set()
seen_matchseat_pks = set()

removed_pair_duplicates = []
removed_pk_duplicates = []

for obj in data:
    if obj.get("model") != "matches.matchseat":
        cleaned.append(obj)
        continue

    pk = obj["pk"]
    pair = (obj["fields"]["match"], obj["fields"]["seat"])

    if pk in seen_matchseat_pks:
        removed_pk_duplicates.append({
            "pk": pk,
            "pair": pair,
        })
        continue

    if pair in seen_matchseat_pairs:
        removed_pair_duplicates.append({
            "pk": pk,
            "pair": pair,
        })
        continue

    seen_matchseat_pks.add(pk)
    seen_matchseat_pairs.add(pair)
    cleaned.append(obj)

with open('data_matchseat_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)

print("original objects:", len(data))
print("cleaned objects:", len(cleaned))
print("removed pair duplicates:", len(removed_pair_duplicates))
print("removed pk duplicates:", len(removed_pk_duplicates))

print("\nSample removed pair duplicates:")
for item in removed_pair_duplicates[:20]:
    print(item)

print("\nSample removed pk duplicates:")
for item in removed_pk_duplicates[:20]:
    print(item)
