# Release checklist

1. Review source, service access terms, privacy, documentation, and branding rights.
2. Update matching versions in `pyproject.toml` and the integration manifest; regenerate `uv.lock`.
3. Run all documented checks, Home Assistant hassfest, and the HACS validator without exclusions. Private repositories intentionally skip HACS; that skip is not a validation pass.
4. Test setup and unload on a separately authorized Home Assistant installation. Mocked tests and live API reads do not prove installation.
5. Obtain explicit approval for public visibility and release publication. A public repository is required for HACS distribution; catalog inclusion is separate.
6. Push the reviewed commit, verify remote CI, and inspect the downloaded manual-install artifact and checksum.
7. Create an immutable version tag on the tested commit, verify it resolves to that commit, and publish a reviewed GitHub release.

CI only builds nonpublishing artifacts. HACS uses the normal source repository layout; the manual-install ZIP is not configured as a HACS zip release.
