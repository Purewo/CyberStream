param([int]$ProxyPort = 0, [switch]$InstallDependencies)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $env:JAVA_HOME -and (Test-Path -LiteralPath 'E:\Tools\jdk21\bin\java.exe')) {
    $env:JAVA_HOME = 'E:\Tools\jdk21'
}
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$env:GOMAXPROCS = '2'
if ($InstallDependencies -or -not (Test-Path -LiteralPath 'node_modules')) {
    npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
}
npm.cmd test
if ($LASTEXITCODE -ne 0) { throw 'Recovery regression tests failed' }
npm.cmd run android:sync
if ($LASTEXITCODE -ne 0) { throw 'Frontend build / Capacitor sync failed' }
$gradleArgs = @(':app:assembleDebug', ':app:testDebugUnitTest', ':app:assembleDebugAndroidTest',
    '--no-daemon', '--console=plain', '--max-workers=2',
    '-Pkotlin.compiler.execution.strategy=in-process', '-Dorg.gradle.jvmargs=-Xmx1536m -XX:ActiveProcessorCount=2')
if ($ProxyPort -gt 0) {
    $gradleArgs += @('-Dhttps.proxyHost=127.0.0.1', "-Dhttps.proxyPort=$ProxyPort",
        '-Dhttp.proxyHost=127.0.0.1', "-Dhttp.proxyPort=$ProxyPort")
}
Push-Location -LiteralPath 'android'
try {
    & .\gradlew.bat @gradleArgs
    if ($LASTEXITCODE -ne 0) { throw 'Android build failed' }
} finally { Pop-Location }
Get-FileHash -Algorithm SHA256 -LiteralPath 'android\app\build\outputs\apk\debug\app-debug.apk'
