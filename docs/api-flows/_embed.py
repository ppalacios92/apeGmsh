"""Re-embed flows.json into atlas.html and validate.

The Atlas (atlas.html) fetches ./flows.json first; opened by
double-click (file://) browsers block that fetch, so it falls back to
a copy embedded in the <script id="flows-data"> block.

flows.json is the source of truth.  After editing it, run:

    python docs/api-flows/_embed.py

to refresh the embedded fallback (serving the folder needs no re-embed).
Idempotent: it replaces whatever currently sits in the block.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "atlas.html")
JSON = os.path.join(HERE, "flows.json")

raw = open(JSON, "r", encoding="utf-8").read()
doc = json.loads(raw)                       # flows.json must be valid JSON
safe = raw.replace("</", "<\\/")            # guard the only <script> breaker
assert "</script" not in safe.lower()

html = open(HTML, "r", encoding="utf-8").read()
pat = re.compile(
    r'(<script id="flows-data" type="application/json">).*?(</script>)', re.S)
assert len(pat.findall(html)) == 1, "embed block not found exactly once"
html = pat.sub(lambda m: m.group(1) + safe + m.group(2), html, count=1)
assert 'raw !== "EMBED_FLOWS_JSON"' in html, "JS sentinel clobbered"

# round-trip + referential integrity
back = json.loads(pat.search(html).group(0)
                   .split(">", 1)[1].rsplit("<", 1)[0].replace("<\\/", "</"))
assert back == doc, "embedded copy != flows.json"
nids = {n["id"] for n in doc["nodes"]}
gids = {g["id"] for g in doc["groups"]}
bad = [n["id"] for n in doc["nodes"] if n["group"] not in gids]
bad += [f"{e['from']}->{e['to']}" for e in doc["edges"]
        if e["from"] not in nids or e["to"] not in nids]
bad += [m["id"] for m in doc["methods"] for s in m.get("flow", [])
        if s.get("node") not in nids or s.get("to") not in nids]

open(HTML, "w", encoding="utf-8").write(html)
print(f"embedded {len(doc['methods'])} methods / {len(doc['nodes'])} nodes / "
      f"{len(doc['edges'])} edges  ->  atlas.html "
      f"({os.path.getsize(HTML):,} bytes)")
print("referential integrity:", "OK" if not bad else f"PROBLEMS {bad[:10]}")
