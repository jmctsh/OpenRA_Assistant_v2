@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Resolve base directory (this script is placed in d:\OpenCodeAlert-Hackathon\dist)
set "BASE=%~dp0"

REM Ensure we run inside the win-x64 directory so working directory is correct
pushd "%BASE%win-x64" >nul 2>&1

REM Determine Game.Mod argument
set "MODARG="
if not "%~1"=="" (
  set "ARG=%~1"
  REM If the argument looks like a directory containing mod.yaml, treat it as an explicit mod path
  if exist "%ARG%\mod.yaml" (
    set "MODARG=Game.Mod=%ARG%"
  ) else (
    REM Special-case copilot: if the repo mods/copilot exists, prefer explicit path for reliability
    if /I "%ARG%"=="copilot" (
      if exist "%BASE%..\mods\copilot\mod.yaml" (
        set "MODARG=Game.Mod=%BASE%..\mods\copilot"
      ) else (
        set "MODARG=Game.Mod=copilot"
      )
    ) else (
      set "MODARG=Game.Mod=%ARG%"
    )
  )
) else (
  REM Default to RA if no argument provided
  set "MODARG=Game.Mod=ra"
)

REM Launch OpenRA with the resolved mod
start "" "OpenRA.exe" %MODARG%

REM Restore previous directory
popd >nul 2>&1

endlocal