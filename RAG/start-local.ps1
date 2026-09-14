$ErrorActionPreference = "Stop"

$ragRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $ragRoot
$runtimeRoot = if ($env:ALTS_RAG_RUNTIME) {
    $env:ALTS_RAG_RUNTIME
} else {
    Join-Path $env:LOCALAPPDATA "MinaAnalytics\AltsRAG"
}
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
$sourceRoot = Join-Path $ragRoot "src"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The local RAG Python environment is absent. Complete the setup in RAG/README.md."
}

$priorPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($priorPythonPath) { "$sourceRoot;$priorPythonPath" } else { $sourceRoot }
try {
    & $python -B -m alts_rag --project-root $projectRoot serve --confirm-loopback --reviewed-corpus
} finally {
    $env:PYTHONPATH = $priorPythonPath
}
