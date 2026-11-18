[CmdletBinding()]
param(
    [ValidatePattern('^gemini-[A-Za-z0-9._-]{1,90}$')]
    [string]$Model = 'gemini-3.1-flash-lite',
    [ValidateRange(1024, 65535)][int]$Port = 8080,
    [ValidateRange(1024, 65535)][int]$ApiPort = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create the project Python environment and install backend requirements first.' }
$savedProvider = [Environment]::GetEnvironmentVariable('AI_PROVIDER', 'Process')
$savedModel = [Environment]::GetEnvironmentVariable('GEMINI_MODEL', 'Process')
$savedKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'Process')
$privateKey = Read-Host 'Replacement Gemini API key (hidden; not saved)' -AsSecureString
$keyPointer = [IntPtr]::Zero
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($privateKey)
    $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    $keyPointer = [IntPtr]::Zero
    if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'No key entered.' }
    $env:AI_PROVIDER = 'gemini'
    $env:GEMINI_MODEL = $Model
    Write-Host "Starting the local Gemini coach with model $Model. Press Ctrl+C to stop."
    & $python (Join-Path $projectRoot 'tools/run_fullstack.py') --port $Port --api-port $ApiPort
    if ($LASTEXITCODE -ne 0) { throw 'The local application stopped with an error.' }
}
finally {
    if ($keyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
    $privateKey.Dispose()
    [Environment]::SetEnvironmentVariable('AI_PROVIDER', $savedProvider, 'Process')
    [Environment]::SetEnvironmentVariable('GEMINI_MODEL', $savedModel, 'Process')
    [Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $savedKey, 'Process')
    $savedKey = $null
}
