# Reviewed publication tools

These tools prepare a controlled future publication from a sealed owner-reviewed packet. They were tested with simulated native drivers; preparation does not authorize their write phases.

Use PowerShell 7. The entrypoint requires the exact SHA256 of REVIEW-ARTIFACTS.json, the fresh extraction of the reviewed public source ZIP, the packet directory, the original workspace and an explicit OwnerApproved switch. It checks every packet and source hash before calling Git. Its own module and entrypoint must match the approved source inventory.

CommitAndPush stages only blobs read directly from that approved source. It uses exact path/mode/blob values and removes excluded paths from the index, preserving the local files. It never stages private governance from the workspace and does not reset unrelated edits. A full staged-tree check precedes the commit and an exact new-parent/tag-target check precedes the atomic push.

Release checks the new commit and annotated tag, the exact staged and remote tree, the actual first-attempt push run, both platform jobs, four complete 1299-test source/wheel summaries and all original identities, then creates only the proposed prerelease. Uploaded asset inventory and server SHA256 digests are checked. Any git/gh nonzero result or identity mismatch throws before the next action; after a failure, retain the trace and inspect actual state instead of blindly retrying.

The local review packet and public folder have different manifests. Only names in ATTACHMENTS.json are proposed for upload. Public SHA256SUMS covers all public payloads plus their public ARTIFACTS.json; neither local execution logs nor this procedure are required by that public checksum list.

Run the reversible gate tests with:

    C:/Program Files/PowerShell/7/pwsh.exe -NoProfile -File tools/release/Test-PublicationGates.ps1 -IdentitiesPath <packet>/EXPECTED-TESTS.json -OutputDirectory <new-test-directory>

The 29 driver-based scenarios do not execute real git/gh mutations. The original source/wheel rounds and actual local CPU/Kit evidence are documented separately; the test traces are not substitutes for a future real CI result. See the packet PUBLICATION-PLAN.md for commands and post-publication download checks. The W5 task stops before every write phase.
For tests from the public source alone, use tools/release/expected-tests.json as IdentitiesPath; this is the same reviewed 1299-identity inventory.
