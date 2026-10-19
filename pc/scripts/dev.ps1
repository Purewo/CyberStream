param([ValidateRange(1024,65535)][int]$Port = 41731)
$ErrorActionPreference = 'Stop'
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$frontend = Join-Path $repo 'frontend'
$url = "http://127.0.0.1:$Port"
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($listener) {
    try {
        $ownsPort = @($listener | ForEach-Object {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
            $process.CommandLine -and $process.CommandLine.Replace('/','\').Contains($frontend)
        }) -contains $true
        if (-not $ownsPort) { throw 'Different checkout owns this listener' }
        $entry = Invoke-WebRequest -UseBasicParsing -Uri "$url/src/platform/index.ts" -TimeoutSec 5
        if ($entry.StatusCode -ne 200 -or $entry.Content -notmatch 'createPcPlatform') {
            throw 'Unexpected application'
        }
    } catch {
        throw "Port $Port belongs to another service. Choose a different -Port; no process was stopped."
    }
} else {
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $vite)) { throw 'Install frontend dependencies before starting PC dev.' }
    $server = Start-Process -FilePath $node -ArgumentList @($vite,'--host','127.0.0.1','--port',"$Port",'--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru
    $ready = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        try { $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1; $ready = $r.StatusCode -eq 200 } catch {}
        if ($ready) { break }
        if ($server.HasExited) { throw 'Vite exited before it became ready.' }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Vite did not become ready at $url (PID $($server.Id))." }
}
$config = Join-Path ([System.IO.Path]::GetTempPath()) ("cyberstream-pc-dev-" + [guid]::NewGuid().ToString('N') + '.json')
$json = @{build=@{beforeDevCommand='';devUrl=$url}} | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($config, $json, [System.Text.UTF8Encoding]::new($false))
Push-Location (Join-Path $repo 'pc\src-tauri')
try {
    Write-Host "PC dev uses $url; the Web server remains available after PC closes."
    cargo tauri dev --no-watch --config $config -- --offline
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item -LiteralPath $config -ErrorAction SilentlyContinue
}
exit $code
