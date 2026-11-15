# Dev-only self-signed code signing certificate for local MSIX sideloading.
# Subject MUST match Identity Publisher in Package.appxmanifest: CN=Element Blocks Desktop
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools/make_cert.ps1
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI,
#       so UTF-8 Chinese text without a BOM would break string literals.
param(
    [string]$OutDir = (Join-Path $PSScriptRoot '..\dist\certs'),
    [string]$Password = 'ElementBlocksDev'
)

$ErrorActionPreference = 'Stop'
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$subject = 'CN=Element Blocks Desktop'
$pfx = Join-Path $OutDir 'ElementBlocksDesktop.pfx'
$cer = Join-Path $OutDir 'ElementBlocksDesktop.cer'

$existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Select-Object -First 1
if ($existing) {
    Write-Host "Reusing existing certificate, thumbprint $($existing.Thumbprint)"
    $cert = $existing
} else {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears(5) `
        -FriendlyName 'Element Blocks Desktop Dev Signing' `
        -KeyExportPolicy Exportable
    Write-Host "Created self-signed certificate, thumbprint $($cert.Thumbprint)"
}

$secure = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
Export-Certificate -Cert $cert -FilePath $cer | Out-Null
Write-Host "PFX: $pfx"
Write-Host "CER: $cer"
Write-Host "Before installing the MSIX, import the .cer into Local Machine / Trusted Root Certification Authorities."
