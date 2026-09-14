$path = Join-Path $PSScriptRoot "03-report\dashboard.html"
if (-not (Test-Path $path)) { throw "Build the pricing report first." }
Start-Process $path
