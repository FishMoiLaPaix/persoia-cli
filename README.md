# persoia-cli

Wrapper CLI souverain pour [PersoIA](https://www.persoia.com) — utilisez votre instance GPU privée depuis le terminal, en mode chat ou code (intégration aider).

## Installation

### macOS (Apple Silicon)

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-darwin-arm64 \
  -o ~/.local/bin/persoia && chmod +x ~/.local/bin/persoia
```

> Si `~/.local/bin` n'est pas dans votre `PATH` (cas par défaut sur macOS), ajoutez-le une fois pour toutes :
> `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec $SHELL`

> Premier lancement : macOS Gatekeeper bloque les binaires non signés. Lever la quarantaine :
> `xattr -d com.apple.quarantine ~/.local/bin/persoia`

### Linux (x64)

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-linux-x64 \
  -o ~/.local/bin/persoia && chmod +x ~/.local/bin/persoia
```

> Si `~/.local/bin` n'est pas dans votre `PATH` :
> `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && exec $SHELL`
>
> Alternative système-wide : déposer le binaire dans `/usr/local/bin/persoia` (sudo requis).

### Windows (x64)

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

> **Redémarrez votre terminal** après l'install : la session PowerShell courante n'hérite pas du nouveau PATH utilisateur.

> Premier lancement : Windows SmartScreen avertit pour les binaires non signés. Cliquer "Plus d'infos" puis "Exécuter quand même".

## Configuration

```bash
mkdir -p ~/.config/persoia
echo "PERSOIA_API_KEY=persoia_sk_xxxxx" > ~/.config/persoia/config.env
chmod 600 ~/.config/persoia/config.env
```

Ou interactivement : `persoia login`

Le préfixe de la clé route automatiquement :
- `persoia_demo_sk_*` → `https://demo.chat.persoia.com/v1`
- `persoia_sk_*` → `https://chat.persoia.com/v1`

## Usage

```bash
persoia version              # Afficher la version
persoia login                # Authentification interactive
persoia config               # Afficher la configuration courante
persoia init                 # Créer un PERSOIA.md dans le projet
persoia chat "question"      # Chat one-shot
persoia code [aider args]    # Lance aider connecté à votre instance
persoia logout               # Effacer la clé locale
```

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

Une release GitHub est publiée automatiquement à chaque tag `v*.*.*`.

## License

MIT — voir [LICENSE](LICENSE).
