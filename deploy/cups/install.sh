#!/bin/sh
# Install the MiniX CUPS backend + PPD and create the "minix" queue. See docs/CUPS.md.
#   deploy/cups/install.sh [--server URL] [--name minix] [--python /path/to/python3] [--uninstall]
# URL is the print server, default http://localhost:8090. Needs sudo.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SERVER=http://localhost:8090
NAME=minix
PYTHON=
UNINSTALL=0
while [ $# -gt 0 ]; do
  case $1 in
    --server) SERVER=$2; shift 2;;
    --name) NAME=$2; shift 2;;
    --python) PYTHON=$2; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    -h|--help) sed -n '2,3p' "$0"; exit 0;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done

case $(uname -s) in
  Darwin) BACKEND_DIR=/usr/libexec/cups/backend; PPD_DIR=/Library/Printers/PPDs/Contents/Resources;;
  *)      BACKEND_DIR=/usr/lib/cups/backend;     PPD_DIR=/usr/share/cups/model;;
esac
LIB_DIR=/usr/local/lib/minixprint-cups

# scheme://host[:port][/root] from http(s)://host[:port][/root]
case $SERVER in
  https://*) SCHEME=minixprints; REST=${SERVER#https://};;
  http://*)  SCHEME=minixprint;  REST=${SERVER#http://};;
  *) echo "--server must start with http:// or https://" >&2; exit 2;;
esac
URI="$SCHEME://${REST%/}"

# A python that has Pillow (the rasteriser needs it).
if [ -z "$PYTHON" ]; then
  for c in "$ROOT/.venv/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import PIL' 2>/dev/null; then PYTHON=$(command -v "$c"); break; fi
  done
fi

if [ $UNINSTALL -eq 0 ] && [ -z "$PYTHON" ]; then
  echo "No python3 with Pillow found. Install it (pip install Pillow / apt install python3-pil) or pass --python." >&2
  exit 1
fi

CMDS="
mkdir -p $LIB_DIR
install -m 644 $ROOT/minixprint/raster.py $LIB_DIR/minixprint_raster.py
sed '1s|.*|#!$PYTHON|' $HERE/minixprint-backend > /tmp/minixprint-backend.\$\$ && install -m 755 -o root /tmp/minixprint-backend.\$\$ $BACKEND_DIR/minixprint
install -m 644 $HERE/minixprint.ppd $PPD_DIR/minixprint.ppd
lpadmin -p $NAME -E -v $URI -P $PPD_DIR/minixprint.ppd -D 'MiniX thermal printer' -o PageSize=Roll48x200
"
if [ $UNINSTALL -eq 1 ]; then
  CMDS="
lpadmin -x $NAME || true
rm -f $BACKEND_DIR/minixprint $PPD_DIR/minixprint.ppd
rm -rf $LIB_DIR
"
fi

run() {
  if [ "$(id -u)" -eq 0 ]; then sh -c "$CMDS"; else sudo sh -c "$CMDS"; fi
}
if ! run; then
  echo >&2
  echo "Install failed (sudo unavailable?). Run these as root yourself:" >&2
  echo "$CMDS" >&2
  exit 1
fi
if [ $UNINSTALL -eq 0 ]; then
  echo "Installed queue '$NAME' -> $URI using $PYTHON"
  echo "Try: lp -d $NAME somefile.txt"
fi
