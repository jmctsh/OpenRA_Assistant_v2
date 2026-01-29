@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Resolve base directory (this script is placed in d:\OpenCodeAlert-Hackathon\dist)
set "BASE=%~dp0"

REM Ensure we run inside the win-x64 directory so working directory is correct
pushd "%BASE%win-x64" >nul 2>&1

REM Always launch Copilot mod (no prompt). Prefer dist\win-x64\mods\copilot if present
set "MODARG="
if exist "%CD%\mods\copilot\mod.yaml" (
  set "MODARG=Game.Mod=%CD%\mods\copilot"
) else if exist "%BASE%..\mods\copilot\mod.yaml" (
  set "MODARG=Game.Mod=%BASE%..\mods\copilot"
) else (
  set "MODARG=Game.Mod=copilot"
)

REM Launch OpenRA with Copilot mod (forward any extra args)
start "" "OpenRA.exe" %MODARG% %*

REM Restore previous directory
popd >nul 2>&1

endlocal