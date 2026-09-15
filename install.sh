#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_HOME=${INK2VAULT_INSTALL_HOME:-"$HOME/Library/Application Support/Ink2Vault"}
BIN_DIR=${INK2VAULT_BIN_DIR:-"$HOME/.local/bin"}
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
  echo "Ink2Vault je určený pro macOS." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("Ink2Vault vyžaduje Python 3.9 nebo novější.")
PY

mkdir -p "$INSTALL_HOME" "$BIN_DIR" "$STAGE"
cp -R "$SOURCE_DIR/ink2vault" "$STAGE/ink2vault"

if [ -d "$RUNTIME" ]; then
  mv "$RUNTIME" "$OLD"
fi
mv "$STAGE" "$RUNTIME"
rm -rf "$OLD"

cat > "$BIN_DIR/ink2vault" <<'EOF'
#!/bin/sh
set -eu
INSTALL_HOME=${INK2VAULT_INSTALL_HOME:-"$HOME/Library/Application Support/Ink2Vault"}
export PYTHONPATH="$INSTALL_HOME/runtime${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m ink2vault.cli "$@"
EOF
chmod 755 "$BIN_DIR/ink2vault"

echo "Ink2Vault nainstalován do: $RUNTIME"
echo "Příkaz: $BIN_DIR/ink2vault"
echo
echo "Další krok: $BIN_DIR/ink2vault configure"
