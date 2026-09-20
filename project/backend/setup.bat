@echo off
REM One-time setup for Windows: creates venv and installs dependencies.
python -m venv venv
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
if not exist ".env" copy .env.example .env
echo.
echo Setup complete. Edit backend\.env if needed, then run start.bat
