param(
    [Parameter(Mandatory = $true)]
    [string]$ApkPath,
    [string]$PackageName = "it.traflix.voice",
    [string]$AdbPath = "adb",
    [int]$WaitSeconds = 5
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) {
    throw "APK not found: $ApkPath"
}

function Invoke-Adb {
    param([string[]]$Arguments)
    & $AdbPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "adb failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

$deviceState = (Invoke-Adb @("get-state") | Out-String).Trim()
if ($deviceState -ne "device") {
    throw "No ready Android device found (state: '$deviceState')"
}

Invoke-Adb @("install", "-r", "-d", $ApkPath) | Out-Null
Invoke-Adb @("logcat", "-c")
Invoke-Adb @("shell", "am", "force-stop", $PackageName) | Out-Null
Invoke-Adb @("shell", "monkey", "-p", $PackageName, "1") | Out-Null
Start-Sleep -Seconds $WaitSeconds

$crashLog = (Invoke-Adb @("logcat", "-b", "crash", "-d", "-v", "threadtime") | Out-String)
if ($crashLog -match "Process:\s+$([regex]::Escape($PackageName))\b" -and $crashLog -match "FATAL EXCEPTION") {
    Write-Output $crashLog
    throw "Android startup crash detected for $PackageName"
}

$processId = (Invoke-Adb @("shell", "pidof", $PackageName) | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($processId)) {
    $activityState = (Invoke-Adb @("shell", "dumpsys", "activity", "activities") | Select-String -Pattern $PackageName | Out-String).Trim()
    throw "Android process is not alive after launch. Activity state: $activityState"
}

Write-Output "ANDROID_STARTUP_SMOKE_PASS package=$PackageName pid=$processId"
