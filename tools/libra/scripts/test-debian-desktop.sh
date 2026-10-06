#!/bin/bash
# Run as the desktop user inside the mounted image, on a private Xvfb display.
set -euo pipefail
export DISPLAY=:98
export XDG_RUNTIME_DIR
XDG_RUNTIME_DIR=$(mktemp -d /tmp/libra-desktop-runtime.XXXXXX)
export LANG=zh_CN.UTF-8
source "$HOME/.xsessionrc"
dbus-update-activation-environment --all
mkdir -p "$HOME/.cache"
Xvfb "$DISPLAY" -screen 0 1080x1920x24 -nolisten tcp -ac > /tmp/libra-xvfb.log 2>&1 &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null || true; rm -rf "$XDG_RUNTIME_DIR"' EXIT
for n in {1..30}; do
 if timeout 5 xdpyinfo >/dev/null 2>&1; then break; fi
 sleep 1
done
glxinfo -B > /tmp/libra-glxinfo.txt
grep -q 'OpenGL renderer string: llvmpipe' /tmp/libra-glxinfo.txt
xfce4-session > /tmp/libra-xfce-session.log 2>&1 &
session_pid=$!
ready=0
for n in {1..60}; do
 if [ -e "$HOME/.config/libra/desktop-initialized" ] && \
    pgrep -x onboard >/dev/null && pgrep -x xfce4-panel >/dev/null && \
    dbus-send --session --print-reply --dest=org.freedesktop.DBus \
     /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner \
     string:org.onboard.Onboard | grep -q 'boolean true'; then
  ready=1
  break
 fi
 sleep 1
done
[ "$ready" = 1 ] || { cat /tmp/libra-xfce-session.log; exit 1; }
test "$(xfconf-query -c xfwm4 -p /general/use_compositing)" = false
test "$(xfconf-query -c xsettings -p /Gdk/WindowScalingFactor)" = 2
test "$(xfconf-query -c thunar -p /misc-single-click)" = true
/usr/local/bin/libra-keyboard
sleep 2
dbus-send --session --print-reply --dest=org.onboard.Onboard \
 /org/onboard/Onboard/Keyboard org.freedesktop.DBus.Properties.Get \
 string:org.onboard.Onboard.Keyboard string:Visible > /tmp/libra-keyboard-state.txt
grep -q 'boolean true' /tmp/libra-keyboard-state.txt
/usr/local/bin/libra-keyboard
xfce4-terminal --disable-server --title='LIBRA MAXIMIZE TEST' -e 'sleep 20' &
window_pid=$!
sleep 4
window=$(wmctrl -l | awk '/LIBRA MAXIMIZE TEST/{print $1}')
test -n "$window"
xprop -id "$window" _NET_WM_STATE > /tmp/libra-window-state.txt
grep -q '_NET_WM_STATE_MAXIMIZED_VERT' /tmp/libra-window-state.txt
grep -q '_NET_WM_STATE_MAXIMIZED_HORZ' /tmp/libra-window-state.txt
kill "$window_pid" 2>/dev/null || true
xwd -root -silent -out /tmp/libra-desktop.xwd
printf 'PASS ARM64 Xfce at 1080x1920: llvmpipe, scaling, panel, keyboard toggle, window maximization\n'
kill "$session_pid" 2>/dev/null || true
