import os
import pathlib
import re
import stat
import subprocess


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _write_executable(path: pathlib.Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _parse_key_value_output(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def test_runtime_architecture_detection_matches_packaging_architectures() -> None:
    source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    for architecture in (
        "arm64ec",
        "x64",
        "x86",
        "arm64",
        "armv7",
        "armv6",
        "arm",
        "riscv64",
        "riscv32",
        "loongarch64",
        "loongarch32",
        "ppc64le",
        "ppc64",
        "ppc",
        "mips64",
        "mips",
        "s390x",
        "s390",
    ):
        assert f'return "{architecture}";' in source


def test_runtime_base_path_has_generic_posix_fallback() -> None:
    source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    assert "if (progPath.empty())" in source
    assert "std::filesystem::current_path()" in source


def test_runtime_uses_native_user_data_paths_per_platform() -> None:
    source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    assert 'Library/Application Support' in source
    assert 'XDG_DATA_HOME' in source
    assert '.local/share' in source
    assert 'Could not determine home directory for macOS user data path' in source
    assert 'Could not determine home directory for user data path' in source
    assert 'if (pw && pw->pw_dir && *pw->pw_dir)' in source
    assert 'std::make_tuple(std::optional<std::filesystem::path>{}' in source


def test_linux_vasprintf_results_are_checked() -> None:
    sys_source = (REPO_ROOT / "engine/system" / "win" / "sys_main.cpp").read_text(encoding="utf-8")
    console_source = (REPO_ROOT / "engine" / "common" / "console.cpp").read_text(encoding="utf-8")

    assert "int msgLen = vasprintf(&msg, fmt, va)" in sys_source
    assert "msgLen >= 0 && msg" in sys_source
    assert "int textLen = vasprintf(&text, fmt, va)" in console_source
    assert "textLen >= 0 && text" in console_source
    assert "int cmdLen = vasprintf(&cmd, fmt, va)" in console_source
    assert "cmdLen >= 0 && cmd" in console_source


def test_console_threads_are_joined_with_atomic_shutdown_flags() -> None:
    header_source = (REPO_ROOT / "engine/system/sys_main.h").read_text(encoding="utf-8")
    sys_source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    assert "std::thread _thread;" in header_source
    assert "void\tThreadJoin();" in header_source
    assert "_thread = std::thread(statThreadProc, this);" in sys_source
    assert "_thread.join();" in sys_source
    assert ".detach()" not in sys_source

    for path in (
        REPO_ROOT / "engine/system/win/sys_console.cpp",
        REPO_ROOT / "engine/system/win/sys_console_unix.cpp",
        REPO_ROOT / "ui_debug.cpp",
    ):
        source = path.read_text(encoding="utf-8")
        assert "#include <atomic>" in source
        assert "std::atomic_bool doRun" in source
        assert "std::atomic_bool isRunning" in source
        assert "ThreadJoin();" in source
        assert "volatile bool doRun" not in source
        assert "volatile bool isRunning" not in source


def test_posix_process_launch_detaches_without_leaving_launcher_zombies() -> None:
    source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    assert "WaitForDetachedLauncher" in source
    assert "waitpid(pid, &status, 0)" in source
    assert "errno != EINTR" in source
    assert "setsid() == -1" in source
    assert "pid_t child = fork()" in source
    assert "_exit(child < 0 ? 127 : 0)" in source
    assert 'execl("/bin/sh", "sh", "-c", command.c_str(), (char*)nullptr)' in source


def test_posix_open_url_uses_generic_launcher_override() -> None:
    source = (REPO_ROOT / "engine/system/win/sys_main.cpp").read_text(encoding="utf-8")

    assert 'getenv("SIMPLEGRAPHIC_OPEN_URL_COMMAND")' in source
    assert 'urlLauncher = "xdg-open"' in source
    assert "execlp(urlLauncher, urlLauncher, url, (char*)nullptr)" in source
    assert 'fmt::format("Could not launch {}.", urlLauncher)' in source
    assert "#elif defined(__APPLE__) && defined(__MACH__)" in source
    assert "const char* PlatformOpenURL(const char* url);" in source


def test_package_script_accepts_future_macos_architecture_spelling() -> None:
    source = (REPO_ROOT / "scripts/package-runtime.sh").read_text(encoding="utf-8")

    assert 'SIMPLEGRAPHIC_CMAKE_OSX_ARCHITECTURES' in source
    assert 'printf \'%s\' "$1"' in source


def test_package_script_can_describe_future_platform_runtime_file_names() -> None:
    source = (REPO_ROOT / "scripts/package-runtime.sh").read_text(encoding="utf-8")

    for variable in (
        "SIMPLEGRAPHIC_ENTRY_LIBRARY",
        "SIMPLEGRAPHIC_LUA_MODULE_EXT",
        "SIMPLEGRAPHIC_LCURL_MODULE",
        "SIMPLEGRAPHIC_LUA_UTF8_MODULE",
        "SIMPLEGRAPHIC_SOCKET_MODULE",
        "SIMPLEGRAPHIC_LZIP_MODULE",
    ):
        assert variable in source

    assert 'require_safe_file_name "$runtime_entry_library"' in source
    assert "SIMPLEGRAPHIC_MANIFEST_ENTRY_LIBRARY" in source
    assert '"entryLibrary": os.environ["SIMPLEGRAPHIC_MANIFEST_ENTRY_LIBRARY"]' in source
    assert '"files": files' in source


def test_package_script_manifest_lists_expected_lua_modules_once() -> None:
    source = (REPO_ROOT / "scripts/package-runtime.sh").read_text(encoding="utf-8")

    for variable in (
        "SIMPLEGRAPHIC_MANIFEST_LCURL_MODULE",
        "SIMPLEGRAPHIC_MANIFEST_LUA_UTF8_MODULE",
        "SIMPLEGRAPHIC_MANIFEST_SOCKET_MODULE",
        "SIMPLEGRAPHIC_MANIFEST_LZIP_MODULE",
    ):
        assert variable in source
    assert '"luaModules": [' in source
    assert 'os.environ["SIMPLEGRAPHIC_MANIFEST_LCURL_MODULE"]' in source


def test_package_script_uses_host_runnable_vcpkg_binary() -> None:
    source = (REPO_ROOT / "scripts/package-runtime.sh").read_text(encoding="utf-8")

    assert "SIMPLEGRAPHIC_VCPKG_ROOT" in source
    assert "windows_path()" in source
    assert "cygpath -w" in source
    assert 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(windows_path "$vcpkg_root/scripts/bootstrap.ps1")" -disableMetrics' in source
    assert 'cmd.exe /d /c call "$(windows_path "$vcpkg_root/bootstrap-vcpkg.bat")" -disableMetrics' in source
    assert "vcpkg_binary_is_usable()" in source
    assert '[ -f "$candidate" ] || return 1' in source
    assert 'if [ "$host_platform" != "win32" ]; then' in source
    assert '"$candidate" version >/dev/null 2>&1' in source
    assert "-DCMAKE_TOOLCHAIN_FILE=\"$vcpkg_root/scripts/buildsystems/vcpkg.cmake\"" in source
    assert "vcpkg bootstrap did not produce a runnable host binary" in source


def test_package_script_auto_detects_latest_windows_visual_studio_generator(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cmake_calls = tmp_path / "cmake.log"
    vcpkg_root = tmp_path / "vcpkg"
    vcpkg_root.mkdir()
    _write_executable(
        vcpkg_root / "vcpkg.exe",
        "#!/bin/sh\n"
        "printf 'fake vcpkg\\n'\n",
    )
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'AMD64\\n'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "cmake",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-E\" ] && [ \"${2:-}\" = \"capabilities\" ]; then\n"
        "  cat <<'JSON'\n"
        "{\"generators\":[{\"name\":\"Visual Studio 17 2022\"},{\"name\":\"Visual Studio 18 2026\"},{\"name\":\"Ninja\"}]}\n"
        "JSON\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" > {cmake_calls}\n"
        "exit 1\n",
    )
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "win32-x64"
    env["SIMPLEGRAPHIC_CMAKE_GENERATOR"] = "auto"
    env["SIMPLEGRAPHIC_CMAKE_PLATFORM"] = "x64"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Using CMake generator Visual Studio 18 2026" in result.stdout
    assert "-G Visual Studio 18 2026 -A x64" in cmake_calls.read_text(encoding="utf-8")


def test_package_script_auto_uses_installed_visual_studio_from_vswhere(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cmake_calls = tmp_path / "cmake.log"
    vcpkg_root = tmp_path / "vcpkg"
    vcpkg_root.mkdir()
    _write_executable(
        vcpkg_root / "vcpkg.exe",
        "#!/bin/sh\n"
        "printf 'fake vcpkg\\n'\n",
    )
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'ARM64\\n'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "vswhere.exe",
        "#!/bin/sh\n"
        "printf '17.13.36514.2\\n'\n",
    )
    _write_executable(
        bin_dir / "cmake",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-E\" ] && [ \"${2:-}\" = \"capabilities\" ]; then\n"
        "  cat <<'JSON'\n"
        "{\"generators\":[{\"name\":\"Visual Studio 17 2022\"},{\"name\":\"Visual Studio 18 2026\"},{\"name\":\"Ninja\"}]}\n"
        "JSON\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" > {cmake_calls}\n"
        "exit 1\n",
    )
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "win32-arm64"
    env["SIMPLEGRAPHIC_CMAKE_GENERATOR"] = "auto"
    env["SIMPLEGRAPHIC_CMAKE_PLATFORM"] = "ARM64"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Using CMake generator Visual Studio 17 2022" in result.stdout
    assert "-G Visual Studio 17 2022 -A ARM64" in cmake_calls.read_text(encoding="utf-8")


def test_package_script_clears_mounted_install_directory_contents() -> None:
    source = (REPO_ROOT / "scripts/package-runtime.sh").read_text(encoding="utf-8")

    assert "reset_directory_contents()" in source
    assert 'mkdir -p "$directory"' in source
    assert 'find "$directory" -mindepth 1 -maxdepth 1 -exec rm -rf {} +' in source
    assert 'reset_directory_contents "$install_dir"' in source
    assert 'rm -rf "$install_dir"' not in source


def test_package_script_rejects_dot_prefixed_target_components(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'x86_64\\n'\n"
        "fi\n",
    )
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "win32-.hidden"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unsafe runtime target component: .hidden" in result.stderr


def test_package_script_rejects_multi_hyphen_target_alias(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'x86_64\\n'\n"
        "fi\n",
    )
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "linux-gnu-x64"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "SIMPLEGRAPHIC_RUNTIME_TARGET must be a two-part" in result.stderr


def test_package_script_normalizes_armhf_to_armv7_target(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'x86_64\\n'\n"
        "fi\n",
    )
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "linux-armhf"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "no default vcpkg triplet for linux-armv7" in result.stderr


def test_package_script_accepts_architecture_first_target_alias(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'x86_64\\n'\n"
        "fi\n",
    )
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nexit 1\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 0\n")
    vcpkg_root = tmp_path / "vcpkg"
    vcpkg_root.mkdir()
    _write_executable(vcpkg_root / "vcpkg", "#!/bin/sh\nprintf 'fake vcpkg\\n'\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "amd64-linux"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Packaging SimpleGraphic runtime linux-x64 with vcpkg triplet x64-linux-dynamic" in result.stdout


def test_package_script_bootstraps_vcpkg_with_windows_powershell_path(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    vcpkg_root = tmp_path / "vcpkg"
    vcpkg_root.mkdir()
    (vcpkg_root / "scripts").mkdir()
    (vcpkg_root / "scripts" / "bootstrap.ps1").write_text("", encoding="utf-8")
    (vcpkg_root / "bootstrap-vcpkg.bat").write_text("@echo off\n", encoding="utf-8")
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'AMD64\\n'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "cygpath",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-w\" ]; then\n"
        "  shift\n"
        "fi\n"
        "case \"$1\" in\n"
        "  */scripts/bootstrap.ps1) printf 'C:\\\\repo\\\\vcpkg\\\\scripts\\\\bootstrap.ps1\\n' ;;\n"
        "  *) printf 'C:\\\\repo\\\\vcpkg\\\\bootstrap-vcpkg.bat\\n' ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "powershell.exe",
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" > {calls}\n"
        f"cat > {vcpkg_root / 'vcpkg.exe'} <<'EOF'\n"
        "#!/bin/sh\n"
        "printf 'fake vcpkg\\n'\n"
        "EOF\n"
        f"chmod +x {vcpkg_root / 'vcpkg.exe'}\n",
    )
    _write_executable(
        bin_dir / "cmake",
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  --build|--install) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 1\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "win32-x64"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert calls.read_text(encoding="utf-8").strip() == (
        "-NoProfile -ExecutionPolicy Bypass -File "
        "C:\\repo\\vcpkg\\scripts\\bootstrap.ps1 -disableMetrics"
    )
    assert "expected runtime file is missing: SimpleGraphic.dll" in result.stderr


def test_package_script_bootstraps_vcpkg_with_windows_cmd_fallback(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    vcpkg_root = tmp_path / "vcpkg"
    vcpkg_root.mkdir()
    (vcpkg_root / "bootstrap-vcpkg.bat").write_text("@echo off\n", encoding="utf-8")
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'AMD64\\n'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "cygpath",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-w\" ]; then\n"
        "  shift\n"
        "fi\n"
        "printf 'C:\\\\repo\\\\vcpkg\\\\bootstrap-vcpkg.bat\\n'\n",
    )
    _write_executable(
        bin_dir / "cmd.exe",
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" > {calls}\n"
        f"cat > {vcpkg_root / 'vcpkg.exe'} <<'EOF'\n"
        "#!/bin/sh\n"
        "printf 'fake vcpkg\\n'\n"
        "EOF\n"
        f"chmod +x {vcpkg_root / 'vcpkg.exe'}\n",
    )
    _write_executable(
        bin_dir / "cmake",
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  --build|--install) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(bin_dir / "tar", "#!/bin/sh\nexit 1\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "win32-x64"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert calls.read_text(encoding="utf-8").strip() == "/d /c call C:\\repo\\vcpkg\\bootstrap-vcpkg.bat -disableMetrics"
    assert "expected runtime file is missing: SimpleGraphic.dll" in result.stderr


def test_package_script_writes_windows_manifest_and_legacy_archive(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    install_dir = tmp_path / "install"
    archive_dir = tmp_path / "archives"
    vcpkg_root = tmp_path / "vcpkg"
    install_dir.mkdir()
    (install_dir / "stale.dll").write_text("old dll\n", encoding="utf-8")
    (install_dir / "stale.txt").write_text("old file\n", encoding="utf-8")
    stale_dir = install_dir / "stale-dir"
    stale_dir.mkdir()
    (stale_dir / "nested.txt").write_text("old nested file\n", encoding="utf-8")
    vcpkg_root.mkdir()
    _write_executable(
        vcpkg_root / "vcpkg.exe",
        "#!/bin/sh\n"
        "printf 'fake vcpkg\\n'\n",
    )
    _write_executable(
        bin_dir / "uname",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-s\" ]; then\n"
        "  printf 'MINGW64_NT-10.0\\n'\n"
        "else\n"
        "  printf 'AMD64\\n'\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "cmake",
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--install\" ]; then\n"
        "  mkdir -p \"$SIMPLEGRAPHIC_INSTALL_DIR\"\n"
        "  for file in SimpleGraphic.dll lcurl.dll lua-utf8.dll socket.dll lzip.dll zlib1.dll lua51.dll; do\n"
        "    printf 'fake %s\\n' \"$file\" > \"$SIMPLEGRAPHIC_INSTALL_DIR/$file\"\n"
        "  done\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "tar",
        "#!/bin/sh\n"
        f"printf 'tar %s\\n' \"$*\" >> {calls}\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-cvf\" ]; then\n"
        "    shift\n"
        "    archive=\"$1\"\n"
        "    if [ \"$archive\" = \"-\" ]; then\n"
        "      printf 'fake archive\\n'\n"
        "    else\n"
        "      mkdir -p \"$(dirname \"$archive\")\"\n"
        "      printf 'fake archive\\n' > \"$archive\"\n"
        "    fi\n"
        "    exit 0\n"
        "  fi\n"
        "  shift || true\n"
        "done\n"
        "exit 1\n",
    )
    _write_executable(
        bin_dir / "python3",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-\" ]; then\n"
        "  cat > \"$2\" <<EOF\n"
        "{\n"
        "  \"architecture\": \"${SIMPLEGRAPHIC_MANIFEST_ARCHITECTURE}\",\n"
        "  \"buildType\": \"${SIMPLEGRAPHIC_MANIFEST_BUILD_TYPE}\",\n"
        "  \"entryLibrary\": \"${SIMPLEGRAPHIC_MANIFEST_ENTRY_LIBRARY}\",\n"
        "  \"entrypoints\": [\"RunLuaFileAsWin\", \"RunLuaFileAsConsole\"],\n"
        "  \"files\": [\"SimpleGraphic.dll\", \"SimpleGraphicRuntime.json\", \"lcurl.dll\", \"lua-utf8.dll\", \"lua51.dll\", \"lzip.dll\", \"socket.dll\", \"zlib1.dll\"],\n"
        "  \"layout\": \"flat\",\n"
        "  \"luaModules\": [\"${SIMPLEGRAPHIC_MANIFEST_LCURL_MODULE}\", \"${SIMPLEGRAPHIC_MANIFEST_LUA_UTF8_MODULE}\", \"${SIMPLEGRAPHIC_MANIFEST_SOCKET_MODULE}\", \"${SIMPLEGRAPHIC_MANIFEST_LZIP_MODULE}\"],\n"
        "  \"name\": \"SimpleGraphic\",\n"
        "  \"platform\": \"${SIMPLEGRAPHIC_MANIFEST_PLATFORM}\",\n"
        "  \"schemaVersion\": 1,\n"
        "  \"target\": \"${SIMPLEGRAPHIC_MANIFEST_TARGET}\"\n"
        "}\n"
        "EOF\n"
        "  exit 0\n"
        "fi\n"
        "case \"$1\" in\n"
        "  */verify-runtime-archive.py) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "amd64-windows"
    env["SIMPLEGRAPHIC_VCPKG_ROOT"] = str(vcpkg_root)
    env["SIMPLEGRAPHIC_INSTALL_DIR"] = str(install_dir)
    env["SIMPLEGRAPHIC_ARCHIVE_DIR"] = str(archive_dir)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = (install_dir / "SimpleGraphicRuntime.json").read_text(encoding="utf-8")
    tar_calls = calls.read_text(encoding="utf-8")
    assert '"target": "win32-x64"' in manifest
    assert '"platform": "win32"' in manifest
    assert '"architecture": "x64"' in manifest
    assert '"entryLibrary": "SimpleGraphic.dll"' in manifest
    assert '"lcurl.dll"' in manifest
    assert '"lua-utf8.dll"' in manifest
    assert '"socket.dll"' in manifest
    assert '"lzip.dll"' in manifest
    assert '"files"' in manifest
    assert '"zlib1.dll"' in manifest
    assert '"lua51.dll"' in manifest
    assert not (install_dir / "stale.dll").exists()
    assert not (install_dir / "stale.txt").exists()
    assert not stale_dir.exists()
    assert (archive_dir / "SimpleGraphicRuntime-win32-x64.tar").is_file()
    assert (archive_dir / "SimpleGraphicDLLs-x64-windows.tar").is_file()
    assert "tar -cvf - ." in tar_calls
    assert "tar -cvf - ./SimpleGraphic.dll" in tar_calls
    assert "./SimpleGraphic.dll" in tar_calls
    assert "./lcurl.dll" in tar_calls
    assert "./lua-utf8.dll" in tar_calls
    assert "./socket.dll" in tar_calls
    assert "./lzip.dll" in tar_calls
    assert "stale.dll" not in tar_calls
    assert "Wrote" in result.stdout


def test_package_script_dry_run_describes_windows_alias_without_build_tools(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nprintf 'cmake should not run\\n' >&2\nexit 44\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nprintf 'tar should not run\\n' >&2\nexit 45\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_DRY_RUN"] = "1"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "amd64-windows"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    config = _parse_key_value_output(result.stdout)
    assert result.stderr == ""
    assert config["runtime_target"] == "win32-x64"
    assert config["runtime_platform"] == "win32"
    assert config["runtime_architecture"] == "x64"
    assert config["triplet"] == "x64-windows-release"
    assert config["entry_library"] == "SimpleGraphic.dll"
    assert config["lua_modules"] == "lcurl.dll,lua-utf8.dll,socket.dll,lzip.dll"
    assert config["archive"].endswith("/SimpleGraphicRuntime-win32-x64.tar")


def test_package_script_dry_run_describes_future_target_with_explicit_triplet(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nprintf 'cmake should not run\\n' >&2\nexit 44\n")
    _write_executable(bin_dir / "tar", "#!/bin/sh\nprintf 'tar should not run\\n' >&2\nexit 45\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_DRY_RUN"] = "true"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "linux-riscv64"
    env["SIMPLEGRAPHIC_VCPKG_TRIPLET"] = "riscv64-linux-dynamic"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    config = _parse_key_value_output(result.stdout)
    assert result.stderr == ""
    assert config["runtime_target"] == "linux-riscv64"
    assert config["runtime_platform"] == "linux"
    assert config["runtime_architecture"] == "riscv64"
    assert config["triplet"] == "riscv64-linux-dynamic"
    assert config["entry_library"] == "libSimpleGraphic.so"
    assert config["lua_modules"] == "lcurl.so,lua-utf8.so,socket.so,lzip.so"


def test_package_script_dry_run_describes_cmake_generator_settings(tmp_path) -> None:
    env = os.environ.copy()
    env["SIMPLEGRAPHIC_DRY_RUN"] = "on"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "arm64-windows"
    env["SIMPLEGRAPHIC_CMAKE_GENERATOR"] = "Visual Studio 17 2022"
    env["SIMPLEGRAPHIC_CMAKE_PLATFORM"] = "ARM64"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    config = _parse_key_value_output(result.stdout)
    assert config["runtime_target"] == "win32-arm64"
    assert config["triplet"] == "arm64-windows"
    assert config["generator"] == "Visual Studio 17 2022"
    assert config["cmake_platform"] == "ARM64"


def test_package_script_dry_run_still_rejects_unsafe_targets(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "cmake", "#!/bin/sh\nprintf 'cmake should not run\\n' >&2\nexit 44\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SIMPLEGRAPHIC_DRY_RUN"] = "1"
    env["SIMPLEGRAPHIC_RUNTIME_TARGET"] = "linux-gnu-x64"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "package-runtime.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "SIMPLEGRAPHIC_RUNTIME_TARGET must be a two-part" in result.stderr
    assert "cmake should not run" not in result.stderr


def test_lzip_checks_short_archive_reads() -> None:
    source = (REPO_ROOT / "libs/LZip/lzip.cpp").read_text(encoding="utf-8")

    assert "rd = fread(ibuf + remin, 1, rd, i->f)" in source
    assert "if (fread(fname, 1, lh.szName, zf) != lh.szName)" in source
    assert "FreeString(fname)" in source


def test_cmake_excludes_common_system_library_locations_from_runtime_archives() -> None:
    source = (REPO_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "cmake_policy(SET CMP0207 NEW)" in source
    for pattern in (
        "[[^azureattest.*[.]dll$]]",
        "[[^hvsifiletrust[.]dll$]]",
        "[[^pdmutilities[.]dll$]]",
        "[[^wtdsensor[.]dll$]]",
        "[[^wpaxholder[.]dll$]]",
        "[[^wtdccm[.]dll$]]",
        r"[[.*[\\/]windows[\\/]system32[\\/].*]]",
        r"[[.*[\\/]windows[\\/]syswow64[\\/].*]]",
        r"[[.*[\\/]windows[\\/]winsxs[\\/].*]]",
        "[[^/System/Library/.*]]",
        "[[^/usr/lib/.*]]",
        "[[^/usr/lib64/.*]]",
        "[[^/lib/.*]]",
        "[[^/lib64/.*]]",
    ):
        assert pattern in source
