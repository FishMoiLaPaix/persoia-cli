# packaging/ — installateurs PersoIA CLI

Génère les installateurs natifs à partir des binaires déjà buildés par
PyInstaller (`dist/persoia-<plateforme>`). Chaque format est produit sur son OS
cible par le stage Jenkins correspondant ; les scripts sont aussi lançables en
local pour validation.

La version est partout dérivée de la source de vérité `__version__`
(`src/persoia.py`).

| Plateforme | Format            | Outil               | Dossier      | Install dans                         |
|------------|-------------------|---------------------|--------------|--------------------------------------|
| Windows    | `.msi`            | WiX v3.14 portable  | `windows/`   | `%LOCALAPPDATA%\PersoIA` + PATH user (per-user, sans UAC) |
| macOS      | `.pkg`            | pkgbuild/productbuild (natif) | `macos/` | `/usr/local/bin/persoia`         |
| Linux      | `.deb` + `.rpm`   | nfpm                | `linux/`     | `/usr/bin/persoia`                   |
| macOS+Linux| Homebrew formula  | tap `homebrew-tap`  | `homebrew/`  | via `brew`                           |

> Réf. **ia-perso#392** (installeur Windows avec wizard + clé API). Choix
> d'install **per-utilisateur** (PATH user, pas de droits admin) conforme à la
> consigne « PATH user > machine » de l'issue, pour des utilisateurs
> non-développeurs. Un seul `persoia` canonique sur le PATH → règle le bug de
> versions multiples (#818).

> **Non signés.** Aucun certificat de signature pour l'instant → SmartScreen
> (Windows) / Gatekeeper (macOS) avertissent. Contournements documentés dans le
> README racine. La signature pourra être ajoutée plus tard sans changer la
> structure des installateurs.

## Windows (`.msi`)

```powershell
# Depuis la racine du repo, avec un persoia.exe dans dist\
packaging\windows\build-msi.ps1 -ExePath dist\persoia-windows-x64.exe -Version 0.6.0
# → dist\persoia-0.6.0-x64.msi
```

`build-msi.ps1` télécharge les binaires WiX v3.14 dans `.wix/` si absents (aucun
droit admin). L'MSI :
- s'installe **per-utilisateur** dans `%LOCALAPPDATA%\PersoIA` (pas d'UAC) ;
- présente un **assistant standard** (`WixUI_InstallDir`) permettant de
  **choisir le dossier** d'installation ;
- ajoute le dossier au **PATH utilisateur** ;
- propose une **case finale** (cochée par défaut) qui lance `persoia login` dans
  un terminal pour guider la création / saisie de la **clé API** ;
- exige un **Windows 64 bits** (x64 natif ou ARM64 en émulation x64) ;
- gère MAJ in-place (`MajorUpgrade`, UpgradeCode fixe) et désinstallation propre
  (binaire + entrée PATH retirés).

Le paramètre `-Arch` (défaut `x64`) prépare le nom de fichier
`persoia-<ver>-<arch>.msi` ; seul le binaire x64 est buildé aujourd'hui.

### Alternative sans MSI : scripts

`install.ps1` (PowerShell) et `install.cmd` (CMD) téléchargent le dernier
binaire dans `%LOCALAPPDATA%\PersoIA` et configurent le PATH utilisateur, sans
droits admin — utiles en environnement verrouillé. Lancement direct PowerShell :

```powershell
irm https://raw.githubusercontent.com/FishMoiLaPaix/persoia-cli/main/packaging/windows/install.ps1 | iex
```

## macOS (`.pkg`)

```bash
packaging/macos/build-pkg.sh dist/persoia-darwin-arm64 0.6.0
# → dist/persoia-0.6.0-arm64.pkg
```

Outils natifs macOS uniquement. Installe dans `/usr/local/bin` (déjà sur le PATH ;
l'installateur GUI demande le mot de passe admin).

## Linux (`.deb` + `.rpm`)

```bash
VERSION=0.6.0 nfpm package --config packaging/linux/nfpm.yaml --packager deb --target dist/
VERSION=0.6.0 nfpm package --config packaging/linux/nfpm.yaml --packager rpm --target dist/
```

Nécessite [`nfpm`](https://nfpm.goreleaser.com). Installe dans `/usr/bin/persoia`.
Sorties : `persoia_<ver>-1_amd64.deb` et `persoia-<ver>-1.x86_64.rpm`.

## Homebrew (`homebrew/`)

Le tap vit dans un **repo séparé** `FishMoiLaPaix/homebrew-tap`
(`Formula/persoia.rb`) → `brew install fishmoilapaix/tap/persoia`.

- `persoia.rb.tmpl` : template (binaire pré-buildé, `on_macos`/`on_linux`).
- `render-formula.sh` : rend le template depuis `SHA256SUMS` et pousse dans le tap.

Création unique du tap (hors CI) :

```bash
gh repo create FishMoiLaPaix/homebrew-tap --public
```

Tant que le tap n'existe pas, `render-formula.sh` se contente d'un skip propre
(la release n'échoue pas).

## Mise à jour et gestionnaires de paquets

`persoia update` réécrit le binaire **en place** (`sys.executable`). Pour une
install posée par un gestionnaire (MSI/pkg/brew/deb/rpm), préférez la mise à
jour par le gestionnaire (`brew upgrade`, `apt`/`dnf`, ré-installation du `.msi`/
`.pkg`) afin de garder la base de paquets cohérente. `persoia update` reste un
fallback fonctionnel.
