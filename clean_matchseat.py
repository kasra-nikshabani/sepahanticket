import json

with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

seen = set()
cleaned = []
removed = []

for obj in data:
    if obj.get("model") == "matches.matchseat":
        key = (obj["fields"]["match"], obj["fields"]["seat"])
        if key in seen:
            removed.append((obj["pk"], key))
            continue
        seen.add(key)

    cleaned.append(obj)

with open('data_clean.json', 'w', encoding='utf-8') as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)

print("original objects:", len(data))
print("cleaned objects:", len(cleaned))
print("removed duplicates:", len(removed))

for pk, key in removed[:50]:
    print(f"removed pk={pk}, match={key[0]}, seat={key[1]}")
