#!/usr/bin/env bash
#
# Rend la formula Homebrew depuis persoia.rb.tmpl et la pousse dans le tap
# FishMoiLaPaix/homebrew-tap. Conçu pour le stage Release du Jenkinsfile.
#
# Lit les empreintes dans le manifeste SHA256SUMS de la release (entrées des
# binaires VERSIONNÉS, donc URL immuable côté formula).
#
# Usage :
#   VERSION=0.6.0 render-formula.sh path/to/SHA256SUMS
#
# Pré-requis : git + gh dans le PATH, GH_TOKEN avec accès au tap.
# Si le tap n'existe pas encore, le script SKIP proprement (exit 0) pour ne
# pas faire échouer la release — créez-le une fois avec :
#   gh repo create FishMoiLaPaix/homebrew-tap --public
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/persoia.rb.tmpl"
SHASUMS="${1:?Usage: render-formula.sh path/to/SHA256SUMS}"
TAP_REPO="FishMoiLaPaix/homebrew-tap"

: "${VERSION:?VERSION doit être défini}"

sha_for() {
    # Récupère l'empreinte d'un fichier listé dans SHA256SUMS.
    local name="$1"
    local line
    line="$(grep -E "  ${name}\$" "$SHASUMS" || true)"
    if [ -z "$line" ]; then
        echo "ERREUR : '$name' absent de $SHASUMS" >&2
        exit 1
    fi
    echo "${line%% *}"
}

SHA_DARWIN="$(sha_for "persoia-${VERSION}-darwin-arm64")"
SHA_LINUX="$(sha_for "persoia-${VERSION}-linux-x64")"

# --- Tap absent → skip propre ; autres erreurs → fail bruyant ----------------
# On capture stderr (stdout jeté) pour différencier un tap réellement absent
# (404) d'un problème d'auth/jeton/réseau qu'il ne faut PAS masquer.
if ! err="$(gh repo view "$TAP_REPO" 2>&1 1>/dev/null)"; then
    case "$err" in
        *"Could not resolve"*|*"404"*|*"Not Found"*)
            echo "Tap $TAP_REPO inexistant — étape Homebrew ignorée."
            echo "Créez-le une fois : gh repo create $TAP_REPO --public"
            exit 0
            ;;
        *)
            echo "ERREUR : accès au tap $TAP_REPO impossible (auth/réseau ?) : $err" >&2
            exit 1
            ;;
    esac
fi

# --- Rendu -------------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FORMULA="$WORK/persoia.rb"
sed -e "s/__VERSION__/${VERSION}/g" \
    -e "s/__SHA_DARWIN_ARM64__/${SHA_DARWIN}/g" \
    -e "s/__SHA_LINUX_X64__/${SHA_LINUX}/g" \
    "$TEMPLATE" > "$FORMULA"

# --- Push dans le tap --------------------------------------------------------
CLONE="$WORK/tap"
gh repo clone "$TAP_REPO" "$CLONE" -- --depth 1
mkdir -p "$CLONE/Formula"
cp "$FORMULA" "$CLONE/Formula/persoia.rb"

cd "$CLONE"
git config user.name  "persoia-ci"
git config user.email "ci@persoia.com"
# On stage d'abord : `git diff` (sans --cached) ignore les fichiers non suivis,
# donc au tout premier passage (Formula/persoia.rb absent du tap) il ne verrait
# aucun changement et n'aurait jamais publié la formula. Stager puis comparer
# l'index à HEAD détecte aussi bien une création qu'une modification.
git add Formula/persoia.rb
# `git diff --cached` compare l'index à HEAD : si le tap vient d'être créé et
# n'a encore aucun commit (HEAD absent), on force la publication du 1er commit.
if git rev-parse --verify -q HEAD >/dev/null && git diff --cached --quiet -- Formula/persoia.rb; then
    echo "Formula déjà à jour pour $VERSION — rien à pousser."
    exit 0
fi
git commit -m "persoia ${VERSION}"
# `git push` n'hérite PAS de l'authentification de `gh` : le clone via `gh repo
# clone` est authentifié, mais un `git push` brut n'a aucun credential et
# échoue (« could not read Username »). On branche le credential helper de gh —
# qui lit GH_TOKEN — uniquement pour ce push, sans toucher la config git globale
# ni exposer le token sur la ligne de commande. Le helper vide en tête
# réinitialise d'éventuels helpers hérités de l'environnement.
# Push explicite avec -u : robuste si la branche n'a pas encore d'upstream.
git -c credential.helper= \
    -c credential.helper='!gh auth git-credential' \
    push -u origin HEAD

echo "Formula Homebrew mise à jour : persoia ${VERSION}"
