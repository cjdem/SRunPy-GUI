from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
RELEASE_DOCUMENTS = (
    "LICENSE",
    "README.md",
    "SOURCE_CODE.md",
    "THIRD_PARTY_NOTICES.md",
)


def test_release_documents_exist_and_are_in_source_distribution_manifest() -> None:
    manifest_text = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    for document_name in RELEASE_DOCUMENTS:
        assert (PROJECT_ROOT / document_name).is_file()
        assert f"include {document_name}" in manifest_text


def test_windows_build_copies_release_documents_into_binary_distribution() -> None:
    build_script_text = (PROJECT_ROOT / "scripts" / "build_windows.ps1").read_text(
        encoding="utf-8"
    )

    assert "$releaseNoticeFiles" in build_script_text
    expected_standalone_directory = (
        '$standaloneDirectory = Join-Path $buildRoot "srun_client.dist"'
    )
    assert expected_standalone_directory in build_script_text
    assert '"--disable-plugin=pywebview"' in build_script_text
    assert '"--include-module=webview.platforms.winforms"' in build_script_text
    assert '"--include-module=webview.platforms.win32"' in build_script_text
    expected_copy_command = (
        "Copy-Item -Path $noticeSourcePath -Destination $standaloneDirectory"
    )
    assert expected_copy_command in build_script_text
    for document_name in RELEASE_DOCUMENTS:
        assert f'"{document_name}"' in build_script_text


def test_readme_identifies_modified_gpl_project_and_source_obligations() -> None:
    readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "二次开发/派生版本" in readme_text
    assert "GPL-3.0-only" in readme_text
    assert "THIRD_PARTY_NOTICES.md" in readme_text
    assert "SOURCE_CODE.md" in readme_text


def test_release_documents_point_to_the_maintained_fork() -> None:
    maintained_repository_url = "https://github.com/cjdem/SRunPy-GUI"
    source_code_text = (PROJECT_ROOT / "SOURCE_CODE.md").read_text(encoding="utf-8")
    project_metadata_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # The update check now lives in the Windows integration layer.
    windows_integration_text = (PROJECT_ROOT / "srunpy" / "windows_integration.py").read_text(
        encoding="utf-8"
    )
    installer_text = (PROJECT_ROOT / "packaging" / "SRunPy.iss").read_text(
        encoding="utf-8"
    )

    assert maintained_repository_url in source_code_text
    assert maintained_repository_url in project_metadata_text
    assert "api.github.com/repos/cjdem/SRunPy-GUI/releases/latest" in windows_integration_text
    assert f"AppPublisherURL={maintained_repository_url}" in installer_text
