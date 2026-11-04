#!/usr/bin/env python3
"""Scénarios « vie réelle » : ce qui arrive vraiment à une appli sur un téléphone.
Usage : scenarios.py PAQUET DOSSIER_SORTIE APK
Chaque scénario réussi ou raté est listé ; seuls les ratés sont des défauts.
"""
import json, os, re, subprocess, sys, time

PKG, OUT, APK = sys.argv[1], sys.argv[2], sys.argv[3]
defauts, faits = [], []


def adb(*a, t=40):
    try:
        return subprocess.run(["adb", *a], capture_output=True, timeout=t).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def sh(*a, t=40):
    return adb("shell", *a, t=t)


def vivant():
    return bool(sh("pidof", PKG).strip())


def lancer():
    sh("monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    for _ in range(20):
        if vivant():
            break
        time.sleep(1)
    time.sleep(4)


def plante():
    c = adb("logcat", "-d", "-b", "crash")
    adb("logcat", "-c")
    return PKG in c and "FATAL EXCEPTION" in c


def ecran_non_vide():
    sh("uiautomator", "dump", "/sdcard/s.xml", t=40)
    x = sh("cat", "/sdcard/s.xml")
    return x.count("<node") >= 2


def scenario(nom, texte_defaut):
    def deco(f):
        def run():
            adb("logcat", "-c")
            try:
                ok = f()
            except Exception as e:  # le banc ne doit jamais s'arrêter
                ok = None
                faits.append({"nom": nom, "resultat": "non vérifié", "raison": str(e)[:80]})
                return
            if ok and not plante():
                faits.append({"nom": nom, "resultat": "ok"})
            else:
                faits.append({"nom": nom, "resultat": "défaut"})
                defauts.append({"type": "scenario_" + nom, "detail": texte_defaut, "mode": "scenarios"})
        return run
    return deco


LISTE = []
_scen = scenario


def scenario(nom, texte):
    d = _scen(nom, texte)

    def enreg(f):
        r = d(f)
        LISTE.append(r)
        return r
    return enreg


@scenario("maison_et_reprise", "Après un appui sur Accueil puis retour dans l'appli, elle plante ou reste vide.")
def _():
    lancer(); sh("input", "keyevent", "KEYCODE_HOME"); time.sleep(6); lancer()
    return vivant() and ecran_non_vide()


@scenario("fermee_puis_relancee", "Après fermeture forcée puis réouverture, l'appli plante ou reste vide.")
def _():
    lancer(); sh("am", "force-stop", PKG); time.sleep(2); lancer()
    return vivant() and ecran_non_vide()


@scenario("bouton_retour", "Le bouton retour d'Android fait planter l'appli.")
def _():
    lancer()
    for _ in range(6):
        sh("input", "keyevent", "KEYCODE_BACK"); time.sleep(1)
    lancer()
    return vivant()


@scenario("rotation_rapide", "Tourner plusieurs fois l'écran vite fait planter l'appli.")
def _():
    lancer()
    for i in range(8):
        sh("settings", "put", "system", "user_rotation", str(i % 2)); time.sleep(1.2)
    sh("settings", "put", "system", "user_rotation", "0")
    time.sleep(3)
    return vivant() and ecran_non_vide()


@scenario("memoire_faible", "Quand le téléphone manque de mémoire, l'appli ne se rouvre pas correctement.")
def _():
    lancer(); sh("input", "keyevent", "KEYCODE_HOME"); time.sleep(2)
    sh("am", "send-trim-memory", PKG, "COMPLETE"); time.sleep(3)
    sh("am", "kill", PKG); time.sleep(2); lancer()
    return vivant() and ecran_non_vide()


@scenario("mise_a_jour_sur_place", "La mise à jour par-dessus l'ancienne version échoue ou l'appli ne s'ouvre plus ensuite.")
def _():
    lancer()
    r = adb("install", "-r", APK, t=180)
    if "Success" not in r:
        return False
    lancer()
    return vivant() and ecran_non_vide()


@scenario("stockage_plein", "Avec le stockage presque plein, l'appli plante.")
def _():
    df = sh("df", "/data").splitlines()
    libre_ko = int(df[-1].split()[3]) if len(df) > 1 else 0
    if libre_ko < 200000:
        raise RuntimeError("place insuffisante pour simuler")
    sh("fallocate", "-l", str(max(libre_ko - 40000, 1) * 1024), "/data/local/tmp/plein", t=120)
    try:
        sh("am", "force-stop", PKG); lancer()
        sh("input", "keyevent", "KEYCODE_BACK")
        return vivant()
    finally:
        sh("rm", "-f", "/data/local/tmp/plein")


@scenario("mode_avion_puis_retour_reseau", "Couper puis rétablir la connexion fait planter l'appli.")
def _():
    lancer()
    sh("cmd", "connectivity", "airplane-mode", "enable"); time.sleep(6)
    sh("input", "tap", "540", "900"); time.sleep(2)
    sh("cmd", "connectivity", "airplane-mode", "disable"); time.sleep(8)
    return vivant()


# Chaque scénario, puis les erreurs JavaScript vues dans le journal
for run in LISTE:
    run()
journal = adb("logcat", "-d", t=60)
erreurs = sorted({re.sub(r"\s+", " ", l)[-160:] for l in journal.splitlines()
                  if re.search(r"(Uncaught|SyntaxError|ReferenceError|TypeError)", l) and "CONSOLE" in l.upper()})
if erreurs:
    defauts.append({"type": "erreur_javascript", "detail": "Erreurs dans le code de l'appli : " + " || ".join(erreurs[:5]).replace(PKG, "<appli>"), "mode": "scenarios"})
json.dump({"mode": "scenarios", "defauts": defauts, "scenarios": faits},
          open(os.path.join(OUT, "explorateur_scenarios.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
