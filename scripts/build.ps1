$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Create .venv and install requirements-dev.txt first.' }
$releaseVersion = & $pythonExe -c "from classroom.version import VERSION; print(VERSION)"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read release version.' }
$versionRoot = Join-Path $projectRoot ('dist\v' + $releaseVersion)
New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
& $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --distpath $versionRoot --name ClassroomAssistant --add-data 'resources;resources' --add-data 'classroom/web/templates;classroom/web/templates' --add-data 'classroom/web/static;classroom/web/static' launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
$delivery = Join-Path $versionRoot 'ClassroomAssistant'
New-Item -ItemType Directory -Path $delivery -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $versionRoot 'ClassroomAssistant.exe') -Destination $delivery
Copy-Item -LiteralPath 'README.md','CHANGELOG.md' -Destination $delivery
$docsTarget = Join-Path $delivery 'docs'
New-Item -ItemType Directory -Path $docsTarget -Force | Out-Null
Copy-Item -LiteralPath 'docs' -Destination $delivery -Recurse -Force
Compress-Archive -LiteralPath $delivery -DestinationPath (Join-Path $versionRoot ('ClassroomAssistant-v' + $releaseVersion + '-Win10-x64.zip')) -Force
& $pythonExe scripts/build_source.py
if ($LASTEXITCODE -ne 0) { throw 'Source archive failed.' }
Write-Output $delivery
