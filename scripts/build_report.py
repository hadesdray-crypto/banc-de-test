#!/usr/bin/env python3
"""Regroupe les résultats de tous les appareils dans docs/resultats/.
Usage : build_report.py DOSSIER_ARTEFACTS ID_APP NOM_APP PUBLIER(true|false) URL_RUN
"""
import glob, json, os, re, shutil, sys, datetime

arte, app_id, nom, publier, run_url = sys.argv[1:6]
publier = publier == "true"
dest = os.path.join("docs", "resultats", app_id)
shutil.rmtree(dest, ignore_errors=True)
os.makedirs(dest, exist_ok=True)

PAQUET = re.compile(r"\b(?!(?:android|androidx|java|javax|kotlin|dalvik|libcore|com\.android|org\.chromium)\.)(?:[A-Za-z][A-Za-z0-9_]*\.){2,}[A-Za-z][A-Za-z0-9_]*\b")


def propre(x):
    """Efface tout nom technique d'appli (il peut contenir un nom propre)."""
    if isinstance(x, str):
        return PAQUET.sub("<appli>", x)
    if isinstance(x, list):
        return [propre(i) for i in x]
    if isinstance(x, dict):
        return {k: propre(v) for k, v in x.items()}
    return x


appareils, total = [], 0
for d in sorted(glob.glob(os.path.join(arte, "resultats-*"))):
    nom_app = os.path.basename(d)[len("resultats-"):]
    defauts, details = [], {}
    for f in glob.glob(os.path.join(d, "explorateur_*.json")):
        r = json.load(open(f, encoding="utf-8"))
        defauts += r.get("defauts", [])
        details[r.get("mode", "?")] = {k: r[k] for k in ("etapes", "ecrans_vus", "boutons_touches", "memoire_mo", "structure_ecrans") if k in r}
    if not glob.glob(os.path.join(d, "explorateur_*.json")):
        defauts.append({"type": "pas_de_resultat", "detail": "Aucun résultat : l'émulateur n'a pas démarré ou a planté."})
    infra = [x for x in defauts if x.get("type") == "infra"]
    reels = [x for x in defauts if x.get("type") not in ("infra", "diagnostic")]
    total += len(reels)
    if publier:
        cap = os.path.join(d, "captures")
        if os.path.isdir(cap):
            shutil.copytree(cap, os.path.join(dest, nom_app, "captures"))
    appareils.append({"appareil": nom_app, "statut": "ok" if not reels and not infra else ("infra" if not reels else "defaut"),
                      "defauts": propre(defauts), "details": details})

res = {"app": nom, "id": app_id, "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
       "total_defauts": total, "captures_publiees": publier, "rapport_complet": run_url,
       "appareils": appareils}
json.dump(res, open(os.path.join(dest, "dernier.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

idx_path = os.path.join("docs", "resultats", "index.json")
idx = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else {}
idx[app_id] = {"app": nom, "date": res["date"], "total_defauts": total,
               "nb_appareils": len(appareils)}
json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Défauts au total :", total)
