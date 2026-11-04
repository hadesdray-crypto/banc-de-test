#!/usr/bin/env bash
# Lancé À L'INTÉRIEUR de l'émulateur par GitHub Actions.
# Usage : run_on_emulator.sh APK NOM_APPAREIL DOSSIER_SORTIE
set -u
APK="$1"; DEVICE="$2"; OUT="$3"
mkdir -p "$OUT"
HERE="$(cd "$(dirname "$0")" && pwd)"
AAPT2="$(ls "$ANDROID_HOME"/build-tools/*/aapt2 | sort -V | tail -1)"
PKG="$("$AAPT2" dump packagename "$APK")"
echo "Test sur $DEVICE (nom de l'appli masqué)"
echo "{\"appareil\":\"$DEVICE\"}" > "$OUT/info.json"

# Toute commande adb ordinaire a une limite de temps : aucun blocage possible.
A() { timeout 40 adb "$@"; }
PHASE=900   # secondes maximum par phase (le robot attend lui-même les redémarrages)
W() { timeout 300 adb wait-for-device; sleep 3; }

A wait-for-device
A shell input keyevent KEYCODE_WAKEUP
A shell wm dismiss-keyguard || true
# Animations coupées : tests plus rapides et plus stables
A shell settings put global window_animation_scale 0 || true
A shell settings put global transition_animation_scale 0 || true
A shell settings put global animator_duration_scale 0 || true

# 1. Installation
if ! A install -r "$APK" > "$OUT/install.txt" 2>&1; then
  echo '{"mode":"installation","defauts":[{"type":"installation","detail":"Installation impossible sur cet appareil."}]}' > "$OUT/explorateur_installation.json"
  exit 0
fi

# 2. Exploration normale (portrait)
A shell settings put system accelerometer_rotation 0
A shell settings put system user_rotation 0
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" normal 120

# 3. Police et affichage au maximum (texte à 200 %)
A shell settings put system font_scale 2.0
DENS="$(A shell wm density | grep -o '[0-9]*$' | tail -1)"
[ -n "$DENS" ] && A shell wm density $(( DENS * 13 / 10 )) || true
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" police200 50
A shell settings put system font_scale 1.0
A shell wm density reset || true

# 4. Paysage
A shell settings put system user_rotation 1
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" paysage 50
A shell settings put system user_rotation 0

# 5. Hors connexion (méthodes en cascade : chacune limitée à 40 s, on passe à la suivante)
A shell svc wifi disable || true
A shell svc data disable || true
A shell cmd connectivity airplane-mode enable || A shell settings put global airplane_mode_on 1 || true
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" horsconnexion 50
A shell cmd connectivity airplane-mode disable || A shell settings put global airplane_mode_on 0 || true
A shell svc wifi enable || true
A shell svc data enable || true

# 5b. Mode sombre
A shell cmd uimode night yes || true
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" sombre 40
A shell cmd uimode night no || true

# 5c. Très petit écran (vieux petit téléphone)
A shell wm size 480x800 || true
W; timeout $PHASE python3 "$HERE/explorer.py" "$PKG" "$OUT" petit_ecran 40
A shell wm size reset || true

# 5d. Scénarios de la vie réelle (accueil/reprise, fermeture, retour, rotation, mémoire, mise à jour sur place, stockage plein, réseau)
W; timeout $PHASE python3 "$HERE/scenarios.py" "$PKG" "$OUT" "$APK" || true

# 6. Gestes au hasard longtemps (Monkey) + endurance
A logcat -c || true
timeout 600 adb shell monkey -p "$PKG" --throttle 120 --pct-syskeys 0 --ignore-timeouts \
  --monitor-native-crashes -s 42 -v 3000 > "$OUT/monkey.txt" 2>&1
MONKEY_CRASH=$(grep -c -E "CRASH:|ANR in" "$OUT/monkey.txt" || true)
A shell dumpsys meminfo "$PKG" > "$OUT/memoire.txt" 2>&1
python3 - "$OUT" "$MONKEY_CRASH" <<'PY'
import json, sys, re
out, crashes = sys.argv[1], int(sys.argv[2])
mem = open(out + "/memoire.txt", errors="replace").read()
m = re.search(r"TOTAL PSS:\s+(\d+)", mem) or re.search(r"TOTAL\s+(\d+)", mem)
pss = int(m.group(1)) // 1024 if m else None
defs = []
if crashes:
    defs.append({"type": "plantage", "detail": "Gestes au hasard : %d plantage(s)/blocage(s)." % crashes, "mode": "hasard"})
if pss and pss > 700:
    defs.append({"type": "memoire", "detail": "Mémoire élevée après endurance : %d Mo." % pss, "mode": "endurance"})
json.dump({"mode": "hasard_endurance", "defauts": defs, "memoire_mo": pss},
          open(out + "/explorateur_hasard.json", "w"), ensure_ascii=False, indent=1)
PY
A logcat -d > "$OUT/logcat.txt" 2>&1 || true
# Aucun nom d'appli dans les fichiers de sortie
sed -i "s/$PKG/<appli>/g" "$OUT"/*.txt 2>/dev/null || true
exit 0
