#!/usr/bin/env python3
"""Robot testeur : explore l'appli comme un humain (touche tous les boutons,
gratte, fait défiler, tape du texte) et note les défauts.

Usage : explorer.py PAQUET DOSSIER_SORTIE ETIQUETTE [MAX_ETAPES]
"""
import hashlib, json, os, re, signal, subprocess, sys, time
import xml.etree.ElementTree as ET

PKG, OUT, LABEL = sys.argv[1], sys.argv[2], sys.argv[3]
MAX_STEPS = int(sys.argv[4]) if len(sys.argv) > 4 else 120
SHOTS = os.path.join(OUT, "captures")
os.makedirs(SHOTS, exist_ok=True)

defects, screens, tapped, stats, known = [], {}, set(), [], []
steps = 0


def adb(*a, timeout=30):
    try:
        r = subprocess.run(["adb", *a], capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def scrub(t):
    """Jamais le nom technique de l'appli dans un rapport (il peut contenir un nom propre)."""
    return t.replace(PKG, "<appli>")


def defect(kind, text):
    d = {"type": kind, "detail": scrub(text), "etape": steps, "mode": LABEL}
    if d not in defects:
        defects.append(d)
        print("DEFAUT", kind, text, flush=True)


def screen_size():
    m = re.search(r"(\d+)x(\d+)", adb("shell", "wm", "size").split("Override")[-1])
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


NSHOT = 0


def shot(name):
    """Capture réduite (JPEG ~480 px) pour garder le dépôt léger ; 14 par phase au plus."""
    global NSHOT
    if NSHOT >= 14 and not name.startswith(("99", "00")):
        return
    NSHOT += 1
    png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True, timeout=30).stdout
    base = os.path.join(SHOTS, "%s_%s" % (LABEL, name))
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.thumbnail((480, 480))
        im.save(base + ".jpg", quality=60)
    except Exception:
        with open(base + ".png", "wb") as f:
            f.write(png)


def hote():
    """État du serveur au moment où l'émulateur disparaît (mémoire, processus, journal noyau)."""
    def sh(c):
        try:
            return subprocess.run(c, shell=True, capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
        except Exception:
            return ""
    mem = " ".join(sh("free -m | sed -n 2p").split())
    proc = sh("pgrep -fc qemu-system").strip()
    noyau = " / ".join(l[-110:] for l in sh("sudo dmesg 2>/dev/null | grep -i -E 'oom|killed process|segfault' | tail -3").splitlines())
    return ("mem[%s] qemu=%s noyau[%s]" % (mem, proc, noyau))[:500]


def device_ok():
    return adb("get-state", timeout=15).strip() == "device"


def attendre_changement(max_s=90):
    """Écran d'ouverture : attend qu'il change (chargement). Sinon, c'est un défaut."""
    v0 = vis()
    if v0 is None:
        return True
    t0 = time.time()
    while time.time() - t0 < max_s:
        time.sleep(5)
        v = vis()
        if v is not None and bin(v ^ v0).count("1") > 10:
            return True
    return False


def vis():
    """Empreinte visuelle 8x8 de l'écran (None si Pillow absent)."""
    try:
        from PIL import Image
        import io
        png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True, timeout=30).stdout
        im = Image.open(io.BytesIO(png)).convert("L").resize((8, 8))
        px = list(im.getdata()); avg = sum(px) / 64
        return sum(1 << i for i, v in enumerate(px) if v > avg)
    except Exception:
        return None


def etat(sig, v):
    """Numéro d'état d'écran : structure identique ET image proche, sinon nouvel état."""
    for i, (s2, v2) in enumerate(known):
        if s2 == sig and (v is None or v2 is None or bin(v ^ v2).count("1") <= 10):
            return i, False
    known.append((sig, v))
    return len(known) - 1, True


def focus_pkg():
    out = adb("shell", "dumpsys", "window")
    m = re.search(r"mCurrentFocus=.*? ([\w.]+)/", out)
    return m.group(1) if m else ""


def alive():
    return bool(adb("shell", "pidof", PKG).strip())


LAST_LAUNCH = ""


def launch():
    global LAST_LAUNCH
    LAST_LAUNCH = adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    for _ in range(25):
        time.sleep(1)
        if alive():
            break
    time.sleep(3)


def crash_summary():
    """Résumé court des causes probables (sans texte de l'appli)."""
    pat = re.compile(r"FATAL|Exception|Caused by|has died|Force finishing|ANR|not responding|"
                     r"Killing|SIGSEGV|Abort|lowmemory|denied|Permission|crash", re.I)
    bits = []
    for buf in ("crash", "main"):
        for l in adb("logcat", "-d", "-b", buf, "-t", "400").splitlines():
            if pat.search(l) and (PKG in l or buf == "crash" or "ActivityManager" in l):
                bits.append(scrub(l.split(": ", 1)[-1].strip())[:140])
    seen, out = set(), []
    for b in bits:
        if b not in seen:
            seen.add(b); out.append(b)
    txt = " | ".join(out[:6])
    return (txt or "aucune cause trouvée dans le journal")[:600]


def diagnostic():
    """Infos pour comprendre pourquoi l'appli ne démarre pas (sans texte d'appli)."""
    out = []
    out.append("android=" + adb("shell", "getprop", "ro.build.version.release").strip()
               + " abis=" + adb("shell", "getprop", "ro.product.cpu.abilist").strip())
    for wp in ("com.google.android.webview", "com.android.webview", "com.android.chrome"):
        for l in adb("shell", "dumpsys", "package", wp).splitlines():
            if "versionName" in l:
                out.append("%s %s" % (wp.split(".")[-1], l.strip()[:40])); break
    for l in adb("shell", "dumpsys", "package", PKG).splitlines():
        if re.search(r"primaryCpuAbi|secondaryCpuAbi|targetSdk|minSdk|versionName|flags=", l):
            out.append(l.strip()[:90])
    out.append("activite=" + adb("shell", "cmd", "package", "resolve-activity", "--brief", PKG).strip().replace("\n", " ")[-120:])
    pat = re.compile(r"CONSOLE|Uncaught|SyntaxError|ReferenceError|TypeError|net::ERR|AndroidRuntime|FATAL|linker|dlopen|ndk_translation|UnsatisfiedLink|has died|am_proc_died|"
                     r"am_crash|Force finishing|SIGSEGV|Abort|Not an ELF|library|chromium|WebView|denied", re.I)
    lines = [l for l in adb("logcat", "-d", "-t", "1500").splitlines() if pat.search(l) and (PKG in l or "ActivityManager" in l or "linker" in l or "AndroidRuntime" in l or "chromium" in l.lower())]
    out += [l.split(": ", 1)[-1].strip()[:150] for l in lines[-12:]]
    return scrub(" ## ".join(out))[:1400]


def dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    xml = adb("exec-out", "cat", "/sdcard/ui.xml")
    try:
        return ET.fromstring(xml[xml.index("<"):])
    except Exception:
        return None


def nodes(root, in_web=False):
    """Parcourt l'arbre ; ajoute n.set('web','1') pour les éléments d'une appli web."""
    stack = [(root, False)]
    while stack:
        n, web = stack.pop()
        web = web or n.get("class") == "android.webkit.WebView"
        if n.tag == "node":
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
            if m:
                n.set("web", "1" if web else "0")
                yield n, tuple(int(x) for x in m.groups())
        for c in reversed(list(n)):
            stack.append((c, web))


def tappable(n):
    """Cliquable pour Android, ou élément d'une appli web avec un nom / focus."""
    if n.get("enabled") != "true":
        return False
    if n.get("clickable") == "true" or n.get("long-clickable") == "true":
        return True
    if n.get("web") == "1" and (n.get("text") or n.get("content-desc")) and \
            n.get("class") in ("android.view.View", "android.widget.Button", "android.widget.ImageView", "android.widget.TextView"):
        return True
    return False


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


def ecrire_resultat():
    res = {"mode": LABEL, "etapes": steps, "ecrans_vus": len(screens),
           "boutons_touches": len([k for k in tapped if k[0] not in ("t", "g")]),
           "structure_ecrans": stats[:12], "defauts": defects}
    with open(os.path.join(OUT, "explorateur_%s.json" % LABEL), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


def main():
    global steps
    W, H = screen_size()
    adb("logcat", "-c")
    launch()
    shot("00_ouverture")
    stale = 0
    if LABEL == "normal" and not attendre_changement(90):
        defect("ecran_bloque", "L'écran d'ouverture ne change pas après 90 secondes.")
        defect("diagnostic", diagnostic())
    while steps < MAX_STEPS and stale < 12:
        steps += 1
        if not device_ok():
            adb("reconnect", timeout=20)
            time.sleep(10)
            if not device_ok():
                defect("infra", "Émulateur injoignable (problème du banc de test, pas de l'appli). Hôte : " + hote())
                break
        if not alive():
            defect("plantage", "L'appli est fermée de façon inattendue. " + crash_summary())
            if not any(d["type"] == "diagnostic" for d in defects):
                defect("diagnostic", diagnostic())
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
        sid, new_screen = etat(sig, vis())
        if new_screen:
            screens[sid] = steps
            stale = 0
            shot("%03d_ecran_%d" % (steps, sid))
            stats.append({"noeuds": len(items), "cliquables": sum(1 for n, _ in items if n.get("clickable") == "true"),
                          "web": sum(1 for n, _ in items if n.get("web") == "1"),
                          "touchables": sum(1 for n, _ in items if tappable(n)),
                          "textes": [t[:24] for t in [(n.get("text") or n.get("content-desc") or "") for n, _ in items] if t][:12]})
            scratch(W, H)  # geste de grattage / glissement sur chaque nouvel écran
            if len(items) < 2:
                defect("ecran_vide", "Écran presque vide (état %d)." % sid)
        # défauts d'affichage : boutons hors écran ou trop petits
        cands = []
        for n, (x1, y1, x2, y2) in items:
            if not tappable(n):
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
                defect("bouton_sans_nom", "Un bouton image n'a pas d'étiquette (état %d)." % sid)
            key = (sid, n.get("resource-id"), lab, x1, y1)
            if key not in tapped:
                cands.append((key, (x1 + x2) // 2, (y1 + y2) // 2, n))
        # champs de texte : vide, accents, très long
        for n, (x1, y1, x2, y2) in items:
            if n.get("class", "").endswith("EditText") and ("t", sid, x1, y1) not in tapped:
                tapped.add(("t", sid, x1, y1))
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
        # repli humain : toucher une grille de points une fois par écran
        if ("g", sid) not in tapped:
            tapped.add(("g", sid))
            for gx in (0.25, 0.5, 0.75):
                for gy in (0.2, 0.4, 0.6, 0.8):
                    tap(int(W * gx), int(H * gy))
                    if check_crash():
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


signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))
try:
    main()
finally:
    ecrire_resultat()
