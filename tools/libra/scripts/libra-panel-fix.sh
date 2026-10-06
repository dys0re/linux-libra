#!/bin/sh
# Repair the overlapping default dock in the already installed Debian desktop.
set -eu
if [ "$(id -u)" -eq 0 ]; then
 exec runuser -u libra -- /bin/sh "$0"
fi
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"
export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
xfconf-query -c xfce4-panel -p /panels -a -t int -s 1
xfce4-panel --restart
printf 'The desktop now uses one panel.\n'
