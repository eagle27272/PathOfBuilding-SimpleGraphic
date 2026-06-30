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
    assert "SimpleGraphicRuntime.json" in macos_entry["files"]
    assert "libSimpleGraphic.dylib" in macos_entry["files"]
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
        "files": ["SimpleGraphicRuntime.json"],
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
        "files": ["SimpleGraphicRuntime.json"],
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


def test_write_runtime_index_rejects_files_metadata_mismatch(tmp_path) -> None:
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
        "files": ["SimpleGraphicRuntime.json"],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (archive_root / "libSimpleGraphic.dylib").write_text("runtime", encoding="utf-8")
    archive_path = artifact_dir / "SimpleGraphicRuntime-macos-arm64.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")
        archive.add(archive_root / "libSimpleGraphic.dylib", arcname="libSimpleGraphic.dylib")

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
    assert "manifest field 'files' must match archive files" in result.stderr


def test_write_runtime_index_rejects_duplicate_files_metadata(tmp_path) -> None:
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
        "files": [
            "SimpleGraphicRuntime.json",
            "libSimpleGraphic.dylib",
            "libSimpleGraphic.dylib",
        ],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (archive_root / "libSimpleGraphic.dylib").write_text("runtime", encoding="utf-8")
    archive_path = artifact_dir / "SimpleGraphicRuntime-macos-arm64.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")
        archive.add(archive_root / "libSimpleGraphic.dylib", arcname="libSimpleGraphic.dylib")

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
    assert "manifest field 'files' contains duplicate entry 'libSimpleGraphic.dylib'" in result.stderr


def test_write_runtime_index_rejects_path_like_entry_library(tmp_path) -> None:
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
        "entryLibrary": "Frameworks/libSimpleGraphic.dylib",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest field 'entryLibrary' must be a flat file name" in result.stderr


def test_write_runtime_index_rejects_non_flat_layout(tmp_path) -> None:
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
        "layout": "bundle",
        "entryLibrary": "libSimpleGraphic.dylib",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest field 'layout' expected 'flat'" in result.stderr


def test_write_runtime_index_rejects_wrong_known_platform_entry_library(tmp_path) -> None:
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
        "entryLibrary": "SimpleGraphic.native",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": POSIX_LUA_MODULES,
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest field 'entryLibrary' expected 'libSimpleGraphic.dylib'" in result.stderr


def test_write_runtime_index_rejects_extra_manifest_entrypoint(tmp_path) -> None:
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
        "entrypoints": [*sorted(REQUIRED_ENTRYPOINTS), "RunExperimental"],
        "luaModules": POSIX_LUA_MODULES,
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest must list only entrypoints" in result.stderr


def test_write_runtime_index_rejects_duplicate_manifest_entrypoint(tmp_path) -> None:
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
        "entrypoints": [
            "RunLuaFileAsWin",
            "RunLuaFileAsConsole",
            "RunLuaFileAsConsole",
        ],
        "luaModules": POSIX_LUA_MODULES,
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest field 'entrypoints' contains duplicate entry 'RunLuaFileAsConsole'" in result.stderr


def test_write_runtime_index_rejects_wrong_known_platform_lua_modules(tmp_path) -> None:
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
        "luaModules": ["lcurl.dylib", "lua-utf8.so", "socket.so", "lzip.so"],
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "manifest must list Lua modules" in result.stderr


def test_write_runtime_index_accepts_future_platform_module_file_names(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_dir.mkdir()
    archive_root.mkdir()

    modules = ["lcurl.native", "lua-utf8.native", "socket.native", "lzip.native"]
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": "freebsd-riscv64",
        "platform": "freebsd",
        "architecture": "riscv64",
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "SimpleGraphic.native",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": modules,
        "files": [
            "SimpleGraphicRuntime.json",
            "SimpleGraphic.native",
            *modules,
        ],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (archive_root / "SimpleGraphic.native").write_text("runtime", encoding="utf-8")
    for module in modules:
        (archive_root / module).write_text("module", encoding="utf-8")
    archive_path = artifact_dir / "SimpleGraphicRuntime-freebsd-riscv64.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)

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

    assert result.returncode == 0, result.stderr
    index = json.loads(result.stdout)
    entry = index["runtimeArchives"][0]
    assert entry["target"] == "freebsd-riscv64"
    assert entry["entryLibrary"] == "SimpleGraphic.native"
    assert entry["luaModules"] == modules


def test_write_runtime_index_rejects_future_platform_wrong_lua_module_basenames(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_dir.mkdir()
    archive_root.mkdir()

    modules = ["lcurl.native", "lua-utf8.native", "socket.native", "socket.alt"]
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": "freebsd-riscv64",
        "platform": "freebsd",
        "architecture": "riscv64",
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "SimpleGraphic.native",
        "entrypoints": sorted(REQUIRED_ENTRYPOINTS),
        "luaModules": modules,
        "files": [
            "SimpleGraphicRuntime.json",
            "SimpleGraphic.native",
            *modules,
        ],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (archive_root / "SimpleGraphic.native").write_text("runtime", encoding="utf-8")
    for module in modules:
        (archive_root / module).write_text("module", encoding="utf-8")
    archive_path = artifact_dir / "SimpleGraphicRuntime-freebsd-riscv64.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)

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
    assert "duplicate module base names ['socket']" in result.stderr


def test_write_runtime_index_rejects_missing_declared_runtime_files(tmp_path) -> None:
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
        "files": ["SimpleGraphicRuntime.json"],
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
    assert "is missing required regular files" in result.stderr


def test_write_runtime_index_rejects_required_symlink_runtime_files(tmp_path) -> None:
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
        "files": [
            "SimpleGraphicRuntime.json",
            "libSimpleGraphic.dylib",
            *POSIX_LUA_MODULES,
        ],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    for module in POSIX_LUA_MODULES:
        (archive_root / module).write_text("module", encoding="utf-8")
    archive_path = artifact_dir / "SimpleGraphicRuntime-macos-arm64.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(archive_root / "SimpleGraphicRuntime.json", arcname="SimpleGraphicRuntime.json")
        link = tarfile.TarInfo("libSimpleGraphic.dylib")
        link.type = tarfile.SYMTYPE
        link.linkname = "libSimpleGraphic.real.dylib"
        archive.addfile(link)
        for module in POSIX_LUA_MODULES:
            archive.add(archive_root / module, arcname=module)

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
    assert "is missing required regular files: libSimpleGraphic.dylib" in result.stderr


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
        "files": [
            "SimpleGraphicRuntime.json",
            "libSimpleGraphic.dylib",
            *POSIX_LUA_MODULES,
        ],
    }
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (archive_root / "libSimpleGraphic.dylib").write_text("runtime", encoding="utf-8")
    for module in POSIX_LUA_MODULES:
        (archive_root / module).write_text("module", encoding="utf-8")
    for archive_name in (
        "SimpleGraphicRuntime-macos-arm64.tar",
        "SimpleGraphicRuntime-macos-arm64.tgz",
    ):
        with tarfile.open(artifact_dir / archive_name, "w") as archive:
            for path in archive_root.iterdir():
                archive.add(path, arcname=path.name)

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
