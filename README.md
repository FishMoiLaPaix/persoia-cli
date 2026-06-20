# persoia-cli

Wrapper CLI souverain pour [PersoIA](https://www.persoia.com) — utilisez votre instance GPU privée depuis le terminal, en mode chat ou code (intégration aider).

## Installation

La méthode recommandée est l'installateur natif de votre système. Les binaires
bruts restent disponibles pour les installations manuelles / automatisées
([plus bas](#installation-manuelle-avancée)).

> Les installateurs ne sont **pas encore signés** : Windows SmartScreen et macOS
> Gatekeeper afficheront un avertissement au premier lancement (voir les notes
> par OS ci-dessous).

### Windows (x64) — `.msi`

Téléchargez et double-cliquez
[**persoia-x64.msi**](https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-x64.msi)
(dernière release). L'assistant s'installe **par utilisateur** (pas d'élévation
administrateur), vous laisse **choisir le dossier** d'installation, ajoute
`persoia` au `PATH`, et propose en fin d'installation de lancer la **connexion**
pour configurer votre **clé API**.

> **Redémarrez votre terminal** après l'install (le nouveau `PATH` n'est pas
> hérité par la session courante).
>
> SmartScreen affiche « Windows a protégé votre ordinateur » → cliquez
> **Informations complémentaires** puis **Exécuter quand même**.

Sans MSI (environnement verrouillé), une alternative en une ligne (le script
vérifie l'empreinte SHA-256 du binaire téléchargé) :

```powershell
irm https://raw.githubusercontent.com/FishMoiLaPaix/persoia-cli/main/packaging/windows/install.ps1 | iex
```

(équivalent CMD : `packaging/windows/install.cmd`)

### macOS (Apple Silicon)

**Homebrew** (recommandé) :

```bash
brew install fishmoilapaix/tap/persoia
```

**Installateur `.pkg`** : téléchargez
[**persoia-arm64.pkg**](https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-arm64.pkg)
et ouvrez-le (installe dans `/usr/local/bin`, déjà sur le `PATH`).

> `.pkg` non signé : si Gatekeeper bloque, **clic-droit sur le `.pkg` →
> Ouvrir**, puis confirmez. (Homebrew ne déclenche pas cet avertissement.)

### Linux (x64)

**Homebrew** (recommandé) :

```bash
brew install fishmoilapaix/tap/persoia
```

**Debian / Ubuntu** (`.deb`) :

```bash
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-amd64.deb -o persoia.deb
sudo apt install ./persoia.deb
```

**Fedora / RHEL** (`.rpm`) :

```bash
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-x86_64.rpm -o persoia.rpm
sudo dnf install ./persoia.rpm
```

Les paquets installent `persoia` dans `/usr/bin`.

### Installation manuelle (avancée)

Binaire brut, sans installateur — utile pour les environnements verrouillés ou
les scripts d'automatisation.

<details>
<summary>macOS (Apple Silicon)</summary>

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-darwin-arm64 \
  -o ~/.local/bin/persoia && chmod +x ~/.local/bin/persoia
```

> Si `~/.local/bin` n'est pas dans votre `PATH` :
> `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec $SHELL`
>
> Lever la quarantaine Gatekeeper : `xattr -d com.apple.quarantine ~/.local/bin/persoia`
</details>

<details>
<summary>Linux (x64)</summary>

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-linux-x64 \
  -o ~/.local/bin/persoia && chmod +x ~/.local/bin/persoia
```

> Si `~/.local/bin` n'est pas dans votre `PATH` :
> `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && exec $SHELL`
</details>

<details>
<summary>Windows (x64)</summary>

```powershell
New-Item -ItemType Directory -Force -Path "$env:LOCALAPPDATA\persoia"
Invoke-WebRequest `
  -Uri "https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-windows-x64.exe" `
  -OutFile "$env:LOCALAPPDATA\persoia\persoia.exe"

# Append to the User PATH (read User scope, not the merged $env:PATH which mixes System+User)
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$cliDir   = "$env:LOCALAPPDATA\persoia"
if ($userPath -notlike "*$cliDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$cliDir", "User")
}
```

> **Redémarrez votre terminal** après l'install.
</details>

## Configuration

```bash
mkdir -p ~/.config/persoia
echo "PERSOIA_API_KEY=persoia_sk_xxxxx" > ~/.config/persoia/config.env
chmod 600 ~/.config/persoia/config.env
```

Ou via `persoia login` : ouvre `chat.persoia.com` dans le navigateur, vous vous
connectez sur le site (qui vérifie vos droits et votre tenant), et le token CLI
dédié est récupéré automatiquement puis écrit dans la config. La récupération
passe par un rappel local que le CLI écoute sur `http://127.0.0.1:<port>` —
l'adresse IPv4 explicite est utilisée volontairement (et non `localhost`, qui
peut résoudre vers la boucle IPv6 `::1` et empêcher le navigateur de joindre le
serveur local). En environnement sans navigateur (headless/SSH), utilisez
`persoia login --no-browser` (email / mot de passe).

Le préfixe de la clé route automatiquement :
- `persoia_demo_sk_*` → `https://demo.chat.persoia.com/v1`
- `persoia_sk_*` → `https://chat.persoia.com/v1`

## Usage

```bash
persoia version              # Afficher la version
persoia login                # Connexion via le navigateur (token CLI auto)
persoia login --no-browser   # Connexion email / mot de passe (headless/SSH)
persoia config               # Afficher la configuration courante
persoia init                 # Créer un PERSOIA.md dans le projet
persoia chat "question"      # Chat one-shot
persoia code [aider args]    # Lance aider connecté à votre instance
persoia update               # Met à jour le binaire (releases GitHub)
persoia logout               # Effacer la clé locale
```

### Mise à jour

```bash
persoia update            # Vérifie et installe la dernière version
persoia update --check    # Vérifie seulement, sans installer
persoia update --pre      # Inclut les pré-versions (rc/beta)
persoia update -y         # Installe sans confirmation
```

`persoia update` compare la version locale aux releases GitHub, télécharge le
binaire correspondant à la plateforme et remplace l'exécutable en place. Si
`persoia` tourne depuis les sources (non packagé), la commande indique d'utiliser
`git pull`.

> Installé via un gestionnaire de paquets (Homebrew, `.deb`/`.rpm`, `.msi`/`.pkg`) ?
> Préférez la mise à jour par le gestionnaire (`brew upgrade persoia`, `apt`/`dnf`,
> ré-installation du `.msi`/`.pkg`) pour garder sa base cohérente. `persoia update`
> reste un fallback fonctionnel (il réécrit le binaire en place).

## Développement

```bash
git clone https://github.com/FishMoiLaPaix/persoia-cli.git
cd persoia-cli

# Lancer le source directement (Python 3.10+)
python3 src/persoia.py version

# Builder le binaire localement
pip install -r requirements-build.txt
pyinstaller persoia.spec
./dist/persoia version
```

Le source est intentionnellement un script Python standalone (zéro dépendance runtime hors stdlib) pour minimiser la surface d'attaque et la taille du binaire.

## CI/CD

Build matrix Jenkins (`Jenkinsfile`) sur 3 plateformes :
- `linux-x64` — cloud-template agent (label `python311`, Ubuntu 22.04 + Python 3.11 ; le build pull en plus une distrib portable Python 3.11 d'`python-build-standalone` pour avoir `libpython3.11.so` dont PyInstaller a besoin)
- `mac-arm64` — agent macOS dédié (label `mac-arm64`, à provisionner ; les PR builds tolèrent l'absence de l'agent — le tag-build hard-fail au stage Release sur l'unstash manquant)
- `windows-x64` — agent permanent `windows-docker-agent` (label `windows-amd64` ; le build pull une distrib portable CPython 3.11 dans le workspace car l'agent n'a que Python 2.7 dans le PATH)

Une release GitHub est publiée automatiquement à chaque tag `v*.*.*`. Chaque
binaire est publié sous deux noms : versionné (`persoia-<version>-<plateforme>`,
pour épingler une version précise) et sans version (`persoia-<plateforme>`, alias
« latest » utilisé par les commandes d'installation et par `persoia update`). Un
manifeste `SHA256SUMS` accompagne chaque release pour la vérification d'intégrité.

Chaque plateforme produit aussi son **installateur** (`.msi` Windows, `.pkg`
macOS, `.deb`/`.rpm` Linux), publié sur la release sous les deux schémas de noms.
Au tag, la formula **Homebrew** du tap `FishMoiLaPaix/homebrew-tap` est mise à
jour automatiquement. Les sources de packaging et leur documentation sont dans
[`packaging/`](packaging/).

## License

MIT — voir [LICENSE](LICENSE).
