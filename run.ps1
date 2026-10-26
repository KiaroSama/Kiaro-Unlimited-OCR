[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$InputPath = '',
    [ValidateSet('base', 'gundam', 'persian')][string]$Mode = 'base',
    [ValidateRange(0, 100000)][int]$Pages = 0,
    [string]$PageSelection = '',
    [ValidateRange(1024, 32768)][int]$MaxLength = 8192,
    [switch]$Check,
    [switch]$Console
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Project Python environment is missing. See README setup instructions.'
    }
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PYTHONUTF8 = '1'
    if ($InputPath -or $Check) {
        $entry = Join-Path $PSScriptRoot 'scripts/ocr.py'
        $options = if ($Check) { @('--check') } else {
            @($InputPath, '--mode', $Mode, '--pages', [string]$Pages,
              '--page-selection', $PageSelection, '--max-length', [string]$MaxLength)
        }
    } elseif ($Console) {
        $entry = Join-Path $PSScriptRoot 'scripts/console.py'
        $options = @()
    } else {
        $desktop = Join-Path $PSScriptRoot 'desktop/target/release/kiaro-unlimited-ocr.exe'
        if (-not (Test-Path -LiteralPath $desktop -PathType Leaf)) {
            throw 'Rust desktop is not built. Run scripts/build-desktop.ps1 first, or use -Console.'
        }
        & $desktop
        exit $LASTEXITCODE
    }
    & $python '-I' '-X' 'utf8' '-u' $entry @options
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    if (-not $InputPath -and -not $Check) { [void](Read-Host 'Press Enter to close') }
    exit 1
}
