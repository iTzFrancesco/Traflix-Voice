param(
    [Parameter(Mandatory = $true)]
    [string]$ApkPath,
    [string]$AaptPath = "aapt"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) {
    throw "APK not found: $ApkPath"
}

$badging = & $AaptPath dump badging $ApkPath 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "aapt failed with exit code ${LASTEXITCODE}"
}

$nativeLine = ($badging | Select-String -Pattern '^native-code:' | Select-Object -First 1).Line
if ([string]::IsNullOrWhiteSpace($nativeLine)) {
    throw "APK does not declare native ABIs"
}

$requiredAbis = @("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
$missingAbis = @($requiredAbis | Where-Object { $nativeLine -notmatch [regex]::Escape($_) })
if ($missingAbis.Count -gt 0) {
    throw "APK is missing required ABIs: $($missingAbis -join ', '). Detected: $nativeLine"
}

Write-Output "ANDROID_ABI_SMOKE_PASS $nativeLine"
