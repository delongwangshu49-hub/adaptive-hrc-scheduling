# W5 limited delivery repair r2

The three W5 review findings are addressed within delivery preparation: separate public and local checksum inventories; exclude five internal records from the proposed public tree while preserving local files and earlier releases; and use fail-closed PowerShell publication gates. Runtime scheduling code, original tests and dependency locks are unchanged.

The source-exclusion policy is [recorded separately](../delivery/w5_publication_scope_r2.json). Forty-nine links in thirty-one documents resolve to the retained v1.0.1 source; earlier provenance hashes remain historical rather than being silently re-bound. Source ZIP, delta, the complete proposed Git tree and exact upsert/deletion lists are generated together. The future index-only removals preserve local governance.

The checked publication flow passed 29 simulated positive/negative cases, including native failures, local/remote tag collisions, old or wrong commits, unexpected staged blobs, incorrect tag targets, incomplete/failed CI, missing test summaries/identities, remote blob/ref mismatches and wrong attachment digests. No real Git write, remote upload, release, tag, branch, worktree or CI was created. All future git/gh calls have explicit nonzero exit handling. The current GitHub stable version remains v1.0.1; v1.1.0 is only the proposed application prerelease and Python metadata remains 0.1.0.

The complete report revision is English 28 pages and Chinese 25 pages. Original text, tables, equations, media and references retain their reviewed meaning; Section C.6 explains these delivery corrections. The original r1 reports and templates are retained with distinct r2 filenames. Rebuild inputs and Word export scripts are in reports/w5. Fifty-three pages were rendered and inspected, with 41 original pages pixel-identical to the reviewed baselines.

The original research figures require no redraw: none of these repairs changes a scientific measurement, model, denominator, hypothesis or result. No new figure is added.

The original r1 complete source/wheel rounds (1299 each), fixed plan/proof identity, actual CPU/Kit STOP/save/exit and read-only evidence remain bound to the same application source. They are reused with their original identities, not described as new r2 runs. The original W3 four-pair result also retains its measured version. E12 remains OWNER_PENDING, P08 OVERALL_INCOMPLETE and P09 NOT_STARTED; previous performance, K01, E20 split scope/all-received NOT_MET, WIP/J3, manual REST, Vite and industrial qualification limits remain.

This documentation describes local preparation. The final review packet provides exact public-only checksums, local review hashes, source inventory, full binary patch, predicted blob/mode tree and owner-facing review instructions. Publication requires separate explicit owner approval of that exact packet and remains unexecuted.
