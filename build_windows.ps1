<#
Builds a clean, shareable Windows desktop package and creates a Desktop
shortcut. The package never includes .env credentials, logins, or history.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$outputDirectory = Join-Path $projectRoot "dist\SoundFlix"
$executable = Join-Path $outputDirectory "SoundFlix.exe"

if (-not (Test-Path $python)) {
    throw "The project virtual environment was not found at $python"
}

Push-Location $projectRoot
try {
    # Remove only the prior generated app folder. This prevents a previously
    # copied .env from surviving into a clean build.
    if (Test-Path $outputDirectory) {
        Remove-Item -LiteralPath $outputDirectory -Recurse -Force
    }

    & $python -m PyInstaller --noconfirm --clean --log-level WARN --windowed --onedir --name SoundFlix `
        --collect-all customtkinter --collect-all tidalapi `
        --collect-all spotipy --hidden-import keyring.backends.Windows app/main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller did not finish successfully."
    }

    # Include only the safe template. Each user may create their own .env
    # alongside the executable if they want Spotify, SoundCloud, or Apple
    # Music credentials; nothing private is copied from this project.
    $dotenvTemplate = Join-Path $projectRoot ".env.example"
    if (Test-Path $dotenvTemplate) {
        Copy-Item -LiteralPath $dotenvTemplate -Destination (Join-Path $outputDirectory ".env.example") -Force
    }

    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "SoundFlix.lnk"))
    $shortcut.TargetPath = $executable
    $shortcut.WorkingDirectory = $outputDirectory
    $shortcut.IconLocation = "$executable,0"
    $shortcut.Save()

    Write-Host "Clean SoundFlix desktop package created: $outputDirectory"
    Write-Host "A SoundFlix shortcut was created on your Desktop."
    Write-Host "No .env secrets, service logins, or playlist history were included."
}
finally {
    Pop-Location
}
