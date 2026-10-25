# Contributing

Install the project using the README, then run:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

The default suite uses synthetic data and simulated transports. Optional tests requiring private or third-party samples skip when those files are absent. `MX700_RAW_SAMPLE`, `MX700_LEGACY_SAMPLE`, and `MX700_MODERN_SAMPLE` can point to local fixtures; never commit those fixtures.

Keep edits byte-preserving outside the intended fields. Add focused tests for format or protocol changes, including malformed input and failures. Preserve bounded I/O, write allowlists, source comparisons, and readback verification. Avoid automatic write retries.

For hardware reports, include remote model/revision, adapter chipset, operation, and outcome. Do not post full configuration backups or personal display text. State whether a result is simulated or physically tested. Do not test against the only copy of a configuration.

`hardware_roundtrip.py` is an explicit physical write test, excluded from automated CI. It requires an original full backup and `--confirm-same-content-write`; it writes the unchanged system section and then compares a full readback. Read its code before use.

Contributions are provided under the repository's Unlicense. Do not contribute proprietary software, vendor code databases, or third-party configuration files.
