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
foreach ($pair in @(@((Join-Path $metadata.Source 'tools/release/v140/Publication.Gates.psm1'),(Join-Path $PSScriptRoot 'Publication.Gates.psm1')),@((Join-Path $metadata.Source 'tools/release/v140/Publish-ReviewedCandidate.ps1'),$PSCommandPath))) {
    if ((Get-FileHash -LiteralPath $pair[0]).Hash -ne (Get-FileHash -LiteralPath $pair[1]).Hash) { throw 'Publication tools differ from approved source' }
}
Push-Location -LiteralPath $Workspace
try {
    $env:GIT_OPTIONAL_LOCKS = '0'
    if ($Phase -ceq 'CommitAndPush') {
        if ((Get-FileHash -LiteralPath '.git/index').Hash -ne '477433bc8b661a259c08a67226cd8bc872b42631eeb1658447223cc2a339cfac') { throw 'Original index differs' }
    }
    Invoke-PublicationFlow -Phase $Phase -Meta $metadata
} finally { Pop-Location }
