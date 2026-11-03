#!/usr/bin/env python3
"""Fabrique la matrice d'appareils pour GitHub Actions et la sortie 'app'."""
import json, os, sys

app_id, complet = sys.argv[1], sys.argv[2] == "true"
unseul = sys.argv[3] if len(sys.argv) > 3 else ""
apps = {a["id"]: a for a in json.load(open("apps.json", encoding="utf-8"))["apps"]}
if app_id not in apps:
    sys.exit("Application inconnue : %s (voir apps.json)" % app_id)
app = apps[app_id]
tous = json.load(open("profiles.json", encoding="utf-8"))["appareils"]
devs = [d for d in tous if d["nom"] == unseul] if unseul else [d for d in tous if complet or d.get("rapide")]
if not devs:
    sys.exit("Aucun appareil ne correspond.")
out = os.environ["GITHUB_OUTPUT"]
with open(out, "a", encoding="utf-8") as f:
    f.write("matrix=%s\n" % json.dumps({"include": devs}))
    f.write("repo=%s\n" % app["repo"])
    f.write("publier=%s\n" % str(app.get("publier_captures", False)).lower())
