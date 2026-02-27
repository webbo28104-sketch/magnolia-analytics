@echo off
echo.
echo  Magnolia Analytics - Setup
echo ================================
echo.

echo Step 1/3: Installing Python packages...
pip install -r requirements.txt
echo   Done.
echo.

echo Step 2/3: Setting up the database...
flask db init
flask db migrate -m "initial schema"
flask db upgrade
echo   Done.
echo.

echo Step 3/3: Adding default courses...
python seed.py
echo.

echo ================================
echo  Setup complete!
echo.
echo  To start the app, double-click start.bat
echo  Then open your browser to: http://127.0.0.1:5000
echo.
pause
