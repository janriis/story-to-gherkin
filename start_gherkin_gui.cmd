@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Python-miljoeet mangler i .venv.
    echo Se README-gui.md for installationsvejledning.
    pause
    popd
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "gherkin_gui.py"
popd
