#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_HOME=${HUION_INSTALL_HOME:-${INK2VAULT_INSTALL_HOME:-"$HOME/Library/Application Support/Huion"}}
BIN_DIR=${HUION_BIN_DIR:-${INK2VAULT_BIN_DIR:-"$HOME/.local/bin"}}
RUNTIME="$INSTALL_HOME/runtime"
STAGE="$INSTALL_HOME/.runtime-new-$$"
OLD="$INSTALL_HOME/.runtime-old-$$"

case "$INSTALL_HOME" in
  ""|/|"$HOME")
    echo "Neplatná instalační složka: $INSTALL_HOME" >&2
    exit 1
    ;;
esac

cleanup() {
  rm -rf "$STAGE" "$OLD"
}
trap cleanup EXIT INT TERM

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Huion je určený pro macOS." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("Huion vyžaduje Python 3.9 nebo novější.")
PY

mkdir -p "$INSTALL_HOME" "$BIN_DIR" "$STAGE"

LEGACY_HOME="$HOME/Library/Application Support/Ink2Vault"
if [ "$INSTALL_HOME" = "$HOME/Library/Application Support/Huion" ] && [ -d "$LEGACY_HOME" ]; then
  for name in config.json state.sqlite3 state.sqlite3-shm state.sqlite3-wal; do
    if [ -e "$LEGACY_HOME/$name" ] && [ ! -e "$INSTALL_HOME/$name" ]; then
      mv "$LEGACY_HOME/$name" "$INSTALL_HOME/$name"
    fi
  done
  if [ -e "$LEGACY_HOME/ink2vault.log" ] && [ ! -e "$INSTALL_HOME/huion.log" ]; then
    mv "$LEGACY_HOME/ink2vault.log" "$INSTALL_HOME/huion.log"
  fi
fi

cp -R "$SOURCE_DIR/ink2vault" "$STAGE/ink2vault"

if [ -d "$RUNTIME" ]; then
  mv "$RUNTIME" "$OLD"
fi
mv "$STAGE" "$RUNTIME"
rm -rf "$OLD"

cat > "$BIN_DIR/huion" <<'EOF'
#!/bin/sh
set -eu
INSTALL_HOME=${HUION_INSTALL_HOME:-${INK2VAULT_INSTALL_HOME:-"$HOME/Library/Application Support/Huion"}}
export PYTHONPATH="$INSTALL_HOME/runtime${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m ink2vault.cli "$@"
EOF
chmod 755 "$BIN_DIR/huion"

echo "Huion nainstalován do: $RUNTIME"
echo "Příkaz: $BIN_DIR/huion"
echo
echo "Další krok: $BIN_DIR/huion"
