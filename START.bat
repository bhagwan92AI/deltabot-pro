@echo off
title DeltaBot Pro
echo.
echo  Starting DeltaBot Pro...
echo  Opening browser at http://localhost:5000
echo.
pip install flask flask-cors requests -q
python main.py
pause