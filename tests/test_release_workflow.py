import os
import pathlib
import re
import shutil
import subprocess


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main.yml"
VALIDATOR = REPO_ROOT / "scripts" / "validate-runtime-artifacts.sh"
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package-runtime.sh"

EXPECTED_RUNTIME_TARGETS = {
    "win32-x64",
    "win32-arm64",
    "linux-x64",
    "linux-arm64",
    "macos-x64",
    "macos-arm64",
}


def file_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def matrix_targets(source: str) -> set[str]:
    return set(re.findall(r"^\s+- target: ([a-z0-9._-]+)$", source, re.MULTILINE))


def validator_default_targets(source: str) -> set[str]:
    match = re.search(
        r"default_expected_targets=\(\n(?P<body>.*?)\n\)",
        source,
        re.DOTALL,
    )
    assert match is not None
    return set(re.findall(r"^\s+([a-z0-9._-]+)$", match.group("body"), re.MULTILINE))


def workflow_matrix_entries(source: str) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in source.splitlines():
        target = re.match(r"^\s+- target: ([a-z0-9._-]+)$", line)
        if target:
            current = {}
            entries[target.group(1)] = current
            continue
        if current is None:
            continue
        field = re.match(r"^\s+([a-z_]+):(?: '([^']*)'|(.*))$", line)
        if field:
            current[field.group(1)] = (field.group(2) if field.group(2) is not None else field.group(3)).strip()
    return entries


def package_script_default_triplets(source: str) -> dict[str, str]:
    match = re.search(
        r"default_triplet_for_target\(\) \{\n(?P<body>.*?)\n\}",
        source,
        re.DOTALL,
    )
    assert match is not None
    return dict(
        re.findall(
            r"^\s+([a-z0-9._-]+)\)\n\s+printf '([^']+)'",
            match.group("body"),
            re.MULTILINE,
        )
    )


def parse_key_value_output(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def test_release_workflow_builds_and_validates_the_same_runtime_targets() -> None:
    workflow_source = file_text(WORKFLOW)
    validator_source = file_text(VALIDATOR)

    assert "workflow_dispatch:" in workflow_source
    assert "-latest" not in workflow_source
    assert "runs-on: ubuntu-24.04" in workflow_source
    assert matrix_targets(workflow_source) == EXPECTED_RUNTIME_TARGETS
    assert validator_default_targets(validator_source) == EXPECTED_RUNTIME_TARGETS
    assert "SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS" in validator_source
    assert "run: scripts/validate-runtime-artifacts.sh runtime-artifacts" in workflow_source


def test_release_workflow_passes_actionlint_when_available() -> None:
    actionlint = shutil.which("actionlint")
    if not actionlint:
        return

    subprocess.run(
        [actionlint, str(WORKFLOW)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_release_workflow_matrix_matches_package_script_defaults() -> None:
    matrix = workflow_matrix_entries(file_text(WORKFLOW))
    default_triplets = package_script_default_triplets(file_text(PACKAGE_SCRIPT))

    assert set(matrix) == EXPECTED_RUNTIME_TARGETS
    assert default_triplets == {
        target: values["triplet"] for target, values in matrix.items()
    }
    assert matrix["win32-x64"]["os"] == "windows-2025"
    assert matrix["win32-x64"]["generator"] == "auto"
    assert matrix["win32-x64"]["cmake_platform"] == "x64"
    assert matrix["win32-arm64"]["os"] == "windows-11-arm"
    assert matrix["win32-arm64"]["generator"] == "auto"
    assert matrix["win32-arm64"]["cmake_platform"] == "ARM64"
    assert matrix["linux-x64"]["os"] == "ubuntu-24.04"
    assert matrix["linux-arm64"]["os"] == "ubuntu-24.04-arm"
    assert matrix["macos-x64"]["os"] == "macos-15-intel"
    assert matrix["macos-arm64"]["os"] == "macos-15"
    assert not any(values["os"].endswith("-latest") for values in matrix.values())
    for target in EXPECTED_RUNTIME_TARGETS - {"win32-x64", "win32-arm64"}:
        assert matrix[target]["generator"] == "Unix Makefiles"
        assert matrix[target]["cmake_platform"] == ""


def test_release_workflow_packages_every_matrix_target_with_runtime_script() -> None:
    source = file_text(WORKFLOW)

    for required_env in (
        "SIMPLEGRAPHIC_DRY_RUN: \"1\"",
        "SIMPLEGRAPHIC_RUNTIME_TARGET: ${{ matrix.target }}",
        "SIMPLEGRAPHIC_VCPKG_TRIPLET: ${{ matrix.triplet }}",
        "SIMPLEGRAPHIC_CMAKE_GENERATOR: ${{ matrix.generator }}",
        "SIMPLEGRAPHIC_CMAKE_PLATFORM: ${{ matrix.cmake_platform }}",
        "SIMPLEGRAPHIC_BUILD_DIR: ${{ github.workspace }}/build",
        "SIMPLEGRAPHIC_INSTALL_DIR: ${{ env.INST_DIR }}",
        "SIMPLEGRAPHIC_ARCHIVE_DIR: ${{ github.workspace }}",
    ):
        assert required_env in source

    assert "name: Show package configuration" in source
    assert "run: scripts/package-runtime.sh" in source
    assert "name: Smoke runtime entrypoint" in source
    assert 'scripts/smoke-runtime-archive.py "SimpleGraphicRuntime-${{ matrix.target }}.tar"' in source
    assert "name: SimpleGraphicRuntime-${{ matrix.target }}" in source
    assert "path: SimpleGraphicRuntime-${{ matrix.target }}.tar" in source


def test_workflow_dispatch_can_build_one_custom_runtime_target() -> None:
    source = file_text(WORKFLOW)

    for expected in (
        "runtime_target:",
        "vcpkg_triplet:",
        "runner:",
        "cmake_generator:",
        "cmake_platform:",
        "cmake_osx_architectures:",
    ):
        assert expected in source
    assert "Optional custom <platform>-<architecture> target" in source
    assert "if: ${{ github.event_name != 'workflow_dispatch' || inputs.runtime_target == '' }}" in source
    assert "build_custom_runtime:" in source
    assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.runtime_target != '' }}" in source
    assert "runs-on: ${{ inputs.runner }}" in source
    assert "SIMPLEGRAPHIC_RUNTIME_TARGET: ${{ inputs.runtime_target }}" in source
    assert "SIMPLEGRAPHIC_VCPKG_TRIPLET: ${{ inputs.vcpkg_triplet }}" in source
    assert "SIMPLEGRAPHIC_CMAKE_GENERATOR: ${{ inputs.cmake_generator }}" in source
    assert "SIMPLEGRAPHIC_CMAKE_PLATFORM: ${{ inputs.cmake_platform }}" in source
    assert "SIMPLEGRAPHIC_CMAKE_OSX_ARCHITECTURES: ${{ inputs.cmake_osx_architectures }}" in source
    assert 'SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE=0' in source
    assert 'SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS="$target"' in source
    assert "scripts/validate-runtime-artifacts.sh runtime-artifacts" in source
    assert "scripts/smoke-runtime-archive.py \"$archive\"" in source
    assert "name: SimpleGraphicRuntime-custom" in source
    assert "runtime-artifacts/SimpleGraphicRuntime-index.json" in source


def test_release_workflow_matrix_resolves_with_package_script_dry_run() -> None:
    matrix = workflow_matrix_entries(file_text(WORKFLOW))
    assert set(matrix) == EXPECTED_RUNTIME_TARGETS

    for target, values in matrix.items():
        env = os.environ.copy()
        env.update(
            {
                "SIMPLEGRAPHIC_DRY_RUN": "1",
                "SIMPLEGRAPHIC_RUNTIME_TARGET": target,
                "SIMPLEGRAPHIC_VCPKG_TRIPLET": values["triplet"],
                "SIMPLEGRAPHIC_CMAKE_GENERATOR": values["generator"],
                "SIMPLEGRAPHIC_CMAKE_PLATFORM": values["cmake_platform"],
                "SIMPLEGRAPHIC_BUILD_DIR": str(REPO_ROOT / "build"),
                "SIMPLEGRAPHIC_INSTALL_DIR": str(REPO_ROOT / "install-prefix"),
                "SIMPLEGRAPHIC_ARCHIVE_DIR": str(REPO_ROOT),
            }
        )
        result = subprocess.run(
            ["bash", str(PACKAGE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        config = parse_key_value_output(result.stdout)

        platform, architecture = target.split("-", 1)
        assert result.stderr == ""
        assert config["runtime_target"] == target
        assert config["runtime_platform"] == platform
        assert config["runtime_architecture"] == architecture
        assert config["triplet"] == values["triplet"]
        assert config["generator"] == values["generator"]
        assert config["cmake_platform"] == values["cmake_platform"]
        assert config["archive"].endswith(f"/SimpleGraphicRuntime-{target}.tar")
        if target.startswith("win32-"):
            assert config["entry_library"] == "SimpleGraphic.dll"
            assert config["lua_modules"] == "lcurl.dll,lua-utf8.dll,socket.dll,lzip.dll"
        elif target.startswith("macos-"):
            assert config["entry_library"] == "libSimpleGraphic.dylib"
            assert config["lua_modules"] == "lcurl.so,lua-utf8.so,socket.so,lzip.so"
            expected_osx_arch = "x86_64" if architecture == "x64" else architecture
            assert config["cmake_osx_architectures"] == expected_osx_arch
        else:
            assert config["entry_library"] == "libSimpleGraphic.so"
            assert config["lua_modules"] == "lcurl.so,lua-utf8.so,socket.so,lzip.so"
            assert config["cmake_osx_architectures"] == ""


def test_release_workflow_preserves_legacy_archive_and_notifies_consumers() -> None:
    source = file_text(WORKFLOW)
    validator_source = file_text(VALIDATOR)

    assert "if: ${{ matrix.target == 'win32-x64' }}" in source
    assert "SimpleGraphicDLLs-x64-windows.tar" in source
    assert "SimpleGraphicDLLs-x64-windows.tar" in validator_source
    assert 'grep -E \'(^|/)[^/]+\\.dll$\'' in validator_source
    old_owner = "PathOfBuilding" + "Community"
    assert old_owner not in source
    assert "repository: eagle27272/PathOfBuilding" in source
    assert "repository: eagle27272/PathOfBuilding-PoE2" in source
    assert "event-type: update-simple-graphic" in source
    assert '"release_repo": "${{ github.repository }}"' in source
    assert '"runtime_index": "SimpleGraphicRuntime-index.json"' in source


def test_release_workflow_validates_all_artifacts_but_only_publishes_runtime_archives() -> None:
    source = file_text(WORKFLOW)

    assert "pattern: SimpleGraphic*" in source
    assert "scripts/validate-runtime-artifacts.sh runtime-artifacts" in source
    assert "name: SimpleGraphicRuntime-index" in source
    assert "runtime-artifacts/SimpleGraphicRuntime-index.json" in source
    assert "for archive in \\" in source
    assert "release-artifacts/SimpleGraphicRuntime-*.tar \\" in source
    assert "release-artifacts/SimpleGraphicRuntime-*.tar.gz" in source
    assert "release-artifacts/SimpleGraphicRuntime-*.tgz" in source
    assert '[ -f "$archive" ] || continue' in source
    assert "gh release upload \"${{ github.event.release.tag_name }}\" \"$archive\" --clobber" in source
    assert "release-artifacts/SimpleGraphicRuntime-index.json --clobber" in source
    assert "release-artifacts/SimpleGraphicDLLs-x64-windows.tar --clobber" in source
    assert "release-artifacts/SimpleGraphicRuntime-*.tar --clobber" not in source
    assert "SimpleGraphicRuntime-${{ matrix.target }}-pdb" in source


def test_release_workflow_verifies_poe2_consumer_runtime_contract() -> None:
    source = file_text(WORKFLOW)

    assert "Checkout PathOfBuilding-PoE2 consumer verifier" in source
    assert "repository: eagle27272/PathOfBuilding-PoE2" in source
    assert "path: consumer/PathOfBuilding-PoE2" in source
    assert "Verify PathOfBuilding-PoE2 runtime contract" in source
    assert "consumer/PathOfBuilding-PoE2/scripts/verify-runtime-index.py" in source
    assert "runtime-artifacts/SimpleGraphicRuntime-index.json" in source
    assert source.index("Verify PathOfBuilding-PoE2 runtime contract") < source.index("Archive runtime index")
