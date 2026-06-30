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

target_is_expected() {
    local candidate="$1"
    local expected
    for expected in "${expected_targets[@]}"; do
        [ "$candidate" = "$expected" ] && return 0
    done
    return 1
}

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

for target in "${expected_targets[@]}"; do
    case "$target" in
        ''|.*|*/*|*\\*|*[!a-z0-9._-]*)
            die "unsafe expected runtime target: $target"
            ;;
    esac
    matching_paths=()
    for suffix in "${supported_runtime_suffixes[@]}"; do
        path="$artifact_dir/SimpleGraphicRuntime-$target$suffix"
        [ -f "$path" ] || continue
        matching_paths+=("$path")
    done
    [ "${#matching_paths[@]}" -gt 0 ] || die "missing runtime archive for target: $target"
    [ "${#matching_paths[@]}" -eq 1 ] || die "duplicate runtime archives for target: $target"
done

for path in "${runtime_archive_paths[@]}"; do
    base="$(basename -- "$path")"
    target="$(archive_target_from_path "$base")" || die "unsupported runtime archive: $base"
    case "$target" in
        ''|.*|*/*|*\\*|*[!a-z0-9._-]*)
            die "unsafe runtime archive target: $base"
            ;;
    esac
    target_is_expected "$target" || die "unexpected runtime archive: $base"
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
