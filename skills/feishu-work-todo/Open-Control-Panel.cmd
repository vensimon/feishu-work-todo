@echo off
where py >nul 2>nul
if errorlevel 1 (
  python "%~dp0scripts\control_panel.py" open
) else (
  py -3 "%~dp0scripts\control_panel.py" open
)
if errorlevel 1 pause
