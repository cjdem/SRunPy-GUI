# Third-Party Notices

SRunPy is distributed under GNU GPL v3.0 only. This file records important third-party origins and dependencies; it does not replace their license texts. Each component remains governed by the license of the exact version included in a release.

## Upstream source and protocol implementation

| Component | Use | Source / notice |
| --- | --- | --- |
| cjdem/SRunPy-GUI | Current modified distribution | <https://github.com/cjdem/SRunPy-GUI>; GPL-3.0-only |
| SRunPy-GUI | Upstream application on which this modified version is based | <https://github.com/HofNature/SRunPy-GUI>; GPL-3.0-only as declared by this repository |
| SRUN-authenticator | Origin of portions of the SRun protocol implementation | <https://github.com/iskoldt-X/SRUN-authenticator>; verify and preserve the upstream license and notices for the revision from which code was taken |

The source file `srunpy/srun.py` retains its upstream modification reference. Do not remove existing authorship or license notices when redistributing the project.

## Runtime and build dependencies

The project declares the following direct dependencies in `pyproject.toml`:

- packaging
- psutil
- requests
- Pillow
- pycryptodome
- pystray
- pywebview
- pywin32
- winotify
- Nuitka (build-time)

A Windows standalone build may bundle these projects and their transitive dependencies. Before publishing a release, generate an inventory from the actual locked or installed build environment and include all license files and notices required by those exact versions. Package metadata and upstream repositories are the authoritative sources; this document intentionally does not assign a license based only on a package name.

## Fonts and visual assets

The desktop interface bundles `srunpy/html/MiSans-Medium.ttf`. Font redistribution rights are separate from the GPL license covering this program. A distributor must confirm that the applicable MiSans terms permit the intended bundling and must include any required font license or attribution. If those rights cannot be confirmed, replace the bundled font with a suitably licensed alternative before distribution.

Application icons and images must likewise be reviewed before public distribution. Do not assume that an asset is covered by the software license merely because it is stored in this repository.

## Design reference directory

The local `参考ui/` directory contains a copy of the Octopus project used only as a visual reference. Octopus declares AGPL-3.0 and is not part of SRunPy's source or release artifacts. The directory is excluded by `.gitignore`.

Do not copy or distribute Octopus source code, logos, icons, screenshots, translations, or other protected assets as part of SRunPy without separately satisfying the applicable license. General visual ideas reimplemented independently are not an instruction to copy upstream code or assets.

## Release checklist

Before distributing an installer, portable archive, wheel, or source archive:

1. Confirm the release is built from a tagged, publicly available source revision.
2. Include `LICENSE`, this file, and `SOURCE_CODE.md` in the binary distribution.
3. Produce a dependency inventory from the release build environment.
4. Include required dependency, font, and asset license texts.
5. Verify that `参考ui/`, local databases, credentials, caches, and development artifacts are absent.
6. Record material modifications and their date in the release notes.

This notice is an engineering compliance aid and not legal advice.
