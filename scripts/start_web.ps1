[CmdletBinding()]
param(
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$python = Join-Path $project ".venv\Scripts\python.exe"
$healthUrl = "http://127.0.0.1:8000/health"
$appUrl = "http://127.0.0.1:8000/"

function Test-AppHealth {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -Method Get -TimeoutSec 2 -UseBasicParsing
        return [int]$response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Show-LaunchError {
    param([Parameter(Mandatory = $true)][string]$Message)
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            "AI Virtual Being - Startup Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    catch {
        Write-Error $Message
    }
}

function Stop-LaunchedServer {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)
    if ($Process.HasExited) { return }
    try {
        # 只停止本次脚本通过 Start-Process 创建且仍由该对象标识的进程。
        Stop-Process -Id $Process.Id -Force -ErrorAction Stop
    }
    catch {
        Write-Warning "Failed to clean up startup process $($Process.Id): $($_.Exception.Message)"
    }
}

if (Test-AppHealth) {
    if (-not $NoBrowser) { Start-Process $appUrl }
    exit 0
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Show-LaunchError "Port 8000 is already in use. Close the conflicting program and try again."
    exit 1
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Show-LaunchError "The project virtual environment was not found: $python"
    exit 1
}

$serverArguments = @{
    FilePath = $python
    ArgumentList = @("-m", "uvicorn", "app.main:app", "--app-dir", $project, "--port", "8000")
    WorkingDirectory = $project
    WindowStyle = "Hidden"
    PassThru = $true
}
$server = Start-Process @serverArguments

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($server.HasExited) { break }
    if (Test-AppHealth) {
        if (-not $NoBrowser) { Start-Process $appUrl }
        exit 0
    }
}

$startupMessage = "The service did not start within 30 seconds. Check Python, Uvicorn, and the app configuration."
Stop-LaunchedServer -Process $server
Show-LaunchError $startupMessage
exit 1
