param([switch]$LocalIdentity)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'signing.ps1')
$directory = Join-Path $root ('.tmp/signing-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $directory -Force | Out-Null
try {
    $metadata = Join-Path $directory 'identity.json'
    [IO.File]::WriteAllText($metadata, '{"thumbprint":"invalid","subject":"CN=Test"}', [Text.UTF8Encoding]::new($false))
    try {
        $unexpected = Resolve-SigningCertificate -IdentityFile $metadata
        $unexpected.Dispose()
        throw 'Invalid signing identity was accepted.'
    } catch {
        if ($_.Exception.Message -ne 'Invalid signing identity metadata.') { throw }
    }
    if ($LocalIdentity) {
        Copy-Item -LiteralPath (Join-Path $root 'signing/identity.json') -Destination $metadata -Force
        Copy-Item -LiteralPath (Join-Path $root 'signing/publisher.cer') -Destination (Join-Path $directory 'publisher.cer')
        # Model a missing store entry without deleting any real certificate or key.
        function Get-Item { param([string]$LiteralPath) return $null }
        try {
            $certificate = Resolve-SigningCertificate -IdentityFile $metadata
            try {
                $identity = Get-Content $metadata -Raw -Encoding utf8 | ConvertFrom-Json
                if (-not $certificate.HasPrivateKey -or $certificate.Thumbprint -ne $identity.thumbprint) { throw 'Existing-key recovery failed.' }
                $probe = Join-Path $directory 'signed probe.ps1'
                [IO.File]::WriteAllText($probe, "Write-Output 'Signing probe'`n", [Text.UTF8Encoding]::new($false))
                $null = Set-AuthenticodeSignature -LiteralPath $probe -Certificate $certificate -HashAlgorithm SHA256
                $verified = Get-AuthenticodeSignature -LiteralPath $probe
                if ($verified.SignerCertificate.Thumbprint -ne $identity.thumbprint -or $verified.Status -in @('NotSigned','HashMismatch')) { throw 'Recovered identity did not sign.' }
            } finally { $certificate.Dispose() }
        } finally { Remove-Item Function:\Get-Item }
        $identity.thumbprint = '0' * 40
        $identity | ConvertTo-Json | Set-Content $metadata -Encoding utf8
        try {
            $unexpected = Resolve-SigningCertificate -IdentityFile $metadata
            $unexpected.Dispose()
            throw 'Mismatched public certificate was accepted.'
        } catch {
            if ($_.Exception.Message -ne 'Public signing certificate does not match the approved identity.') { throw }
        }
    }
    Write-Output 'PASS signing identity validation and requested recovery contracts'
} finally {
    Remove-Item -LiteralPath $directory -Recurse -Force
}
