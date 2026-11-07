param(
    [Parameter(Mandatory)][ValidateSet('CommitAndPush','Release')][string]$Phase,
    [Parameter(Mandatory)][string]$Packet,
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ApprovedManifestSha256,
    [Parameter(Mandatory)][switch]$OwnerApproved,
    [Parameter(Mandatory)][string]$Workspace
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 required' }
if (-not $OwnerApproved) { throw 'Owner approval of the exact review identity is required' }
Import-Module (Join-Path $PSScriptRoot 'Publication.Gates.psm1') -Force
$metadata = Get-ReviewedMetadata -Packet $Packet -Source $Source -ApprovedManifestSha256 $ApprovedManifestSha256
foreach ($pair in @(@((Join-Path $metadata.Source 'tools/release/Publication.Gates.psm1'),(Join-Path $PSScriptRoot 'Publication.Gates.psm1')),@((Join-Path $metadata.Source 'tools/release/Publish-ReviewedCandidate.ps1'),$PSCommandPath))) {
    if ((Get-FileHash -LiteralPath $pair[0]).Hash -ne (Get-FileHash -LiteralPath $pair[1]).Hash) { throw 'Publication tools differ from approved source' }
}
Push-Location -LiteralPath $Workspace
try {
    $env:GIT_OPTIONAL_LOCKS = '0'
    if ($Phase -ceq 'CommitAndPush') {
        if ((Get-FileHash -LiteralPath '.git/index').Hash -ne '5201124203ed852a3a62f522079517bd6d00f8ee70d76e33e79b2876e2bc0e5e') { throw 'Original index differs' }
    }
    Invoke-PublicationFlow -Phase $Phase -Meta $metadata
} finally { Pop-Location }
