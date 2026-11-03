#!/usr/bin/env bash
# Lancé À L'INTÉRIEUR de l'émulateur par GitHub Actions.
# Usage : run_on_emulator.sh APK NOM_APPAREIL DOSSIER_SORTIE
set -u
APK="$1"; DEVICE="$2"; OUT="$3"
mkdir -p "$OUT"
HERE="$(cd "$(dirname "$0")" && pwd)"
AAPT2="$(ls "$ANDROID_HOME"/build-tools/*/aapt2 | sort -V | tail -1)"
PKG="$("$AAPT2" dump packagename "$APK")"
echo "Appli : $PKG sur $DEVICE"
echo "{\"appareil\":\"$DEVICE\",\"paquet\":\"$PKG\"}" > "$OUT/info.json"

adb wait-for-device
adb shell input keyevent KEYCODE_WAKEUP
adb shell wm dismiss-keyguard || true

# 1. Installation
if ! adb install -r "$APK" > "$OUT/install.txt" 2>&1; then
  echo '{"mode":"installation","defauts":[{"type":"installation","detail":"Installation impossible : voir install.txt"}]}' > "$OUT/explorateur_installation.json"
  exit 0
fi

# 2. Exploration normale (portrait)
adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 0
timeout 900 python3 "$HERE/explorer.py" "$PKG" "$OUT" normal 120

# 3. Police et affichage au maximum (texte à 200 %)
adb shell settings put system font_scale 2.0
adb shell wm density $(( $(adb shell wm density | grep -o '[0-9]*$' | tail -1) * 13 / 10 )) || true
timeout 900 python3 "$HERE/explorer.py" "$PKG" "$OUT" police200 50
adb shell settings put system font_scale 1.0
adb shell wm density reset || true

# 4. Paysage
adb shell settings put system user_rotation 1
timeout 900 python3 "$HERE/explorer.py" "$PKG" "$OUT" paysage 50
adb shell settings put system user_rotation 0

# 5. Hors connexion
adb shell svc wifi disable; adb shell svc data disable
adb shell cmd connectivity airplane-mode enable || true
timeout 900 python3 "$HERE/explorer.py" "$PKG" "$OUT" horsconnexion 50
adb shell cmd connectivity airplane-mode disable || true
adb shell svc wifi enable

# 6. Gestes au hasard longtemps (Monkey) + endurance
adb logcat -c
timeout 900 adb shell monkey -p "$PKG" --throttle 120 --pct-syskeys 0 --ignore-timeouts \
  --monitor-native-crashes -s 42 -v 4000 > "$OUT/monkey.txt" 2>&1
MONKEY_CRASH=$(grep -c -E "CRASH:|ANR in" "$OUT/monkey.txt" || true)
adb shell dumpsys meminfo "$PKG" > "$OUT/memoire.txt" 2>&1
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
adb logcat -d > "$OUT/logcat.txt" 2>&1 || true
exit 0
