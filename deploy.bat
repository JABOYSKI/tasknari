@echo off
cd /d "%~dp0"
git add .
git commit -m "Update Tasknari"
git push
echo.
echo Done! Changes will be live at https://JABOYSKI.github.io/tasknari/ in about 60 seconds.
pause
