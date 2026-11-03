#!/usr/bin/env python3
"""Robot testeur : explore l'appli comme un humain (touche tous les boutons,
gratte, fait défiler, tape du texte) et note les défauts.

Usage : explorer.py PAQUET DOSSIER_SORTIE ETIQUETTE [MAX_ETAPES]
"""
import hashlib, json, os, re, subprocess, sys, time
import xml.etree.ElementTree as ET

PKG, OUT, LABEL = sys.argv[1], sys.argv[2], sys.argv[3]
MAX_STEPS = int(sys.argv[4]) if len(sys.argv) > 4 else 120
SHOTS = os.path.join(OUT, "captures")
os.makedirs(SHOTS, exist_ok=True)

defects, screens, tapped = [], {}, set()
steps = 0


def adb(*a, timeout=30):
    try:
        r = subprocess.run(["adb", *a], capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def defect(kind, text):
    d = {"type": kind, "detail": text, "etape": steps, "mode": LABEL}
    if d not in defects:
        defects.append(d)
        print("DEFAUT", kind, text, flush=True)


def screen_size():
    m = re.search(r"(\d+)x(\d+)", adb("shell", "wm", "size").split("Override")[-1])
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


def shot(name):
    p = os.path.join(SHOTS, "%s_%s.png" % (LABEL, name))
    with open(p, "wb") as f:
        f.write(subprocess.run(["adb", "exec-out", "screencap", "-p"],
                               capture_output=True, timeout=30).stdout)


def focus_pkg():
    out = adb("shell", "dumpsys", "window")
    m = re.search(r"mCurrentFocus=.*? ([\w.]+)/", out)
    return m.group(1) if m else ""


def alive():
    return bool(adb("shell", "pidof", PKG).strip())


def launch():
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(3)


def dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    xml = adb("exec-out", "cat", "/sdcard/ui.xml")
    try:
        return ET.fromstring(xml[xml.index("<"):])
    except Exception:
        return None


def nodes(root):
    for n in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if m:
            yield n, tuple(int(x) for x in m.groups())


def tap(x, y):
    adb("shell", "input", "tap", str(x), str(y))
    time.sleep(0.9)


def swipe(x1, y1, x2, y2, ms=300):
    adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))
    time.sleep(0.5)


def scratch(W, H):
    """Geste de grattage : zigzag au centre de l'écran."""
    y = int(H * 0.35)
    for i in range(5):
        swipe(int(W * 0.15), y + i * int(H * 0.06), int(W * 0.85), y + i * int(H * 0.06), 220)


def check_crash():
    crash = adb("logcat", "-d", "-b", "crash")
    if PKG in crash and "FATAL EXCEPTION" in crash:
        defect("plantage", "L'appli a planté (voir journal).")
        with open(os.path.join(OUT, "crash_%s.txt" % LABEL), "w", encoding="utf-8") as f:
            f.write(crash[-6000:])
        adb("logcat", "-c")
        return True
    if "ANR in " + PKG in adb("logcat", "-d", "-b", "events", "-t", "200") or \
       "ANR in " + PKG in adb("logcat", "-d", "-t", "400"):
        defect("blocage", "L'appli ne répond plus (ANR).")
    return False


def main():
    global steps
    W, H = screen_size()
    adb("logcat", "-c")
    launch()
    shot("00_ouverture")
    stale = 0
    while steps < MAX_STEPS and stale < 12:
        steps += 1
        if not alive():
            defect("plantage", "L'appli est fermée de façon inattendue.")
            check_crash()
            launch()
        if focus_pkg() not in (PKG, ""):
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1)
            if focus_pkg() != PKG:
                launch()
            continue
        root = dump_ui()
        if root is None:
            stale += 1
            continue
        items = list(nodes(root))
        sig = hashlib.md5("|".join(sorted(
            "%s%s%s" % (n.get("class"), n.get("resource-id"), n.get("text"))
            for n, _ in items)).encode()).hexdigest()[:10]
        new_screen = sig not in screens
        if new_screen:
            screens[sig] = steps
            stale = 0
            shot("%03d_ecran_%s" % (steps, sig))
            scratch(W, H)  # geste de grattage / glissement sur chaque nouvel écran
            if len(items) < 2:
                defect("ecran_vide", "Écran presque vide (%s)." % sig)
        # défauts d'affichage : boutons hors écran ou trop petits
        cands = []
        for n, (x1, y1, x2, y2) in items:
            if n.get("clickable") != "true" or n.get("enabled") != "true":
                continue
            lab = n.get("text") or n.get("content-desc") or n.get("resource-id") or "bouton"
            if x2 <= 0 or y2 <= 0 or x1 >= W or y1 >= H:
                defect("bouton_hors_ecran", "« %s » est hors de l'écran." % lab[:40])
                continue
            if x1 < -2 or x2 > W + 2 or y2 > H + 2:
                defect("bouton_coupe", "« %s » dépasse de l'écran." % lab[:40])
            if (x2 - x1) < 40 or (y2 - y1) < 40:
                defect("bouton_trop_petit", "« %s » est trop petit pour un doigt." % lab[:40])
            if not (n.get("text") or n.get("content-desc")) and n.get("class", "").endswith("ImageView"):
                defect("bouton_sans_nom", "Un bouton image n'a pas d'étiquette (%s)." % sig)
            key = (sig, n.get("resource-id"), lab, x1, y1)
            if key not in tapped:
                cands.append((key, (x1 + x2) // 2, (y1 + y2) // 2, n))
        # champs de texte : vide, accents, très long
        for n, (x1, y1, x2, y2) in items:
            if n.get("class", "").endswith("EditText") and ("t", sig, x1, y1) not in tapped:
                tapped.add(("t", sig, x1, y1))
                tap((x1 + x2) // 2, (y1 + y2) // 2)
                adb("shell", "input", "text", "test%sAAAA" % ("A" * 250))
                adb("shell", "input", "keyevent", "KEYCODE_ENTER")
                time.sleep(0.8)
        if cands:
            key, x, y, _ = cands[0]
            tapped.add(key)
            tap(x, y)
            if check_crash():
                shot("%03d_apres_plantage" % steps)
                launch()
            continue
        # plus rien à toucher ici : défilement puis retour
        stale += 1
        swipe(W // 2, int(H * 0.75), W // 2, int(H * 0.25))
        if stale % 3 == 0:
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1)
    shot("99_fin")
    check_crash()
    res = {"mode": LABEL, "etapes": steps, "ecrans_vus": len(screens),
           "boutons_touches": len([k for k in tapped if k[0] != "t"]), "defauts": defects}
    with open(os.path.join(OUT, "explorateur_%s.json" % LABEL), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


main()
