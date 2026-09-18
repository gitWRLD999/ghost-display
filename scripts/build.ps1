[CmdletBinding()]
param(
    [string[]] $Tasks = @('clean', ':app:assembleDebug'),
    [string] $Keystore = $env:GHOST_KEYSTORE,
    [string] $JavaHome = $env:JAVA_HOME,
    [string] $AndroidSdk = $env:ANDROID_HOME,
    [string] $ExpectedCertificateSha256 = $env:GHOST_SIGNING_CERT_SHA256
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$originalJavaHome = $env:JAVA_HOME
$originalAndroidHome = $env:ANDROID_HOME
$originalGhostKeystore = $env:GHOST_KEYSTORE

if (-not $JavaHome) {
    $studioJdk = Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'
    if (Test-Path -LiteralPath (Join-Path $studioJdk 'bin\java.exe')) {
        $JavaHome = $studioJdk
    } else {
        $javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
        if ($javaCommand) { $JavaHome = Split-Path -Parent (Split-Path -Parent $javaCommand.Source) }
    }
}
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\javac.exe'))) {
    throw 'Install JDK 17 or newer, then set JAVA_HOME or pass -JavaHome.'
}
if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_SDK_ROOT }
if (-not $AndroidSdk -and $env:LOCALAPPDATA) {
    $AndroidSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
}
if (-not $AndroidSdk -or -not (Test-Path -LiteralPath (Join-Path $AndroidSdk 'platforms\android-36\android.jar'))) {
    throw 'Install Android SDK platform 36, then set ANDROID_HOME or pass -AndroidSdk.'
}
$apkSigner = Join-Path $AndroidSdk 'build-tools\36.0.0\apksigner.bat'
if (-not (Test-Path -LiteralPath $apkSigner)) {
    throw 'Install Android SDK build-tools 36.0.0.'
}
if ($Keystore) {
    $Keystore = (Resolve-Path -LiteralPath $Keystore).Path
}

Push-Location $projectDirectory
try {
    $env:JAVA_HOME = $JavaHome
    $env:ANDROID_HOME = $AndroidSdk
    if ($Keystore) { $env:GHOST_KEYSTORE = $Keystore }
    & (Join-Path $projectDirectory 'gradlew.bat') @Tasks '--console=plain' '--no-daemon'
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed with exit code $LASTEXITCODE." }

    $apkPath = Join-Path $projectDirectory 'app\build\outputs\apk\debug\app-debug.apk'
    if (-not (Test-Path -LiteralPath $apkPath)) { throw "The debug APK was not produced: $apkPath" }
    $signatureOutput = @(& $apkSigner verify --verbose --print-certs $apkPath)
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    $signatureOutput | ForEach-Object { Write-Host $_ }
    $certificateLine = $signatureOutput | Where-Object { $_ -match '^Signer #1 certificate SHA-256 digest: ' } | Select-Object -First 1
    $certificateHash = ($certificateLine -replace '^Signer #1 certificate SHA-256 digest: ', '').Trim()
    if ($ExpectedCertificateSha256 -and $certificateHash -ne ($ExpectedCertificateSha256 -replace ':', '').ToLowerInvariant()) {
        throw 'APK signing certificate does not match the expected installed-app certificate.'
    }
    [pscustomobject]@{
        Apk = $apkPath
        Bytes = (Get-Item -LiteralPath $apkPath).Length
        Sha256 = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
        SigningCertificateSha256 = $certificateHash
    }
} finally {
    $env:JAVA_HOME = $originalJavaHome
    $env:ANDROID_HOME = $originalAndroidHome
    $env:GHOST_KEYSTORE = $originalGhostKeystore
    Pop-Location
}
