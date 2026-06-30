import json
import platform as platform_module
import pathlib
import shutil
import subprocess
import sys
import tarfile

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _host_runtime_names() -> tuple[str, str, str]:
    machine = platform_module.machine().lower()
    if machine in ("x86_64", "amd64"):
        architecture = "x64"
    elif machine in ("arm64", "aarch64"):
        architecture = "arm64"
    elif machine in ("i386", "i486", "i586", "i686", "x86"):
        architecture = "x86"
    else:
        architecture = machine

    if sys.platform == "darwin":
        return "macos", architecture, "libSimpleGraphic.dylib"
    if sys.platform.startswith("linux"):
        return "linux", architecture, "libSimpleGraphic.so"
    if sys.platform == "win32":
        return "win32", "x64", "SimpleGraphic.dll"
    pytest.skip(f"runtime smoke fixture does not support {sys.platform}")


def _compile_dummy_runtime_library(path: pathlib.Path) -> None:
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("a C compiler is required for the runtime smoke fixture")

    source = path.with_suffix(".c")
    source.write_text(
        """
#include <stdio.h>
#include <string.h>
#if defined(_WIN32)
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
EXPORT int RunLuaFileAsConsole(int argc, char** argv) {
    if (argc != 1 || !argv || !argv[0]) {
        return 11;
    }
    FILE* file = fopen(argv[0], "rb");
    if (!file) {
        return 12;
    }
    char buffer[128];
    size_t length = fread(buffer, 1, sizeof(buffer) - 1, file);
    fclose(file);
    buffer[length] = '\\0';
    return strstr(buffer, "Exit()") ? 0 : 13;
}
EXPORT int RunLuaFileAsWin(int argc, char** argv) {
    return RunLuaFileAsConsole(argc, argv);
}
""",
        encoding="utf-8",
    )

    if sys.platform == "darwin":
        command = [compiler, "-dynamiclib", "-o", str(path), str(source)]
    elif sys.platform.startswith("linux"):
        command = [compiler, "-shared", "-fPIC", "-o", str(path), str(source)]
    else:
        pytest.skip(f"runtime smoke fixture does not support compiling on {sys.platform}")
    subprocess.run(command, check=True, capture_output=True, text=True)


def _write_runtime_archive(tmp_path: pathlib.Path) -> pathlib.Path:
    platform, architecture, entry_library = _host_runtime_names()
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    _compile_dummy_runtime_library(archive_root / entry_library)
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": f"{platform}-{architecture}",
        "platform": platform,
        "architecture": architecture,
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": entry_library,
        "entrypoints": ["RunLuaFileAsWin", "RunLuaFileAsConsole"],
        "luaModules": ["lcurl.so", "lua-utf8.so", "socket.so", "lzip.so"],
    }
    if platform == "win32":
        manifest["luaModules"] = ["lcurl.dll", "lua-utf8.dll", "socket.dll", "lzip.dll"]
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    archive_path = tmp_path / f"SimpleGraphicRuntime-{platform}-{architecture}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)
    return archive_path


def _write_incompatible_runtime_archive(tmp_path: pathlib.Path) -> pathlib.Path:
    platform, architecture, entry_library = _host_runtime_names()
    other_architecture = "x64" if architecture != "x64" else "arm64"
    archive_root = tmp_path / "incompatible-archive"
    archive_root.mkdir()
    (archive_root / entry_library).write_text("not loaded on incompatible host\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": f"{platform}-{other_architecture}",
        "platform": platform,
        "architecture": other_architecture,
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": entry_library,
        "entrypoints": ["RunLuaFileAsWin", "RunLuaFileAsConsole"],
        "luaModules": ["lcurl.so", "lua-utf8.so", "socket.so", "lzip.so"],
    }
    if platform == "win32":
        manifest["luaModules"] = ["lcurl.dll", "lua-utf8.dll", "socket.dll", "lzip.dll"]
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    archive_path = tmp_path / f"SimpleGraphicRuntime-{platform}-{other_architecture}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)
    return archive_path


def test_smoke_runtime_archive_invokes_console_entrypoint(tmp_path) -> None:
    archive_path = _write_runtime_archive(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "smoke-runtime-archive.py"),
            str(archive_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"Smoke-tested {archive_path.name} with RunLuaFileAsConsole" in result.stdout


def test_smoke_runtime_archive_reports_incompatible_host_before_loading(
    tmp_path,
) -> None:
    archive_path = _write_incompatible_runtime_archive(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "smoke-runtime-archive.py"),
            str(archive_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "cannot be smoke-tested on host" in result.stderr
    assert "pass --allow-incompatible-host" in result.stderr


def test_smoke_runtime_archive_can_skip_incompatible_host_when_allowed(
    tmp_path,
) -> None:
    archive_path = _write_incompatible_runtime_archive(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "smoke-runtime-archive.py"),
            "--allow-incompatible-host",
            str(archive_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"Skipped smoke execution for {archive_path.name}" in result.stdout


def test_smoke_runtime_archive_rejects_unsafe_members(tmp_path) -> None:
    archive_path = tmp_path / "SimpleGraphicRuntime-macos-arm64.tar"
    bad_file = tmp_path / "evil"
    bad_file.write_text("bad\n", encoding="utf-8")
    with tarfile.open(archive_path, "w") as archive:
        archive.add(bad_file, arcname="../evil")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "smoke-runtime-archive.py"),
            str(archive_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unsafe path in archive: ../evil" in result.stderr
