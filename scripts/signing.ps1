function Resolve-SigningCertificate {
    param([Parameter(Mandatory)][string]$IdentityFile)
    $identity = Get-Content -LiteralPath $IdentityFile -Raw -Encoding utf8 | ConvertFrom-Json
    if ($identity.thumbprint -notmatch '^[A-Fa-f0-9]{40}$' -or -not $identity.subject) {
        throw 'Invalid signing identity metadata.'
    }
    if ($identity.ownerSid -and $identity.ownerSid -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
        throw 'Signing identity belongs to another Windows account.'
    }
    $publicFile = Join-Path (Split-Path $IdentityFile -Parent) 'publisher.cer'
    $public = [Security.Cryptography.X509Certificates.X509Certificate2]::new($publicFile)
    try {
        if ($public.Thumbprint -ne $identity.thumbprint -or $public.Subject -ne $identity.subject) {
            throw 'Public signing certificate does not match the approved identity.'
        }
        if ($public.NotAfter.ToUniversalTime() -le [DateTime]::UtcNow -or $public.NotBefore.ToUniversalTime() -gt [DateTime]::UtcNow) {
            throw 'Approved signing certificate is outside its validity period.'
        }
        $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $identity.thumbprint) -ErrorAction SilentlyContinue
        if (-not $certificate -or -not $certificate.HasPrivateKey) {
            if (-not $identity.keyName -or -not $identity.keyProvider) {
                throw 'Approved signing key is unavailable. Recover its existing key association; do not generate a replacement.'
            }
            # Rebind the existing persisted key, never export it or generate a replacement.
            $provider = [Security.Cryptography.CngProvider]::new($identity.keyProvider)
            $key = [Security.Cryptography.CngKey]::Open($identity.keyName, $provider)
            try {
                $rsa = [Security.Cryptography.RSACng]::new($key)
                try {
                    $certificate = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey($public, $rsa)
                } finally { $rsa.Dispose() }
            } finally { $key.Dispose() }
        }
        try {
            $rsa = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
            if (-not $rsa) { throw 'Approved signing key is not accessible.' }
            try {
                $message = [Text.Encoding]::UTF8.GetBytes('Kiaro signing identity preflight')
                $signature = $rsa.SignData($message, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
                $verifier = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($public)
                try {
                    if (-not $verifier.VerifyData($message, $signature, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)) {
                        throw 'Approved signing key does not match its public certificate.'
                    }
                } finally { $verifier.Dispose() }
                if ($rsa -is [Security.Cryptography.RSACng]) {
                    $identity | Add-Member -Force NoteProperty keyName $rsa.Key.KeyName
                    $identity | Add-Member -Force NoteProperty keyProvider $rsa.Key.Provider.Provider
                    $identity | Add-Member -Force NoteProperty ownerSid ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
                    $serialized = $identity | ConvertTo-Json
                    $existing = Get-Content -LiteralPath $IdentityFile -Raw -Encoding utf8
                    if ($existing.Trim() -ne $serialized.Trim()) {
                        $temporary = $IdentityFile + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
                        try {
                            [IO.File]::WriteAllText($temporary, $serialized + "`n", [Text.UTF8Encoding]::new($false))
                            Move-Item -LiteralPath $temporary -Destination $IdentityFile -Force
                        } finally { if (Test-Path $temporary) { Remove-Item -LiteralPath $temporary } }
                    }
                }
            } finally { $rsa.Dispose() }
            return $certificate
        } catch {
            $certificate.Dispose()
            throw
        }
    } finally { $public.Dispose() }
}
