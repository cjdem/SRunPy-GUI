# Corresponding Source Code

SRunPy and this modified version are licensed under GNU GPL v3.0 only. The complete corresponding source for a distributed binary must be the preferred form for making modifications and must include the scripts and project files needed to build that binary.

## Canonical repository

The repository currently configured for this project is:

<https://github.com/cjdem/SRunPy-GUI>

The repository home page alone is not sufficient to identify the source for a particular binary. Every public installer or portable archive should state all of the following in its release notes:

```text
Version: <application version>
Source tag: <Git tag>
Source commit: <full commit hash>
Source archive: <stable release or archive URL>
Build instructions: README.md, section "构建 Windows 发布包"
```

This public fork contains the modifications present in this distribution. Release artifacts must point to a tag and commit in this repository rather than only to the upstream revision on which the fork is based.

## Required source contents

The corresponding source should include, as applicable:

- Python source under `srunpy/`;
- local HTML, CSS, JavaScript, fonts, icons, and other required interface assets;
- `pyproject.toml`, `MANIFEST.in`, packaging definitions, and build scripts;
- tests and configuration needed to validate or rebuild the release;
- `LICENSE`, `README.md`, and `THIRD_PARTY_NOTICES.md`;
- any modifications to bundled libraries that are needed to reproduce the executable.

Generated binaries, caches, credentials, traffic databases, private signing keys, and the local `参考ui/` design reference are not corresponding source and must not be published as source inputs.

## Distributor responsibilities

Anyone redistributing a binary is responsible for ensuring that recipients can obtain its exact corresponding source under GPL-3.0-only using one of the methods permitted by the license. Keep the source available for the period required by the selected distribution method. A temporary branch, an untagged working tree, or a link that can disappear without preserving the released revision is not a reliable release process.

This document describes the intended release process and does not replace the terms in `LICENSE`.
