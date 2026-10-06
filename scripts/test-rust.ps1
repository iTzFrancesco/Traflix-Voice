$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$tauriDirectory = Join-Path $repositoryRoot "src-tauri"
$manifest = Join-Path $tauriDirectory "windows\test.manifest"
$windowsKitsBin = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"

Push-Location $tauriDirectory
try {
    $cargoOutput = cargo test --no-run --message-format=json
    if ($LASTEXITCODE -ne 0) {
        throw "cargo test --no-run failed with exit code $LASTEXITCODE"
    }

    $testExecutables = @(
        $cargoOutput | ForEach-Object {
            try {
                $message = $_ | ConvertFrom-Json -ErrorAction Stop
            } catch {
                return
            }

            if ($message.reason -eq "compiler-artifact" -and $message.target.test -and $message.executable) {
                $message.executable
            }
        } | Sort-Object -Unique
    )

    if ($testExecutables.Count -eq 0) {
        throw "Cargo did not report any test executables."
    }

    $manifestTool = Get-ChildItem -Path $windowsKitsBin -Filter mt.exe -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "[\\/]x64[\\/]mt\.exe$" } |
        Sort-Object { [version]$_.Directory.Parent.Name } -Descending |
        Select-Object -First 1

    if (-not $manifestTool) {
        throw "Could not find the Windows SDK manifest tool (mt.exe)."
    }

    foreach ($executable in $testExecutables) {
        & $manifestTool.FullName -manifest $manifest "-outputresource:$executable;#1" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not embed the test manifest in $executable (exit code $LASTEXITCODE)."
        }
    }

    cargo test
    if ($LASTEXITCODE -ne 0) {
        throw "cargo test failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
