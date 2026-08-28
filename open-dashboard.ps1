# Build the reviewer dashboard from this repository and open it in the browser.
#
#   Right-click this file and choose "Run with PowerShell", or double-click
#   open-dashboard.cmd beside it. Nothing to install: the page is built by the
#   Python standard library. Where no Python is found the script opens the
#   dashboard.html already in the folder, which is the static snapshot of the
#   data as of the last build, and says so.
#
# The dashboard is a static picture of the data at build time. After any data
# changes, run this again for an updated page. A build that fails stops here
# with its error; it never opens an older page in its place.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$page = Join-Path $root "dashboard.html"

function Find-Python {
    foreach ($candidate in @("python", "python3", "py")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            $version = & $command.Source --version 2>&1
            if ("$version" -match "Python 3\.(9|1\d)") { return $command.Source }
        }
    }
    return $null
}

$python = Find-Python
if ($python) {
    Write-Host "Building the dashboard from the published files with $python ..."
    & $python (Join-Path $root "src\dashboard\build_dashboard.py") --output $page
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "The build failed, so nothing was opened. The message above says why."
        Write-Host "The committed dashboard.html is the snapshot from the last successful build; open it by hand if that is what you want."
        exit 1
    }
    Write-Host "Opening $page"
    Start-Process $page
    exit 0
}

if (Test-Path $page) {
    Write-Host "No Python 3.9 or later on this machine, so this opens the committed snapshot: the data as of the last build, and nothing newer."
    Start-Process $page
    exit 0
}

Write-Host "No dashboard.html here and no Python to build one. Install Python 3 and run this again, or fetch the built page from the repository."
exit 1
