<#
.SYNOPSIS
    Construit l'installateur MSI de PersoIA CLI avec WiX v3 (portable).

.DESCRIPTION
    Empaquette un persoia.exe déjà buildé dans un MSI per-utilisateur
    (install sous %LOCALAPPDATA%\PersoIA + ajout au PATH utilisateur, assistant
    standard avec choix du dossier, sans élévation UAC). Télécharge les binaires
    WiX v3.14 dans le workspace s'ils ne sont pas déjà présents — aucun droit
    admin requis.

    Utilisable en local (validation) et depuis le stage Windows du Jenkinsfile.

.PARAMETER ExePath
    Chemin du persoia.exe à empaqueter. Défaut : <repo>\dist\persoia-windows-x64.exe

.PARAMETER Version
    Version du produit. Défaut : extraite de src/persoia.py (__version__).
    Tout suffixe de pré-version (-rc1, -beta...) est retiré car un
    ProductVersion MSI doit être purement numérique (x.y.z).

.PARAMETER Arch
    Architecture cible (x64 par défaut). Sert au suffixe du nom de fichier et à
    candle -arch. Seul x64 est buildé aujourd'hui (couvre x64 + ARM64 émulé).

.PARAMETER OutDir
    Dossier de sortie du MSI. Défaut : <repo>\dist

.EXAMPLE
    ./build-msi.ps1 -ExePath C:\tmp\persoia.exe -Version 0.6.0
#>
[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$Version,
    [ValidateSet('x64','x86')]
    [string]$Arch = 'x64',
    [string]$OutDir
)

$ErrorActionPreference = 'Stop'

# --- Chemins -----------------------------------------------------------------
$ScriptDir = $PSScriptRoot
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path

if (-not $ExePath) { $ExePath = Join-Path $RepoRoot 'dist\persoia-windows-x64.exe' }
if (-not $OutDir)  { $OutDir  = Join-Path $RepoRoot 'dist' }

$IconPath   = Join-Path $RepoRoot 'persoia.ico'
$LicenseRtf = Join-Path $ScriptDir 'License.rtf'
$WxsPath    = Join-Path $ScriptDir 'persoia.wxs'

if (-not (Test-Path $ExePath))   { throw "persoia.exe introuvable : $ExePath" }
if (-not (Test-Path $IconPath))  { throw "persoia.ico introuvable : $IconPath" }

# --- Version ----------------------------------------------------------------
if (-not $Version) {
    $verLine = Select-String -Path (Join-Path $RepoRoot 'src\persoia.py') `
                             -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $verLine) { throw "Impossible d'extraire __version__ de src/persoia.py" }
    $Version = $verLine.Matches[0].Groups[1].Value
}
# ProductVersion MSI = numérique pur : on retire un éventuel suffixe -rcN/-beta.
$NumericVersion = ($Version -split '-')[0]
if ($NumericVersion -notmatch '^\d+\.\d+(\.\d+)?$') {
    throw "Version non numérique pour un MSI : '$NumericVersion' (depuis '$Version')"
}

Write-Host "PersoIA MSI : version=$NumericVersion  exe=$ExePath"

# --- WiX v3.14 portable ------------------------------------------------------
$WixVersion = '3.14'
$WixDir     = Join-Path $RepoRoot '.wix'
$Candle     = Join-Path $WixDir 'candle.exe'
$Light      = Join-Path $WixDir 'light.exe'

if (-not (Test-Path $Candle)) {
    $WixZipUrl = 'https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip'
    # Empreinte épinglée du zip wix314-binaries.zip (wix3141rtm) : on exécute
    # candle.exe/light.exe depuis cette archive, donc on vérifie son intégrité
    # avant extraction pour fermer un vecteur d'exécution (archive falsifiée).
    $WixZipSha256 = '6ac824e1642d6f7277d0ed7ea09411a508f6116ba6fae0aa5f2c7daa2ff43d31'
    $WixZip       = Join-Path $RepoRoot 'wix314-binaries.zip'
    Write-Host "Téléchargement de WiX $WixVersion..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $WixZipUrl -OutFile $WixZip
    $actual = (Get-FileHash -Algorithm SHA256 -Path $WixZip).Hash
    if ($actual -ne $WixZipSha256) {
        Remove-Item $WixZip -Force
        throw "Empreinte WiX invalide : attendue $WixZipSha256, obtenue $actual"
    }
    if (Test-Path $WixDir) { Remove-Item -Recurse -Force $WixDir }
    Expand-Archive -Path $WixZip -DestinationPath $WixDir -Force
    Remove-Item $WixZip -Force
}
if (-not (Test-Path $Candle)) { throw "candle.exe introuvable après extraction WiX : $Candle" }

# --- Build -------------------------------------------------------------------
$ObjDir = Join-Path $RepoRoot 'build\wix'
if (Test-Path $ObjDir) { Remove-Item -Recurse -Force $ObjDir }
New-Item -ItemType Directory -Force -Path $ObjDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$WixObj = Join-Path $ObjDir 'persoia.wixobj'
$MsiOut = Join-Path $OutDir "persoia-$NumericVersion-$Arch.msi"

Write-Host "candle..."
& $Candle -nologo -arch $Arch `
    "-dVersion=$NumericVersion" `
    "-dExePath=$ExePath" `
    "-dIconPath=$IconPath" `
    "-dLicenseRtf=$LicenseRtf" `
    -out $WixObj $WxsPath
if ($LASTEXITCODE -ne 0) { throw "candle a échoué (code $LASTEXITCODE)" }

Write-Host "light..."
# -ext WixUIExtension : UI minimale (licence/progression/fin).
# -sice:ICE61 : AllowSameVersionUpgrades déclenche un avertissement ICE61 attendu.
& $Light -nologo -ext WixUIExtension -sice:ICE61 -out $MsiOut $WixObj
if ($LASTEXITCODE -ne 0) { throw "light a échoué (code $LASTEXITCODE)" }

Write-Host "MSI généré : $MsiOut"
