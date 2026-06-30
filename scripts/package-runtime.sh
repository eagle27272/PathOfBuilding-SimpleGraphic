#!/usr/bin/env bash
set -euo pipefail

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

lower_value() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

runtime_system_dependencies=()

normalize_platform() {
    local value
    value="$(lower_value "$1")"
    case "$value" in
        darwin|mac|macos|osx)
            printf 'macos'
            ;;
        mingw*|msys*|cygwin*|win|win32|windows)
            printf 'win32'
            ;;
        linux*)
            printf 'linux'
            ;;
        *)
            printf '%s' "$value"
            ;;
    esac
}

normalize_architecture() {
    local value
    value="$(lower_value "$1")"
    case "$value" in
        x86_64|amd64)
            printf 'x64'
            ;;
        aarch64|arm64)
            printf 'arm64'
            ;;
        i386|i486|i586|i686|x86)
            printf 'x86'
            ;;
        armv7*|armhf)
            printf 'armv7'
            ;;
        armv6*)
            printf 'armv6'
            ;;
        armv5*|arm)
            printf 'arm'
            ;;
        ppc64el)
            printf 'ppc64le'
            ;;
        *)
            printf '%s' "$value"
            ;;
    esac
}

is_known_architecture() {
    case "$(normalize_architecture "$1")" in
        x64|x86|arm64|arm64ec|arm64x|arm|armv6|armv7|riscv32|riscv64|riscv128|ppc|ppc64|ppc64le|mips|mips64|s390|s390x|loongarch32|loongarch64|ia64)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

require_safe_component() {
    case "$1" in
        ''|.*|*-*|*[!a-z0-9._]*)
            die "unsafe runtime target component: $1"
            ;;
    esac
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

windows_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

posix_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$1"
    else
        printf '%s' "$1"
    fi
}

is_truthy() {
    case "$(lower_value "${1:-}")" in
        1|true|yes|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

detect_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf 'python3'
    elif command -v python >/dev/null 2>&1; then
        printf 'python'
    else
        die "python3 or python is required"
    fi
}

find_vswhere() {
    local candidate
    local program_files
    local program_files_x86

    program_files="$(printenv ProgramFiles 2>/dev/null || true)"
    program_files_x86="$(printenv 'ProgramFiles(x86)' 2>/dev/null || true)"
    for candidate in \
            "$program_files_x86/Microsoft Visual Studio/Installer/vswhere.exe" \
            "$program_files/Microsoft Visual Studio/Installer/vswhere.exe" \
            "/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe" \
            "/c/Program Files/Microsoft Visual Studio/Installer/vswhere.exe"; do
        [ -n "$candidate" ] || continue
        [ -f "$candidate" ] || continue
        printf '%s\n' "$candidate"
        return 0
    done
    command -v vswhere.exe 2>/dev/null || return 1
}

visual_studio_generator_for_major() {
    case "$1" in
        18)
            printf 'Visual Studio 18 2026'
            ;;
        17)
            printf 'Visual Studio 17 2022'
            ;;
        16)
            printf 'Visual Studio 16 2019'
            ;;
        15)
            printf 'Visual Studio 15 2017'
            ;;
        *)
            return 1
            ;;
    esac
}

detect_visual_studio_generator() {
    local installation_version
    local visual_studio_major
    local vswhere

    if vswhere="$(find_vswhere)"; then
        installation_version="$("$vswhere" -latest -products '*' -requires Microsoft.Component.MSBuild -property installationVersion 2>/dev/null | tr -d '\r' | head -n 1)"
        visual_studio_major="${installation_version%%.*}"
        if [ -n "$visual_studio_major" ] \
                && visual_studio_generator_for_major "$visual_studio_major"; then
            return 0
        fi
    fi

    cmake -E capabilities | "$python_cmd" -c '
import json
import re
import sys

data = json.load(sys.stdin)
generators = []
for generator in data.get("generators", []):
    name = generator.get("name", "")
    match = re.match(r"Visual Studio ([0-9]+) ", name)
    if match:
        generators.append((int(match.group(1)), name))
if not generators:
    sys.exit(1)
print(max(generators)[1])
'
}

require_python_venv() {
    local venv_dir
    venv_dir="${TMPDIR:-/tmp}/simplegraphic-venv-check.$$"
    rm -rf "$venv_dir"
    if ! "$python_cmd" -m venv "$venv_dir" >/dev/null 2>&1; then
        rm -rf "$venv_dir"
        die "Python venv support is required by vcpkg; install python3-venv or the equivalent package"
    fi
    rm -rf "$venv_dir"
}

detect_platform() {
    normalize_platform "$(uname -s)"
}

detect_architecture() {
    normalize_architecture "$(uname -m)"
}

default_triplet_for_target() {
    case "$1" in
        win32-x64)
            printf 'x64-windows-release'
            ;;
        win32-arm64)
            printf 'arm64-windows'
            ;;
        linux-x64)
            printf 'x64-linux-dynamic'
            ;;
        linux-arm64)
            printf 'arm64-linux-dynamic'
            ;;
        macos-x64)
            printf 'x64-osx-dynamic'
            ;;
        macos-arm64)
            printf 'arm64-osx-dynamic'
            ;;
        *)
            die "no default vcpkg triplet for $1; set SIMPLEGRAPHIC_VCPKG_TRIPLET"
            ;;
    esac
}

cmake_osx_architecture_for_target_architecture() {
    case "$1" in
        x64)
            printf 'x86_64'
            ;;
        arm64)
            printf 'arm64'
            ;;
        x86)
            printf 'i386'
            ;;
        *)
            printf '%s' "$1"
            ;;
    esac
}

entry_library_for_platform() {
    case "$1" in
        win32)
            printf 'SimpleGraphic.dll'
            ;;
        macos)
            printf 'libSimpleGraphic.dylib'
            ;;
        *)
            printf 'libSimpleGraphic.so'
            ;;
    esac
}

lua_module_ext_for_platform() {
    case "$1" in
        win32)
            printf '.dll'
            ;;
        *)
            printf '.so'
            ;;
    esac
}

require_safe_build_value() {
    case "$1" in
        ''|*[!A-Za-z0-9._-]*)
            die "unsafe build value: $1"
            ;;
    esac
}

require_safe_file_name() {
    case "$1" in
        ''|.|..|*[!A-Za-z0-9._+-]*)
            die "unsafe runtime file name: $1"
            ;;
    esac
}

require_runtime_file() {
    [ -f "$install_dir/$1" ] || die "expected runtime file is missing: $1"
}

reset_directory_contents() {
    local directory="$1"
    [ -n "$directory" ] || die "empty directory"
    mkdir -p "$directory"
    find "$directory" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
}

runtime_file_exists() {
    local path="$1"
    [ -f "$path" ] || [ -f "$(posix_path "$path")" ]
}

is_windows_system_dependency_name() {
    local file_name
    file_name="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"

    case "$file_name" in
        advapi32.dll|bcrypt.dll|cfgmgr32.dll|comctl32.dll|comdlg32.dll|crypt32.dll|d3d11.dll|d3d9.dll|d3dcompiler_47.dll|dbghelp.dll|dnsapi.dll|dwmapi.dll|dxgi.dll|fwpuclnt.dll|gdi32.dll|imm32.dll|iphlpapi.dll|kernel32.dll|mpr.dll|ncrypt.dll|normaliz.dll|ntdll.dll|ole32.dll|oleacc.dll|oleaut32.dll|opengl32.dll|powrprof.dll|propsys.dll|rpcrt4.dll|sechost.dll|secur32.dll|setupapi.dll|shell32.dll|shcore.dll|shlwapi.dll|user32.dll|userenv.dll|uxtheme.dll|version.dll|winhttp.dll|winmm.dll|wldap32.dll|ws2_32.dll|wtsapi32.dll)
            return 0
            ;;
    esac

    return 1
}

is_windows_packaged_dependency() {
    local file_name="$1"

    if is_windows_system_dependency_name "$file_name"; then
        return 1
    fi

    case "$file_name" in
        "$runtime_entry_library"|"$runtime_lcurl_module"|"$runtime_lua_utf8_module"|"$runtime_socket_module"|"$runtime_lzip_module")
            return 0
            ;;
    esac

    runtime_file_exists "$build_dir/$file_name" \
        || runtime_file_exists "$build_dir/$build_type/$file_name" \
        || runtime_file_exists "$vcpkg_installed_dir/$triplet/bin/$file_name"
}

prune_windows_system_runtime_files() {
    [ "$runtime_platform" = "win32" ] || return 0

    shopt -s nullglob
    local file
    local file_name
    for file in "$install_dir"/*.[dD][lL][lL]; do
        file_name="$(basename "$file")"
        if ! is_windows_packaged_dependency "$file_name"; then
            printf 'Removing Windows system runtime dependency %s\n' "$file_name"
            runtime_system_dependencies+=("$(lower_value "$file_name")")
            rm -f "$file"
        fi
    done
    shopt -u nullglob
}

write_runtime_manifest() {
    local system_dependencies

    require_runtime_file "$runtime_entry_library"
    require_runtime_file "$runtime_lcurl_module"
    require_runtime_file "$runtime_lua_utf8_module"
    require_runtime_file "$runtime_socket_module"
    require_runtime_file "$runtime_lzip_module"

    if find "$install_dir" -mindepth 1 -type d -print -quit | grep -q .; then
        die "runtime install tree must be flat: $install_dir"
    fi

    if [ "${#runtime_system_dependencies[@]}" -gt 0 ]; then
        system_dependencies="$(printf '%s\n' "${runtime_system_dependencies[@]}" | sort -u)"
    else
        system_dependencies=""
    fi

    SIMPLEGRAPHIC_MANIFEST_TARGET="$runtime_target" \
    SIMPLEGRAPHIC_MANIFEST_PLATFORM="$runtime_platform" \
    SIMPLEGRAPHIC_MANIFEST_ARCHITECTURE="$runtime_architecture" \
    SIMPLEGRAPHIC_MANIFEST_BUILD_TYPE="$build_type" \
    SIMPLEGRAPHIC_MANIFEST_ENTRY_LIBRARY="$runtime_entry_library" \
    SIMPLEGRAPHIC_MANIFEST_LCURL_MODULE="$runtime_lcurl_module" \
    SIMPLEGRAPHIC_MANIFEST_LUA_UTF8_MODULE="$runtime_lua_utf8_module" \
    SIMPLEGRAPHIC_MANIFEST_SOCKET_MODULE="$runtime_socket_module" \
    SIMPLEGRAPHIC_MANIFEST_LZIP_MODULE="$runtime_lzip_module" \
    SIMPLEGRAPHIC_MANIFEST_SYSTEM_DEPENDENCIES="$system_dependencies" \
    "$python_cmd" - "$install_dir/SimpleGraphicRuntime.json" "$install_dir" <<'PY'
import json
import os
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
install_dir = pathlib.Path(sys.argv[2])
manifest_name = manifest_path.name
files = sorted(path.name for path in install_dir.iterdir() if path.is_file())
if manifest_name not in files:
    files.append(manifest_name)
files = sorted(set(files))
system_dependencies = sorted({
    dependency.strip().lower()
    for dependency in os.environ["SIMPLEGRAPHIC_MANIFEST_SYSTEM_DEPENDENCIES"].splitlines()
    if dependency.strip()
})
manifest = {
    "schemaVersion": 1,
    "name": "SimpleGraphic",
    "target": os.environ["SIMPLEGRAPHIC_MANIFEST_TARGET"],
    "platform": os.environ["SIMPLEGRAPHIC_MANIFEST_PLATFORM"],
    "architecture": os.environ["SIMPLEGRAPHIC_MANIFEST_ARCHITECTURE"],
    "buildType": os.environ["SIMPLEGRAPHIC_MANIFEST_BUILD_TYPE"],
    "layout": "flat",
    "entryLibrary": os.environ["SIMPLEGRAPHIC_MANIFEST_ENTRY_LIBRARY"],
    "entrypoints": [
        "RunLuaFileAsWin",
        "RunLuaFileAsConsole",
    ],
    "luaModules": [
        os.environ["SIMPLEGRAPHIC_MANIFEST_LCURL_MODULE"],
        os.environ["SIMPLEGRAPHIC_MANIFEST_LUA_UTF8_MODULE"],
        os.environ["SIMPLEGRAPHIC_MANIFEST_SOCKET_MODULE"],
        os.environ["SIMPLEGRAPHIC_MANIFEST_LZIP_MODULE"],
    ],
    "files": files,
}
if system_dependencies:
    manifest["systemDependencies"] = system_dependencies
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

print_package_config() {
    printf 'runtime_target=%s\n' "$runtime_target"
    printf 'runtime_platform=%s\n' "$runtime_platform"
    printf 'runtime_architecture=%s\n' "$runtime_architecture"
    printf 'triplet=%s\n' "$triplet"
    printf 'build_type=%s\n' "$build_type"
    printf 'build_dir=%s\n' "$build_dir"
    printf 'install_dir=%s\n' "$install_dir"
    printf 'archive_dir=%s\n' "$archive_dir"
    printf 'archive=%s\n' "$runtime_archive"
    printf 'entry_library=%s\n' "$runtime_entry_library"
    printf 'lua_modules=%s,%s,%s,%s\n' \
        "$runtime_lcurl_module" \
        "$runtime_lua_utf8_module" \
        "$runtime_socket_module" \
        "$runtime_lzip_module"
    printf 'vcpkg_root=%s\n' "$vcpkg_root"
    printf 'generator=%s\n' "$generator"
    printf 'cmake_platform=%s\n' "$cmake_platform"
    printf 'cmake_osx_architectures=%s\n' "$resolved_cmake_osx_architectures"
    printf 'vcpkg_installed_dir=%s\n' "$vcpkg_installed_dir"
}

vcpkg_binary_is_usable() {
    local candidate="$1"
    [ -f "$candidate" ] || return 1
    if [ "$host_platform" != "win32" ]; then
        [ -x "$candidate" ] || return 1
    fi
    "$candidate" version >/dev/null 2>&1
}

bootstrap_vcpkg() {
    if vcpkg_binary_is_usable "$vcpkg_root/vcpkg" \
            || vcpkg_binary_is_usable "$vcpkg_root/vcpkg.exe"; then
        return
    fi

    [ -d "$vcpkg_root" ] || die "vcpkg root does not exist: $vcpkg_root"
    if [ "$host_platform" = "win32" ]; then
        if command -v powershell.exe >/dev/null 2>&1; then
            powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(windows_path "$vcpkg_root/scripts/bootstrap.ps1")" -disableMetrics
        elif command -v cmd.exe >/dev/null 2>&1; then
            cmd.exe /d /c call "$(windows_path "$vcpkg_root/bootstrap-vcpkg.bat")" -disableMetrics
        else
            die "powershell.exe or cmd.exe is required to bootstrap vcpkg on Windows"
        fi
    else
        "$vcpkg_root/bootstrap-vcpkg.sh"
    fi

    if ! vcpkg_binary_is_usable "$vcpkg_root/vcpkg" \
            && ! vcpkg_binary_is_usable "$vcpkg_root/vcpkg.exe"; then
        die "vcpkg bootstrap did not produce a runnable host binary in $vcpkg_root"
    fi
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
host_platform="$(detect_platform)"
vcpkg_root="${SIMPLEGRAPHIC_VCPKG_ROOT:-$repo_dir/vcpkg}"
dry_run="${SIMPLEGRAPHIC_DRY_RUN:-}"

runtime_platform="${SIMPLEGRAPHIC_RUNTIME_PLATFORM:-}"
runtime_architecture="${SIMPLEGRAPHIC_RUNTIME_ARCHITECTURE:-}"
runtime_target="${SIMPLEGRAPHIC_RUNTIME_TARGET:-}"

if [ -n "$runtime_target" ]; then
    case "$runtime_target" in
        *-*)
            first_component="${runtime_target%%-*}"
            remaining_components="${runtime_target#*-}"
            if [ "$remaining_components" != "${remaining_components#*-}" ]; then
                die "SIMPLEGRAPHIC_RUNTIME_TARGET must be a two-part <platform>-<architecture> value"
            fi
            if ! is_known_architecture "$first_component"; then
                runtime_platform="${runtime_target%-*}"
                runtime_architecture="${runtime_target##*-}"
            else
                runtime_platform="$remaining_components"
                runtime_architecture="$first_component"
            fi
            ;;
        *)
            die "SIMPLEGRAPHIC_RUNTIME_TARGET must look like <platform>-<architecture>"
            ;;
    esac
fi

runtime_platform="$(normalize_platform "${runtime_platform:-$(detect_platform)}")"
runtime_architecture="$(normalize_architecture "${runtime_architecture:-$(detect_architecture)}")"
require_safe_component "$runtime_platform"
require_safe_component "$runtime_architecture"
runtime_target="$runtime_platform-$runtime_architecture"

runtime_lua_module_ext="${SIMPLEGRAPHIC_LUA_MODULE_EXT:-$(lua_module_ext_for_platform "$runtime_platform")}"
runtime_entry_library="${SIMPLEGRAPHIC_ENTRY_LIBRARY:-$(entry_library_for_platform "$runtime_platform")}"
runtime_lcurl_module="${SIMPLEGRAPHIC_LCURL_MODULE:-lcurl$runtime_lua_module_ext}"
runtime_lua_utf8_module="${SIMPLEGRAPHIC_LUA_UTF8_MODULE:-lua-utf8$runtime_lua_module_ext}"
runtime_socket_module="${SIMPLEGRAPHIC_SOCKET_MODULE:-socket$runtime_lua_module_ext}"
runtime_lzip_module="${SIMPLEGRAPHIC_LZIP_MODULE:-lzip$runtime_lua_module_ext}"
require_safe_file_name "$runtime_entry_library"
require_safe_file_name "$runtime_lcurl_module"
require_safe_file_name "$runtime_lua_utf8_module"
require_safe_file_name "$runtime_socket_module"
require_safe_file_name "$runtime_lzip_module"

build_type="${SIMPLEGRAPHIC_BUILD_TYPE:-Release}"
require_safe_build_value "$build_type"
build_dir="${SIMPLEGRAPHIC_BUILD_DIR:-$repo_dir/build/$runtime_target}"
install_dir="${SIMPLEGRAPHIC_INSTALL_DIR:-$repo_dir/install/$runtime_target}"
archive_dir="${SIMPLEGRAPHIC_ARCHIVE_DIR:-$repo_dir}"
triplet="${SIMPLEGRAPHIC_VCPKG_TRIPLET:-$(default_triplet_for_target "$runtime_target")}"
generator="${SIMPLEGRAPHIC_CMAKE_GENERATOR:-}"
cmake_platform="${SIMPLEGRAPHIC_CMAKE_PLATFORM:-}"
cmake_osx_architectures="${SIMPLEGRAPHIC_CMAKE_OSX_ARCHITECTURES:-}"
vcpkg_installed_dir="${SIMPLEGRAPHIC_VCPKG_INSTALLED_DIR:-${VCPKG_INSTALLED_DIR:-}}"
runtime_archive="$archive_dir/SimpleGraphicRuntime-$runtime_target.tar"
resolved_cmake_osx_architectures=""
if [ "$runtime_platform" = "macos" ]; then
    resolved_cmake_osx_architectures="${cmake_osx_architectures:-$(cmake_osx_architecture_for_target_architecture "$runtime_architecture")}"
fi

if is_truthy "$dry_run"; then
    print_package_config
    exit 0
fi

require_command cmake
require_command tar
python_cmd="$(detect_python)"
if [ "$host_platform" != "win32" ]; then
    require_python_venv
fi
if [ "$host_platform" != "win32" ] \
        && ! command -v pkg-config >/dev/null 2>&1 \
        && ! command -v pkgconf >/dev/null 2>&1; then
    die "pkg-config is required by vcpkg; install pkg-config or pkgconf first"
fi

bootstrap_vcpkg
mkdir -p "$archive_dir"

if [ "$generator" = "auto" ]; then
    [ "$host_platform" = "win32" ] || die "SIMPLEGRAPHIC_CMAKE_GENERATOR=auto is only supported on Windows"
    generator="$(detect_visual_studio_generator)" || die "could not detect an installed Visual Studio CMake generator"
    printf 'Using CMake generator %s\n' "$generator"
fi

configure_args=(
    -S "$repo_dir"
    -B "$build_dir"
    -DCMAKE_BUILD_TYPE="$build_type"
    -DCMAKE_INSTALL_PREFIX="$install_dir"
    -DCMAKE_TOOLCHAIN_FILE="$vcpkg_root/scripts/buildsystems/vcpkg.cmake"
    -DVCPKG_TARGET_TRIPLET="$triplet"
)

if [ -n "$resolved_cmake_osx_architectures" ]; then
    configure_args+=(-DCMAKE_OSX_ARCHITECTURES="$resolved_cmake_osx_architectures")
fi

if [ -n "$vcpkg_installed_dir" ]; then
    configure_args+=(-DVCPKG_INSTALLED_DIR="$vcpkg_installed_dir")
fi

generator_args=()
if [ -n "$generator" ]; then
    generator_args+=(-G "$generator")
fi
if [ -n "$cmake_platform" ]; then
    generator_args+=(-A "$cmake_platform")
fi

printf 'Packaging SimpleGraphic runtime %s with vcpkg triplet %s\n' "$runtime_target" "$triplet"
cmake "${generator_args[@]}" "${configure_args[@]}"
cmake --build "$build_dir" --config "$build_type"
reset_directory_contents "$install_dir"
cmake --install "$build_dir" --config "$build_type"
prune_windows_system_runtime_files
write_runtime_manifest

(cd "$install_dir" && COPYFILE_DISABLE=1 tar -cvf - .) > "$runtime_archive"
"$python_cmd" "$repo_dir/scripts/verify-runtime-archive.py" "$runtime_archive"
printf 'Wrote %s\n' "$runtime_archive"

if [ "$runtime_target" = "win32-x64" ]; then
    shopt -s nullglob
    windows_dlls=("$install_dir"/*.dll)
    shopt -u nullglob
    [ "${#windows_dlls[@]}" -gt 0 ] || die "no DLLs found in $install_dir for legacy Windows archive"

    legacy_archive="$archive_dir/SimpleGraphicDLLs-x64-windows.tar"
    (cd "$install_dir" && COPYFILE_DISABLE=1 tar -cvf - ./*.dll) > "$legacy_archive"
    printf 'Wrote %s\n' "$legacy_archive"
fi
