[CmdletBinding()]
param([switch]$CreateSigningIdentity, [switch]$SkipCompile)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs ("build-desktop_{0}_{1}.log" -f [DateTime]::UtcNow.ToString('yyyy-MM-dd_HH-mm-ss_UTC'), [guid]::NewGuid().ToString('N').Substring(0,8))
function Write-Event([string]$message) {
    $line = '[{0} UTC] [INFO] [BUILD] {1}' -f [DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'), $message
    [IO.File]::AppendAllText($log, $line + "`n", [Text.UTF8Encoding]::new($false))
    Write-Host $message
}
try {
    $env:TEMP = Join-Path $root '.tmp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
    $env:CARGO_BUILD_JOBS = '2'
    Write-Event 'Starting desktop build version=0.5.1'
    if (-not $SkipCompile) {
        & npm --prefix (Join-Path $root 'desktop/web') ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
        & npm --prefix (Join-Path $root 'desktop/web') run build
        if ($LASTEXITCODE) { throw 'Frontend compilation failed.' }
        & cargo build --release --locked --manifest-path (Join-Path $root 'desktop/Cargo.toml') -j 2
        if ($LASTEXITCODE) { throw 'Rust compilation failed.' }
    }
    $identityFile = Join-Path $root 'signing/identity.json'
    if ($CreateSigningIdentity) {
        if (Test-Path -LiteralPath $identityFile) { throw 'Signing identity already exists; no replacement performed.' }
        $certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=KiaroSama' -FriendlyName 'Kiaro Unlimited-OCR local signing' -CertStoreLocation 'Cert:\CurrentUser\My' -KeyExportPolicy NonExportable -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(2)
        New-Item -ItemType Directory -Force -Path (Split-Path $identityFile -Parent) | Out-Null
        @{ thumbprint = $certificate.Thumbprint; subject = 'CN=KiaroSama'; trust = 'self-signed'; custody = 'CurrentUser certificate store; nonexportable key' } | ConvertTo-Json | Set-Content -LiteralPath $identityFile -Encoding utf8
        Export-Certificate -Cert $certificate -FilePath (Join-Path $root 'signing/publisher.cer') | Out-Null
        Write-Event 'Created explicitly authorized nonexportable self-signed identity; no trust-store installation'
    }
    if (-not (Test-Path -LiteralPath $identityFile)) { throw 'No project signing identity. Use -CreateSigningIdentity only after approving creation.' }
    $identity = Get-Content -LiteralPath $identityFile -Raw -Encoding utf8 | ConvertFrom-Json
    $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $identity.thumbprint)
    if (-not $certificate.HasPrivateKey) { throw 'Signing certificate has no private key.' }
    $executable = Join-Path $root 'desktop/target/release/kiaro-unlimited-ocr.exe'
    $signature = Set-AuthenticodeSignature -LiteralPath $executable -Certificate $certificate -HashAlgorithm SHA256
    $verified = Get-AuthenticodeSignature -LiteralPath $executable
    if ($verified.SignerCertificate.Thumbprint -ne $identity.thumbprint -or $verified.Status -eq 'HashMismatch' -or $verified.Status -eq 'NotSigned') { throw 'Executable signature verification failed.' }
    $tampered = Join-Path $env:TEMP ('signature-check-' + [guid]::NewGuid().ToString('N') + '.exe')
    try {
        $bytes = [IO.File]::ReadAllBytes($executable)
        $bytes[1024] = $bytes[1024] -bxor 1
        [IO.File]::WriteAllBytes($tampered, $bytes)
        $rejected = Get-AuthenticodeSignature -LiteralPath $tampered
        if ($rejected.Status -ne 'HashMismatch') { throw 'Signature tamper rejection could not be verified.' }
    } finally {
        if (Test-Path -LiteralPath $tampered) { Remove-Item -LiteralPath $tampered }
    }
    Write-Event ("Signed with approved identity; digest tamper rejected; platform trust={0}; SHA256={1}" -f $verified.Status, (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash)
    Write-Event 'Build finished. Self-signed certificate is not publicly trusted; Windows warnings can remain.'
} catch {
    Write-Event ("Build failed: " + $_.Exception.Message)
    throw
}
