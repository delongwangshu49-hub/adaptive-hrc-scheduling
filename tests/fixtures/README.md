# Historical S20 source fixture

`s20_sources_r3.zip` contains the 243 source files already bound by
`experiments/manifests/s20_sources_r3.json`. Every member is recovered from
commit `a01e49c45b1ff5a0573d9fe8ab6837d778aef7ec`, restoring CRLF only where
required to match that existing manifest's exact SHA-256. No source digest,
experiment configuration, execution authorization or historical manifest is changed.

The design tests unpack these bytes to a temporary directory and retain the
existing strict source hash checks and corruption cases. They still validate
configuration reconstruction with the current implementation. A separate
negative test confirms the current P04 checkout cannot claim the historical
S20 source identity. The production validator retains its default current-root
check and continues to reject the old experiment against changed source.

These files are test data, never imported or executed, and do not authorize
resuming the old 64/636 experiments. The complete fixture makes the historical
check independent of shallow Git history, local backups and wheel installation.
