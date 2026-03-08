@echo off
cd /d "%~dp0"

:: Stamp sw.js with current timestamp so browser cache is busted on every deploy
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TIMESTAMP=%DT:~0,12%
powershell -Command "(Get-Content sw.js) -replace 'tasknari-BUILD_TIMESTAMP', 'tasknari-%TIMESTAMP%' | Set-Content sw.js"

git add .
git commit -m "Update Tasknari"
git push

:: Restore the placeholder so next deploy works the same way
powershell -Command "(Get-Content sw.js) -replace 'tasknari-%TIMESTAMP%', 'tasknari-BUILD_TIMESTAMP' | Set-Content sw.js"

echo.
echo Done! Changes will be live at https://JABOYSKI.github.io/tasknari/ in about 60 seconds.
pause
