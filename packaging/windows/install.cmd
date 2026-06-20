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

REM --- Verification d'integrite (sidecar .sha256 publie avec la release) ------
REM Empeche l'execution d'un binaire altere. Avertit si le sidecar manque.
set "SHAFILE=%TEMP%\persoia.exe.sha256"
set "EXPECTED="
set "ACTUAL="
curl -fsSL "%URL%.sha256" -o "%SHAFILE%" 2>nul
if exist "%SHAFILE%" (
    set /p EXPECTED=<"%SHAFILE%"
    for /f "skip=1 delims=" %%H in ('certutil -hashfile "%TARGET%" SHA256') do if not defined ACTUAL set "ACTUAL=%%H"
    set "ACTUAL=!ACTUAL: =!"
    if /I not "!ACTUAL!"=="!EXPECTED!" (
        echo Empreinte du binaire invalide : attendue !EXPECTED!, obtenue !ACTUAL!.
        del "%TARGET%" 2>nul
        del "%SHAFILE%" 2>nul
        exit /b 1
    )
    del "%SHAFILE%" 2>nul
    echo Integrite verifiee ^(SHA-256^).
) else (
    echo Empreinte SHA-256 indisponible pour cette release -- integrite non verifiee.
)

REM --- PATH utilisateur : lire le scope User dans le registre, puis l'ecrire --
REM On utilise `reg add` (REG_EXPAND_SZ) plutot que `setx`, qui tronque
REM silencieusement les PATH > 1024 caracteres. Un nouveau terminal relit le
REM registre, donc la modif est prise en compte (cf. message de fin).
set "USERPATH="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USERPATH=%%B"

echo !USERPATH! | find /I "%INSTALLDIR%" >nul
if errorlevel 1 (
    if defined USERPATH (
        reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "!USERPATH!;%INSTALLDIR%" /f >nul
    ) else (
        reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "%INSTALLDIR%" /f >nul
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
