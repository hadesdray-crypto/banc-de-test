#!/usr/bin/env bash
# Expérience : l'émulateur survit-il à une page web simple, puis à l'appli ?
# Usage : sante.sh APK
APK="$1"
A() { timeout 30 adb "$@"; }
AAPT2="$(ls "$ANDROID_HOME"/build-tools/*/aapt2 | sort -V | tail -1)"
PKG="$("$AAPT2" dump packagename "$APK")"
A wait-for-device
echo "SANTE debut etat=$(A get-state 2>&1 | head -1) android=$(A shell getprop ro.build.version.release | tr -d '\r')"
A shell settings put global window_animation_scale 0 >/dev/null 2>&1
echo "SANTE navigateur: ouverture d'une page simple"
A shell am start -a android.intent.action.VIEW -d "data:text/html,<h1>essai</h1>" >/dev/null 2>&1
for i in 1 2 3 4 5 6; do
  sleep 10
  echo "SANTE navigateur t=$((i*10))s etat=$(A get-state 2>&1 | head -1) boot=$(A shell getprop sys.boot_completed 2>&1 | head -1 | tr -d '\r')"
done
A shell input keyevent KEYCODE_HOME >/dev/null 2>&1
echo "SANTE appli: installation"
A install -r "$APK" 2>&1 | tail -1
A shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8; do
  sleep 10
  echo "SANTE appli t=$((i*10))s etat=$(A get-state 2>&1 | head -1) pid=$(A shell pidof "$PKG" 2>&1 | head -1 | tr -d '\r')"
done
echo "SANTE fin"
exit 0
