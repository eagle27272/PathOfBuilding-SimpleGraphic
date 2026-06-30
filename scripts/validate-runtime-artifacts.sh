#!/usr/bin/env bash
set -euo pipefail

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

artifact_dir="${1:-runtime-artifacts}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"

[ -d "$artifact_dir" ] || die "artifact directory does not exist: $artifact_dir"

default_expected_targets=(
    win32-x64
    win32-arm64
    linux-x64
    linux-arm64
    macos-x64
    macos-arm64
)
expected_targets_value="${SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS:-}"
expected_targets=()
if [ -n "$expected_targets_value" ]; then
    expected_targets_value="${expected_targets_value//,/ }"
    read -r -a expected_targets <<< "$expected_targets_value"
else
    expected_targets=("${default_expected_targets[@]}")
fi
[ "${#expected_targets[@]}" -gt 0 ] || die "expected runtime target list is empty"
require_legacy_windows="${SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE:-1}"
supported_runtime_suffixes=(".tar" ".tar.gz" ".tgz")

lower_value() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

normalize_platform() {
    local value
    value="$(lower_value "$1")"
    case "$value" in
        darwin|mac|macos|osx)
            printf 'macos'
            ;;
        windows|win|win32|mingw*|msys*|cygwin*)
            printf 'win32'
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
        arm64|aarch64)
            printf 'arm64'
            ;;
        x86_64|amd64)
            printf 'x64'
            ;;
        i386|i486|i586|i686)
            printf 'x86'
            ;;
        armv7*|armhf)
            printf 'armv7'
            ;;
        armv6*)
            printf 'armv6'
            ;;
        armv5*)
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

valid_target_part() {
    case "$1" in
        ''|.*|*/*|*\\*|*[!a-z0-9._-]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

normalize_target() {
    local name="$1"
    local first
    local second
    local platform
    local architecture

    name="$(lower_value "$name")"
    case "$name" in
        *-*) ;;
        *) return 1 ;;
    esac

    first="${name%%-*}"
    second="${name#*-}"
    case "$second" in
        *-*) return 1 ;;
    esac

    valid_target_part "$first" || return 1
    valid_target_part "$second" || return 1

    if is_known_architecture "$first"; then
        platform="$(normalize_platform "$second")"
        architecture="$(normalize_architecture "$first")"
    else
        platform="$(normalize_platform "$first")"
        architecture="$(normalize_architecture "$second")"
    fi

    valid_target_part "$platform" || return 1
    valid_target_part "$architecture" || return 1
    printf '%s-%s\n' "$platform" "$architecture"
}

target_in_list() {
    local candidate="$1"
    local expected
    shift || true
    for expected in "$@"; do
        [ "$candidate" = "$expected" ] && return 0
    done
    return 1
}

canonical_expected_targets=()
for target in "${expected_targets[@]}"; do
    canonical_target="$(normalize_target "$target")" || die "unsafe expected runtime target: $target"
    if target_in_list "$canonical_target" "${canonical_expected_targets[@]}"; then
        die "duplicate expected runtime target: $canonical_target"
    fi
    canonical_expected_targets+=("$canonical_target")
done
expected_targets=("${canonical_expected_targets[@]}")

runtime_archive_paths=()
for suffix in "${supported_runtime_suffixes[@]}"; do
    for path in "$artifact_dir"/SimpleGraphicRuntime-*$suffix; do
        [ -e "$path" ] || continue
        runtime_archive_paths+=("$path")
    done
done

archive_target_from_path() {
    local base="$1"
    local target
    case "$base" in
        SimpleGraphicRuntime-*.tar.gz)
            target="${base#SimpleGraphicRuntime-}"
            target="${target%.tar.gz}"
            ;;
        SimpleGraphicRuntime-*.tgz)
            target="${base#SimpleGraphicRuntime-}"
            target="${target%.tgz}"
            ;;
        SimpleGraphicRuntime-*.tar)
            target="${base#SimpleGraphicRuntime-}"
            target="${target%.tar}"
            ;;
        *)
            return 1
            ;;
    esac
    printf '%s\n' "$target"
}

archive_targets=()
for path in "${runtime_archive_paths[@]}"; do
    base="$(basename -- "$path")"
    target="$(archive_target_from_path "$base")" || die "unsupported runtime archive: $base"
    canonical_target="$(normalize_target "$target")" || die "unsafe runtime archive target: $base"
    target_in_list "$canonical_target" "${expected_targets[@]}" || die "unexpected runtime archive: $base"
    archive_targets+=("$canonical_target")
done

for target in "${expected_targets[@]}"; do
    match_count=0
    for archive_target in "${archive_targets[@]}"; do
        if [ "$archive_target" = "$target" ]; then
            match_count=$((match_count + 1))
        fi
    done
    [ "$match_count" -gt 0 ] || die "missing runtime archive for target: $target"
    [ "$match_count" -eq 1 ] || die "duplicate runtime archives for target: $target"
done

"$repo_dir/scripts/verify-runtime-archive.py" "${runtime_archive_paths[@]}"

legacy_archive="$artifact_dir/SimpleGraphicDLLs-x64-windows.tar"
case "$require_legacy_windows" in
    1|true|TRUE|yes|YES|on|ON)
        [ -s "$legacy_archive" ] || die "missing legacy Windows runtime archive: $legacy_archive"
        legacy_members="$(tar -tf "$legacy_archive" | sed 's#^\./##')"
        if ! printf '%s\n' "$legacy_members" | grep -E '(^|/)[^/]+\.dll$' >/dev/null; then
            die "legacy Windows runtime archive contains no DLL files: $legacy_archive"
        fi
        for required_dll in SimpleGraphic.dll lcurl.dll lua-utf8.dll socket.dll lzip.dll; do
            if ! printf '%s\n' "$legacy_members" | grep -Fx "$required_dll" >/dev/null; then
                die "legacy Windows runtime archive is missing required DLL: $required_dll"
            fi
        done
        ;;
    0|false|FALSE|no|NO|off|OFF)
        ;;
    *)
        die "SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE must be true or false"
        ;;
esac

"$repo_dir/scripts/write-runtime-index.py" \
    --artifact-dir "$artifact_dir" \
    --output "$artifact_dir/SimpleGraphicRuntime-index.json"
