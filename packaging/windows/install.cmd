@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ===========================================================================
REM  Installe PersoIA CLI sur Windows sans MSI (alternative CMD, ref. #392).
REM
REM  Telecharge le dernier binaire persoia depuis les releases GitHub, le pose
REM  dans %LOCALAPPDATA%\PersoIA et ajoute ce dossier au PATH utilisateur
REM  (aucun droit administrateur requis).
REM ===========================================================================

REM --- Architecture : x64 natif (AMD64) ou ARM64 (emulation x64). Pas de x86.
set "ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "ARCH=%PROCESSOR_ARCHITEW6432%"
if /I not "%ARCH%"=="AMD64" if /I not "%ARCH%"=="ARM64" (
    echo Architecture non supportee : %ARCH%.
    echo PersoIA CLI necessite un Windows 64 bits ^(x64 ou ARM64^).
    exit /b 1
)

set "INSTALLDIR=%LOCALAPPDATA%\PersoIA"
set "TARGET=%INSTALLDIR%\persoia.exe"
set "URL=https://github.com/FishMoiLaPaix/persoia-cli/releases/latest/download/persoia-windows-x64.exe"

echo Installation de PersoIA CLI dans %INSTALLDIR% (%ARCH%)...
if not exist "%INSTALLDIR%" mkdir "%INSTALLDIR%"

curl -fsSL "%URL%" -o "%TARGET%"
if errorlevel 1 (
    echo Echec du telechargement depuis %URL%
    exit /b 1
)

REM --- PATH utilisateur : lire le scope User dans le registre, puis setx ------
REM (setx ecrit dans le scope utilisateur ; limite ~1024 caracteres.)
set "USERPATH="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USERPATH=%%B"

echo %USERPATH% | find /I "%INSTALLDIR%" >nul
if errorlevel 1 (
    if defined USERPATH (
        setx PATH "%USERPATH%;%INSTALLDIR%" >nul
    ) else (
        setx PATH "%INSTALLDIR%" >nul
    )
    echo PATH utilisateur mis a jour.
) else (
    echo PATH deja configure.
)

echo.
echo PersoIA CLI installe.
echo Ouvrez un NOUVEAU terminal ^(le PATH n'est pas herite par la session courante^).
echo Puis lancez : persoia login   ^(connexion et cle API^)
endlocal
