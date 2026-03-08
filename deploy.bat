@echo off
cd /d "%~dp0"

:: Get timestamp (YYYYMMDDHHmm)
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TIMESTAMP=%DT:~0,12%

:: Get human-readable date e.g. "Mar 8, 2026"
for /f "delims=" %%D in ('powershell -Command "Get-Date -Format \"MMM d, yyyy HH:mm:ss\""') do set READABLE_DATE=%%D

:: Stamp sw.js cache name with timestamp
powershell -Command "(Get-Content sw.js) -replace 'tasknari-BUILD_TIMESTAMP', 'tasknari-%TIMESTAMP%' | Set-Content sw.js"

:: Stamp build date into index.html
powershell -Command "(Get-Content index.html) -replace 'updated BUILD_DATE', 'updated %READABLE_DATE%' | Set-Content index.html"

git add .
git commit -m "Update Tasknari"
git push

:: Restore placeholders for next deploy
powershell -Command "(Get-Content sw.js) -replace 'tasknari-%TIMESTAMP%', 'tasknari-BUILD_TIMESTAMP' | Set-Content sw.js"
powershell -Command "(Get-Content index.html) -replace 'updated %READABLE_DATE%', 'updated BUILD_DATE' | Set-Content index.html"

echo.
echo Done! Changes will be live at https://JABOYSKI.github.io/tasknari/ in about 60 seconds.
pause
