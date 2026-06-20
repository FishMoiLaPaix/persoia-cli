<#
.SYNOPSIS
    Installe PersoIA CLI sur Windows sans MSI (alternative PowerShell, réf. #392).

.DESCRIPTION
    Télécharge le dernier binaire `persoia` depuis les releases GitHub, le pose
    dans %LOCALAPPDATA%\PersoIA et ajoute ce dossier au PATH **utilisateur**
    (aucun droit administrateur requis). Convient aux environnements où l'on ne
    peut/veut pas lancer le MSI.

    Lancement direct (sans cloner le dépôt) :
      irm https://raw.githubusercontent.com/FishMoiLaPaix/persoia-cli/main/packaging/windows/install.ps1 | iex

.PARAMETER Login
    Lance `persoia login` à la fin pour configurer la clé API immédiatement.
#>
[CmdletBinding()]
param(
    [switch]$Login
)

$ErrorActionPreference = 'Stop'

# --- Architecture ------------------------------------------------------------
# Le binaire publié est x64. Il tourne nativement sur AMD64 et en émulation sur
# Windows ARM64. Le 32 bits (x86) n'est pas supporté.
$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
if ($arch -notin @('AMD64', 'ARM64')) {
    throw "Architecture non supportée : $arch. PersoIA CLI nécessite un Windows 64 bits (x64 ou ARM64)."
}

$installDir = Join-Path $env:LOCALAPPDATA 'PersoIA'
$target     = Join-Path $installDir 'persoia.exe'
$url        = 'https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-windows-x64.exe'

Write-Host "Installation de PersoIA CLI dans $installDir ($arch)..."
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $target

# --- Vérification d'intégrité (sidecar .sha256 publié avec la release) -------
# Empêche l'exécution d'un binaire altéré (réseau/artefact compromis).
# On télécharge le sidecar dans un fichier puis on le lit : sous Windows
# PowerShell 5.1, (Invoke-WebRequest ...).Content d'un .sha256 renvoie un
# Byte[] (pas une chaîne), ce qui casserait un .Trim() direct.
$expected = $null
$shaTmp = Join-Path $env:TEMP 'persoia.exe.sha256'
try {
    Invoke-WebRequest -Uri "$url.sha256" -OutFile $shaTmp
    # Le sidecar ne contient que l'empreinte (cf. pipeline de release).
    $expected = (Get-Content -Raw $shaTmp).Trim()
    Remove-Item $shaTmp -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Empreinte SHA-256 indisponible pour cette release : intégrité non vérifiée."
}
if ($expected) {
    $actual = (Get-FileHash -Algorithm SHA256 -Path $target).Hash
    if ($actual -ne $expected) {   # -ne est insensible à la casse
        Remove-Item $target -Force
        throw "Empreinte du binaire invalide : attendue $expected, obtenue $actual. Installation annulée."
    }
    Write-Host "Intégrité vérifiée (SHA-256)."
}

# --- PATH utilisateur (scope User, pas le PATH fusionné) --------------------
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if (($userPath -split ';') -notcontains $installDir) {
    $newPath = if ([string]::IsNullOrEmpty($userPath)) { $installDir } else { "$userPath;$installDir" }
    [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
    Write-Host "PATH utilisateur mis à jour."
} else {
    Write-Host "PATH déjà configuré."
}

Write-Host ""
Write-Host "PersoIA CLI installé." -ForegroundColor Green
Write-Host "Ouvrez un NOUVEAU terminal (le PATH n'est pas hérité par la session courante)."

if ($Login) {
    & $target login
} else {
    Write-Host "Puis lancez : persoia login   (connexion et clé API)"
}
