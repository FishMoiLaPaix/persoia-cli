#!/usr/bin/env bash
#
# Construit l'installateur .pkg de PersoIA CLI (outils natifs macOS :
# pkgbuild + productbuild, aucune dépendance externe).
#
# Le .pkg installe le binaire dans /usr/local/bin/persoia (déjà dans le PATH
# macOS par défaut). Non signé : Gatekeeper demandera un clic-droit > Ouvrir
# au premier lancement de l'installateur (voir README).
#
# Usage :
#   build-pkg.sh [chemin_binaire] [version]
# Défauts : dist/persoia-darwin-arm64 ; version extraite de src/persoia.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BIN="${1:-$REPO_ROOT/dist/persoia-darwin-arm64}"
VERSION="${2:-}"
OUTDIR="${OUTDIR:-$REPO_ROOT/dist}"
IDENTIFIER="com.persoia.cli"

if [ ! -f "$BIN" ]; then
    echo "ERREUR : binaire introuvable : $BIN" >&2
    exit 1
fi

if [ -z "$VERSION" ]; then
    VERSION="$(grep -E '^__version__' "$REPO_ROOT/src/persoia.py" | cut -d'"' -f2)"
fi
if [ -z "$VERSION" ]; then
    echo "ERREUR : impossible de déterminer la version" >&2
    exit 1
fi

echo "PersoIA pkg : version=$VERSION  bin=$BIN"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- Payload : /usr/local/bin/persoia ---------------------------------------
ROOT="$WORK/root"
mkdir -p "$ROOT/usr/local/bin"
cp "$BIN" "$ROOT/usr/local/bin/persoia"
chmod 0755 "$ROOT/usr/local/bin/persoia"

# --- Composant pkg -----------------------------------------------------------
COMPONENT="$WORK/persoia-component.pkg"
pkgbuild \
    --root "$ROOT" \
    --identifier "$IDENTIFIER" \
    --version "$VERSION" \
    --install-location "/" \
    "$COMPONENT"

# --- Installateur final (titre + écran d'accueil) ---------------------------
mkdir -p "$OUTDIR"
PKG_OUT="$OUTDIR/persoia-$VERSION-arm64.pkg"

# distribution.xml référence "persoia-component.pkg" → --package-path pointe le
# dossier qui le contient.
productbuild \
    --distribution "$SCRIPT_DIR/distribution.xml" \
    --resources "$SCRIPT_DIR/resources" \
    --package-path "$WORK" \
    "$PKG_OUT"

echo "pkg généré : $PKG_OUT"
