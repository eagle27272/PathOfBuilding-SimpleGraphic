import json
import os
import pathlib
import shutil
import stat
import subprocess
import tarfile

from test_verify_runtime_archive import (
    REQUIRED_ENTRYPOINTS,
    make_linux_runtime_archive,
    make_macos_runtime_archive,
    make_runtime_archive,
)


EXPECTED_ARCHIVES = (
    "SimpleGraphicRuntime-win32-x64.tar",
    "SimpleGraphicRuntime-win32-arm64.tar",
    "SimpleGraphicRuntime-linux-x64.tar",
    "SimpleGraphicRuntime-linux-arm64.tar",
    "SimpleGraphicRuntime-macos-x64.tar",
    "SimpleGraphicRuntime-macos-arm64.tar",
)


def _write_legacy_windows_archive(path: pathlib.Path) -> None:
    with tarfile.open(path, "w") as archive:
        for name in (
            "SimpleGraphic.dll",
            "lcurl.dll",
            "lua-utf8.dll",
            "socket.dll",
            "lzip.dll",
        ):
            dll = path.parent / name
            dll.write_text(f"legacy {name}\n", encoding="utf-8")
            archive.add(dll, arcname=dll.name)


def _copy_archive(source: pathlib.Path, artifact_dir: pathlib.Path) -> pathlib.Path:
    destination = artifact_dir / source.name
    shutil.copy2(source, destination)
    return destination


def _workspace(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    path = tmp_path / name
    path.mkdir()
    return path


def test_validate_runtime_artifacts_verifies_future_runtime_archives(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    script_dir = tmp_path / "repo" / "scripts"
    script_dir.mkdir(parents=True)
    validator = script_dir / "validate-runtime-artifacts.sh"
    validator.write_text(
        (repo_root / "scripts" / "validate-runtime-artifacts.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    validator.chmod(validator.stat().st_mode | stat.S_IXUSR)

    capture_path = tmp_path / "verified.txt"
    fake_verifier = script_dir / "verify-runtime-archive.py"
    fake_verifier.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import pathlib\n"
        "import sys\n"
        "pathlib.Path(os.environ['CAPTURED_ARCHIVES']).write_text(\n"
        "    '\\n'.join(pathlib.Path(arg).name for arg in sys.argv[1:]),\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    fake_verifier.chmod(fake_verifier.stat().st_mode | stat.S_IXUSR)
    fake_index_writer = script_dir / "write-runtime-index.py"
    fake_index_writer.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text('{}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_index_writer.chmod(fake_index_writer.stat().st_mode | stat.S_IXUSR)

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    for archive in EXPECTED_ARCHIVES:
        (artifact_dir / archive).write_bytes(b"placeholder")
    future_archive = "SimpleGraphicRuntime-freebsd-riscv64.tar"
    (artifact_dir / future_archive).write_bytes(b"future placeholder")
    _write_legacy_windows_archive(artifact_dir / "SimpleGraphicDLLs-x64-windows.tar")

    env = os.environ.copy()
    env["CAPTURED_ARCHIVES"] = str(capture_path)
    subprocess.run([str(validator), str(artifact_dir)], check=True, env=env)

    verified_archives = set(capture_path.read_text(encoding="utf-8").splitlines())
    assert verified_archives == {*EXPECTED_ARCHIVES, future_archive}
    assert (artifact_dir / "SimpleGraphicRuntime-index.json").is_file()


def test_validate_runtime_artifacts_accepts_real_multi_platform_archive_set(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    _copy_archive(
        make_runtime_archive(
            _workspace(tmp_path, "win32-x64"),
            REQUIRED_ENTRYPOINTS,
            architecture="x64",
            machine=0x8664,
        ),
        artifact_dir,
    )
    _copy_archive(
        make_runtime_archive(
            _workspace(tmp_path, "win32-arm64"),
            REQUIRED_ENTRYPOINTS,
            architecture="arm64",
            machine=0xAA64,
        ),
        artifact_dir,
    )
    _copy_archive(
        make_linux_runtime_archive(
            _workspace(tmp_path, "linux-x64"),
            architecture="x64",
            machine=62,
        ),
        artifact_dir,
    )
    _copy_archive(
        make_linux_runtime_archive(
            _workspace(tmp_path, "linux-arm64"),
            architecture="arm64",
            machine=183,
        ),
        artifact_dir,
    )
    _copy_archive(
        make_macos_runtime_archive(
            _workspace(tmp_path, "macos-x64"),
            ["@rpath/libdep.dylib"],
            architecture="x64",
            cpu_type=0x01000007,
        ),
        artifact_dir,
    )
    _copy_archive(
        make_macos_runtime_archive(
            _workspace(tmp_path, "macos-arm64"),
            ["@rpath/libdep.dylib"],
            architecture="arm64",
            cpu_type=0x0100000C,
        ),
        artifact_dir,
    )
    future_archive = make_linux_runtime_archive(
        _workspace(tmp_path, "freebsd-riscv64"),
        platform="freebsd",
        architecture="riscv64",
        machine=243,
        entry_library="SimpleGraphic.native",
        lua_modules=[
            "lcurl.native",
            "lua-utf8.native",
            "socket.native",
            "lzip.native",
        ],
    )
    _copy_archive(future_archive, artifact_dir)
    _write_legacy_windows_archive(artifact_dir / "SimpleGraphicDLLs-x64-windows.tar")

    result = subprocess.run(
        [str(repo_root / "scripts" / "validate-runtime-artifacts.sh"), str(artifact_dir)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout
    runtime_index = artifact_dir / "SimpleGraphicRuntime-index.json"
    assert runtime_index.is_file()
    index = json.loads(runtime_index.read_text(encoding="utf-8"))
    assert {entry["target"] for entry in index["runtimeArchives"]} == {
        *[archive.removeprefix("SimpleGraphicRuntime-").removesuffix(".tar") for archive in EXPECTED_ARCHIVES],
        "freebsd-riscv64",
    }
    assert index["legacyArchives"][0]["fileName"] == "SimpleGraphicDLLs-x64-windows.tar"


def test_validate_runtime_artifacts_accepts_custom_future_target_set(tmp_path) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    future_archive = make_linux_runtime_archive(
        _workspace(tmp_path, "freebsd-riscv64-only"),
        platform="freebsd",
        architecture="riscv64",
        machine=243,
        entry_library="SimpleGraphic.native",
        lua_modules=[
            "lcurl.native",
            "lua-utf8.native",
            "socket.native",
            "lzip.native",
        ],
    )
    _copy_archive(future_archive, artifact_dir)

    env = os.environ.copy()
    env["SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS"] = "freebsd-riscv64"
    env["SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE"] = "false"
    result = subprocess.run(
        [str(repo_root / "scripts" / "validate-runtime-artifacts.sh"), str(artifact_dir)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    runtime_index = artifact_dir / "SimpleGraphicRuntime-index.json"
    index = json.loads(runtime_index.read_text(encoding="utf-8"))
    assert [entry["target"] for entry in index["runtimeArchives"]] == ["freebsd-riscv64"]
    assert "legacyArchives" not in index


def test_validate_runtime_artifacts_rejects_unsafe_custom_expected_target(
    tmp_path,
) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    env = os.environ.copy()
    env["SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS"] = "../linux-x64"
    env["SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE"] = "false"
    result = subprocess.run(
        [str(repo_root / "scripts" / "validate-runtime-artifacts.sh"), str(artifact_dir)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unsafe expected runtime target" in result.stderr


def test_validate_runtime_artifacts_rejects_incomplete_legacy_windows_archive(
    tmp_path,
) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    script_dir = tmp_path / "repo" / "scripts"
    script_dir.mkdir(parents=True)
    validator = script_dir / "validate-runtime-artifacts.sh"
    validator.write_text(
        (repo_root / "scripts" / "validate-runtime-artifacts.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    validator.chmod(validator.stat().st_mode | stat.S_IXUSR)

    fake_verifier = script_dir / "verify-runtime-archive.py"
    fake_verifier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_verifier.chmod(fake_verifier.stat().st_mode | stat.S_IXUSR)

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    for archive in EXPECTED_ARCHIVES:
        (artifact_dir / archive).write_bytes(b"placeholder")
    simplegraphic_dll = artifact_dir / "SimpleGraphic.dll"
    simplegraphic_dll.write_text("legacy runtime\n", encoding="utf-8")
    with tarfile.open(artifact_dir / "SimpleGraphicDLLs-x64-windows.tar", "w") as archive:
        archive.add(simplegraphic_dll, arcname=simplegraphic_dll.name)

    result = subprocess.run(
        [str(validator), str(artifact_dir)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "legacy Windows runtime archive is missing required DLL: lcurl.dll" in result.stderr
