import hashlib
import json
import pathlib
import subprocess
import sys
import tarfile

from test_verify_runtime_archive import (
    POSIX_LUA_MODULES,
    REQUIRED_ENTRYPOINTS,
    make_linux_runtime_archive,
    make_macos_runtime_archive,
)


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_legacy_windows_archive(path: pathlib.Path) -> None:
    dll = path.parent / "SimpleGraphic.dll"
    dll.write_text("legacy runtime\n", encoding="utf-8")
    with tarfile.open(path, "w") as archive:
        archive.add(dll, arcname=dll.name)


def _workspace(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    path = tmp_path / name
    path.mkdir()
    return path


def test_write_runtime_index_records_release_archive_contract(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    macos_archive = make_macos_runtime_archive(
        _workspace(tmp_path, "macos"),
        ["@rpath/libdep.dylib"],
        architecture="arm64",
        cpu_type=0x0100000C,
    )
    linux_archive = make_linux_runtime_archive(
        _workspace(tmp_path, "linux"),
        architecture="x64",
        machine=62,
    )
    macos_target = artifact_dir / macos_archive.name
    linux_target = artifact_dir / linux_archive.name
    macos_archive.rename(macos_target)
    linux_archive.rename(linux_target)

    legacy_archive = artifact_dir / "SimpleGraphicDLLs-x64-windows.tar"
    _write_legacy_windows_archive(legacy_archive)

    index_path = artifact_dir / "SimpleGraphicRuntime-index.json"
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "write-runtime-index.py"),
            "--artifact-dir",
            str(artifact_dir),
            "--output",
            str(index_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))

    assert index["schemaVersion"] == 1
    assert index["name"] == "SimpleGraphic"
    assert [entry["target"] for entry in index["runtimeArchives"]] == [
        "linux-x64",
        "macos-arm64",
    ]

    macos_entry = index["runtimeArchives"][1]
    assert macos_entry["fileName"] == "SimpleGraphicRuntime-macos-arm64.tar"
    assert macos_entry["platform"] == "macos"
    assert macos_entry["architecture"] == "arm64"
    assert macos_entry["entryLibrary"] == "libSimpleGraphic.dylib"
    assert set(macos_entry["entrypoints"]) == set(REQUIRED_ENTRYPOINTS)
    assert macos_entry["luaModules"] == POSIX_LUA_MODULES
    assert macos_entry["size"] == macos_target.stat().st_size
    assert macos_entry["sha256"] == _sha256(macos_target)

    legacy_entry = index["legacyArchives"][0]
    assert legacy_entry["fileName"] == "SimpleGraphicDLLs-x64-windows.tar"
    assert legacy_entry["target"] == "win32-x64"
    assert legacy_entry["mode"] == "legacy-windows-runtime"
    assert legacy_entry["sha256"] == _sha256(legacy_archive)


def test_write_runtime_index_rejects_manifest_target_mismatch(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_dir.mkdir()
    archive_root.mkdir()

    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": "linux-x64",
        "platform": "linux",
        "architecture": "x64",
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "libSimpleGraphic.so",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    archive_path = artifact_dir / "SimpleGraphicRuntime-macos-arm64.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "write-runtime-index.py"),
            "--artifact-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "manifest field 'target' expected 'macos-arm64'" in result.stderr


def test_write_runtime_index_rejects_unsafe_archive_link(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_dir.mkdir()
    archive_root.mkdir()

    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": "macos-arm64",
        "platform": "macos",
        "architecture": "arm64",
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "libSimpleGraphic.dylib",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    archive_path = artifact_dir / "SimpleGraphicRuntime-macos-arm64.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")
        link = tarfile.TarInfo("linked")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        archive.addfile(link)

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "write-runtime-index.py"),
            "--artifact-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "contains unsafe link: linked -> ../outside" in result.stderr


def test_write_runtime_index_rejects_duplicate_runtime_target(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_dir.mkdir()
    archive_root.mkdir()

    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": "macos-arm64",
        "platform": "macos",
        "architecture": "arm64",
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "libSimpleGraphic.dylib",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    for archive_name in (
        "SimpleGraphicRuntime-macos-arm64.tar",
        "SimpleGraphicRuntime-macos-arm64.tgz",
    ):
        with tarfile.open(artifact_dir / archive_name, "w") as archive:
            archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "write-runtime-index.py"),
            "--artifact-dir",
            str(artifact_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "duplicate runtime archive target macos-arm64" in result.stderr
