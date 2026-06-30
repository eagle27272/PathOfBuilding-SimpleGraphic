import json
import pathlib
import struct
import subprocess
import sys
import tarfile


REQUIRED_ENTRYPOINTS = ["RunLuaFileAsWin", "RunLuaFileAsConsole"]
LUA_MODULES = ["lcurl.dll", "lua-utf8.dll", "socket.dll", "lzip.dll"]
POSIX_LUA_MODULES = ["lcurl.so", "lua-utf8.so", "socket.so", "lzip.so"]


def make_pe_x64(exports=(), imports=(), machine=0x8664):
    data = bytearray(0x1000)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, machine)
    struct.pack_into("<H", data, 0x86, 1)
    struct.pack_into("<H", data, 0x94, 0xF0)

    optional_header = 0x98
    struct.pack_into("<H", data, optional_header, 0x20B)

    section = optional_header + 0xF0
    data[section : section + 8] = b".edata\0\0"
    struct.pack_into("<I", data, section + 8, 0x800)
    struct.pack_into("<I", data, section + 12, 0x1000)
    struct.pack_into("<I", data, section + 16, 0x800)
    struct.pack_into("<I", data, section + 20, 0x200)

    if exports:
        export_directory = 0x200
        name_array_rva = 0x1080
        ordinal_array_rva = 0x1090
        function_array_rva = 0x10A0
        dll_name_rva = 0x10C0
        string_rva = 0x10E0
        struct.pack_into("<II", data, optional_header + 112, 0x1000, 0x200)
        struct.pack_into(
            "<IIHHIIIIIII",
            data,
            export_directory,
            0,
            0,
            0,
            0,
            dll_name_rva,
            1,
            len(exports),
            len(exports),
            function_array_rva,
            name_array_rva,
            ordinal_array_rva,
        )
        data[0x200 + (dll_name_rva - 0x1000) : 0x200 + (dll_name_rva - 0x1000) + 18] = (
            b"SimpleGraphic.dll\0"
        )

        cursor = string_rva
        for index, export in enumerate(exports):
            struct.pack_into("<I", data, 0x200 + (name_array_rva - 0x1000) + index * 4, cursor)
            struct.pack_into("<H", data, 0x200 + (ordinal_array_rva - 0x1000) + index * 2, index)
            struct.pack_into(
                "<I",
                data,
                0x200 + (function_array_rva - 0x1000) + index * 4,
                0x1100 + index * 4,
            )
            raw = 0x200 + (cursor - 0x1000)
            data[raw : raw + len(export)] = export.encode("ascii")
            cursor += len(export) + 1

    if imports:
        import_directory_rva = 0x1200
        import_directory = 0x200 + (import_directory_rva - 0x1000)
        name_rva = 0x1300
        struct.pack_into(
            "<II",
            data,
            optional_header + 112 + 8,
            import_directory_rva,
            (len(imports) + 1) * 20,
        )
        for index, imported_dll in enumerate(imports):
            struct.pack_into(
                "<IIIII",
                data,
                import_directory + index * 20,
                0,
                0,
                0,
                name_rva,
                0,
            )
            encoded = imported_dll.encode("ascii") + b"\0"
            raw = 0x200 + (name_rva - 0x1000)
            data[raw : raw + len(encoded)] = encoded
            name_rva += len(encoded)

    return bytes(data)


def padded_command(command):
    while len(command) % 8:
        command += b"\0"
    return command


def make_macho_arm64(
    exports=(), dependencies=(), rpaths=("@loader_path",), cpu_type=0x0100000C
):
    commands = []
    string_table = b"\0"

    def append_dylib_command(command_id, path):
        encoded = path.encode("utf-8") + b"\0"
        command = struct.pack("<IIIiii", command_id, 0, 24, 0, 0, 0) + encoded
        command = padded_command(command)
        command = command[:4] + struct.pack("<I", len(command)) + command[8:]
        commands.append(command)

    def append_rpath_command(path):
        encoded = path.encode("utf-8") + b"\0"
        command = struct.pack("<III", 0x8000001C, 0, 12) + encoded
        command = padded_command(command)
        command = command[:4] + struct.pack("<I", len(command)) + command[8:]
        commands.append(command)

    append_dylib_command(0xD, "@rpath/libSimpleGraphic.dylib")
    for dependency in dependencies:
        append_dylib_command(0xC, dependency)
    for rpath in rpaths:
        append_rpath_command(rpath)

    symbol_count = len(exports)
    command_bytes_without_symtab = b"".join(commands)
    symtab_offset = 32 + len(command_bytes_without_symtab) + 24
    string_offset = symtab_offset + symbol_count * 16
    string_indices = []
    for export in exports:
        string_indices.append(len(string_table))
        string_table += f"_{export}".encode("utf-8") + b"\0"

    symtab_command = struct.pack(
        "<IIIIII",
        0x2,
        24,
        symtab_offset,
        symbol_count,
        string_offset,
        len(string_table),
    )
    commands.append(symtab_command)
    command_bytes = b"".join(commands)

    header = struct.pack(
        "<IiiIIII",
        0xFEEDFACF,
        cpu_type,
        0,
        6,
        len(commands),
        len(command_bytes),
        0,
    ) + struct.pack("<I", 0)

    symbols = bytearray()
    for index in string_indices:
        symbols += struct.pack("<IBBHQ", index, 0x0F, 1, 0, 0x1000)

    return header + command_bytes + bytes(symbols) + string_table


def make_elf_x64(exports=(), dependencies=("libdep.so",), rpath="$ORIGIN", machine=62):
    data = bytearray(0x600)
    data[:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    data[6] = 1

    section_header_offset = 0x100
    section_count = 4
    section_entry_size = 64
    struct.pack_into(
        "<HHIQQQIHHHHHH",
        data,
        16,
        3,
        machine,
        1,
        0,
        0,
        section_header_offset,
        0,
        64,
        0,
        0,
        section_entry_size,
        section_count,
        0,
    )

    strings = bytearray(b"\0")
    string_offsets = {}
    for text in [*exports, *dependencies, rpath]:
        if text not in string_offsets:
            string_offsets[text] = len(strings)
            strings += text.encode("utf-8") + b"\0"
    string_offset = 0x300
    data[string_offset : string_offset + len(strings)] = strings

    symbol_offset = 0x200
    for index, export in enumerate(exports):
        struct.pack_into(
            "<IBBHQQ",
            data,
            symbol_offset + index * 24,
            string_offsets[export],
            0x10,
            0,
            1,
            0x1000,
            0,
        )
    symbol_size = len(exports) * 24

    dynamic_offset = 0x400
    dynamic_index = 0
    for dependency in dependencies:
        struct.pack_into(
            "<qQ",
            data,
            dynamic_offset + dynamic_index * 16,
            1,
            string_offsets[dependency],
        )
        dynamic_index += 1
    struct.pack_into("<qQ", data, dynamic_offset + dynamic_index * 16, 29, string_offsets[rpath])
    dynamic_index += 1
    struct.pack_into("<qQ", data, dynamic_offset + dynamic_index * 16, 0, 0)
    dynamic_size = (dynamic_index + 1) * 16

    def write_section(index, section_type, offset, size, link=0, entry_size=0):
        struct.pack_into(
            "<IIQQQQIIQQ",
            data,
            section_header_offset + index * section_entry_size,
            0,
            section_type,
            0,
            0,
            offset,
            size,
            link,
            0,
            8,
            entry_size,
        )

    write_section(1, 11, symbol_offset, symbol_size, link=2, entry_size=24)
    write_section(2, 3, string_offset, len(strings))
    write_section(3, 6, dynamic_offset, dynamic_size, link=2, entry_size=16)
    return bytes(data)


def write_runtime_manifest(archive_root, manifest):
    files = sorted(
        {path.name for path in archive_root.iterdir() if path.is_file()}
        | {"SimpleGraphicRuntime.json"}
    )
    manifest = dict(manifest)
    manifest["files"] = files
    (archive_root / "SimpleGraphicRuntime.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def make_runtime_archive(
    tmp_path,
    exports,
    imports=(),
    extra_files=(),
    architecture="x64",
    machine=0x8664,
    manifest_entrypoints=None,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    if manifest_entrypoints is None:
        manifest_entrypoints = REQUIRED_ENTRYPOINTS
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": f"win32-{architecture}",
        "platform": "win32",
        "architecture": architecture,
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "SimpleGraphic.dll",
        "entrypoints": manifest_entrypoints,
        "luaModules": LUA_MODULES,
    }
    (archive_root / "SimpleGraphic.dll").write_bytes(make_pe_x64(exports, imports, machine))
    for module in LUA_MODULES:
        (archive_root / module).write_bytes(make_pe_x64(machine=machine))
    for name, contents in extra_files:
        (archive_root / name).write_bytes(contents)
    write_runtime_manifest(archive_root, manifest)

    archive_path = tmp_path / f"SimpleGraphicRuntime-win32-{architecture}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)
    return archive_path


def make_macos_runtime_archive(
    tmp_path,
    dependencies,
    rpaths=("@loader_path",),
    include_dependencies=True,
    architecture="arm64",
    cpu_type=0x0100000C,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": f"macos-{architecture}",
        "platform": "macos",
        "architecture": architecture,
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": "libSimpleGraphic.dylib",
        "entrypoints": REQUIRED_ENTRYPOINTS,
        "luaModules": POSIX_LUA_MODULES,
    }
    (archive_root / "libSimpleGraphic.dylib").write_bytes(
        make_macho_arm64(REQUIRED_ENTRYPOINTS, dependencies, rpaths, cpu_type)
    )
    for module in POSIX_LUA_MODULES:
        (archive_root / module).write_bytes(make_macho_arm64(cpu_type=cpu_type))
    if include_dependencies:
        for dependency in dependencies:
            if dependency.startswith("@rpath/"):
                name = dependency.rsplit("/", 1)[-1]
                if name != "libSimpleGraphic.dylib":
                    (archive_root / name).write_bytes(make_macho_arm64(cpu_type=cpu_type))
    write_runtime_manifest(archive_root, manifest)

    archive_path = tmp_path / f"SimpleGraphicRuntime-macos-{architecture}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)
    return archive_path


def make_linux_runtime_archive(
    tmp_path,
    dependencies=("libdep.so",),
    rpath="$ORIGIN",
    include_dependencies=True,
    platform="linux",
    architecture="x64",
    machine=62,
    entry_library="libSimpleGraphic.so",
    lua_modules=POSIX_LUA_MODULES,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    manifest = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "target": f"{platform}-{architecture}",
        "platform": platform,
        "architecture": architecture,
        "buildType": "Release",
        "layout": "flat",
        "entryLibrary": entry_library,
        "entrypoints": REQUIRED_ENTRYPOINTS,
        "luaModules": lua_modules,
    }
    (archive_root / entry_library).write_bytes(
        make_elf_x64(REQUIRED_ENTRYPOINTS, dependencies, rpath, machine)
    )
    for module in lua_modules:
        (archive_root / module).write_bytes(make_elf_x64(machine=machine))
    if include_dependencies:
        for dependency in dependencies:
            if dependency.startswith("libdep"):
                (archive_root / dependency).write_bytes(
                    make_elf_x64(dependencies=(), machine=machine)
                )
    write_runtime_manifest(archive_root, manifest)

    archive_path = tmp_path / f"SimpleGraphicRuntime-{platform}-{architecture}.tar"
    with tarfile.open(archive_path, "w") as archive:
        for path in archive_root.iterdir():
            archive.add(path, arcname=path.name)
    return archive_path


def run_verifier(archive_path):
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "verify-runtime-archive.py"), str(archive_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_verify_runtime_archive_accepts_required_pe_exports(tmp_path):
    result = run_verifier(make_runtime_archive(tmp_path, REQUIRED_ENTRYPOINTS))

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_rejects_missing_pe_entrypoint_export(tmp_path):
    result = run_verifier(make_runtime_archive(tmp_path, ["RunLuaFileAsWin"]))

    assert result.returncode != 0
    assert "missing exports: RunLuaFileAsConsole" in result.stderr


def test_verify_runtime_archive_rejects_extra_manifest_entrypoint(tmp_path):
    result = run_verifier(
        make_runtime_archive(
            tmp_path,
            REQUIRED_ENTRYPOINTS,
            manifest_entrypoints=[*REQUIRED_ENTRYPOINTS, "RunExperimental"],
        )
    )

    assert result.returncode != 0
    assert "must list only entrypoints" in result.stderr


def test_verify_runtime_archive_rejects_duplicate_manifest_entrypoint(tmp_path):
    result = run_verifier(
        make_runtime_archive(
            tmp_path,
            REQUIRED_ENTRYPOINTS,
            manifest_entrypoints=[
                "RunLuaFileAsWin",
                "RunLuaFileAsConsole",
                "RunLuaFileAsConsole",
            ],
        )
    )

    assert result.returncode != 0
    assert "field 'entrypoints' contains duplicate entry 'RunLuaFileAsConsole'" in result.stderr


def test_verify_runtime_archive_rejects_missing_pe_dependency(tmp_path):
    result = run_verifier(
        make_runtime_archive(tmp_path, REQUIRED_ENTRYPOINTS, imports=["LocalDep.dll"])
    )

    assert result.returncode != 0
    assert "depends on LocalDep.dll, which is not present in the archive" in result.stderr


def test_verify_runtime_archive_accepts_windows_system_dependency(tmp_path):
    result = run_verifier(
        make_runtime_archive(tmp_path, REQUIRED_ENTRYPOINTS, imports=["KERNEL32.dll"])
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_accepts_pe_arm64ec_binary(tmp_path):
    result = run_verifier(
        make_runtime_archive(
            tmp_path,
            REQUIRED_ENTRYPOINTS,
            architecture="arm64ec",
            machine=0xA641,
        )
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_accepts_elf_architecture_alias(tmp_path):
    archive_path = make_linux_runtime_archive(tmp_path, architecture="x64", machine=62)
    alias_path = archive_path.with_name("SimpleGraphicRuntime-linux-amd64.tar")
    archive_path.rename(alias_path)

    result = run_verifier(alias_path)

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_accepts_architecture_first_archive_name(tmp_path):
    archive_path = make_linux_runtime_archive(tmp_path, architecture="x64", machine=62)
    alias_path = archive_path.with_name("SimpleGraphicRuntime-x64-linux.tar")
    archive_path.rename(alias_path)

    result = run_verifier(alias_path)

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_rejects_multi_hyphen_archive_target(tmp_path):
    archive_path = make_linux_runtime_archive(tmp_path, architecture="x64", machine=62)
    alias_path = archive_path.with_name("SimpleGraphicRuntime-linux-gnu-x64.tar")
    archive_path.rename(alias_path)

    result = run_verifier(alias_path)

    assert result.returncode != 0
    assert "target must be a two-part" in result.stderr


def test_verify_runtime_archive_accepts_loongarch64_elf_binary(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(tmp_path, architecture="loongarch64", machine=258)
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_accepts_armv7_label_for_elf_arm_binary(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(tmp_path, architecture="armv7", machine=40)
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_accepts_manifest_names_for_unknown_platform(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(
            tmp_path,
            platform="freebsd",
            architecture="x64",
            entry_library="SimpleGraphic.native",
            lua_modules=["lcurl.native", "lua-utf8.native", "socket.native", "lzip.native"],
        )
    )

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_rejects_wrong_known_platform_entry_library(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(tmp_path, entry_library="SimpleGraphic.native")
    )

    assert result.returncode != 0
    assert "field 'entryLibrary' expected 'libSimpleGraphic.so'" in result.stderr


def test_verify_runtime_archive_rejects_unknown_platform_wrong_lua_modules(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(
            tmp_path,
            platform="freebsd",
            lua_modules=["alpha.native", "beta.native", "gamma.native", "delta.native"],
        )
    )

    assert result.returncode != 0
    assert "must list Lua modules ['lcurl', 'lua-utf8', 'lzip', 'socket']" in result.stderr


def test_verify_runtime_archive_rejects_duplicate_lua_module_entries(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(
            tmp_path,
            lua_modules=["lcurl.so", "lua-utf8.so", "socket.so", "socket.so"],
        )
    )

    assert result.returncode != 0
    assert "field 'luaModules' contains duplicate entry 'socket.so'" in result.stderr


def test_verify_runtime_archive_rejects_extra_lua_module_entries(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(
            tmp_path,
            lua_modules=["lcurl.so", "lua-utf8.so", "socket.so", "lzip.so", "extra.so"],
        )
    )

    assert result.returncode != 0
    assert "must list Lua modules ['lcurl.so', 'lua-utf8.so', 'lzip.so', 'socket.so']" in result.stderr


def test_verify_runtime_archive_rejects_appledouble_metadata(tmp_path):
    archive_path = make_runtime_archive(tmp_path, REQUIRED_ENTRYPOINTS)
    metadata = tmp_path / "._SimpleGraphic.dll"
    metadata.write_bytes(b"metadata")
    with tarfile.open(archive_path, "a") as archive:
        archive.add(metadata, arcname=metadata.name)

    result = run_verifier(archive_path)

    assert result.returncode != 0
    assert "must not contain macOS metadata files" in result.stderr


def test_verify_runtime_archive_accepts_relocatable_macho_dependencies(tmp_path):
    result = run_verifier(make_macos_runtime_archive(tmp_path, ["@rpath/libdep.dylib"]))

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_rejects_absolute_macho_dependency(tmp_path):
    result = run_verifier(make_macos_runtime_archive(tmp_path, ["/tmp/vcpkg/libdep.dylib"]))

    assert result.returncode != 0
    assert "non-relocatable Mach-O dependency path" in result.stderr


def test_verify_runtime_archive_rejects_missing_macho_dependency(tmp_path):
    result = run_verifier(
        make_macos_runtime_archive(
            tmp_path, ["@rpath/libdep.dylib"], include_dependencies=False
        )
    )

    assert result.returncode != 0
    assert "depends on @rpath/libdep.dylib, which is not present in the archive" in result.stderr


def test_verify_runtime_archive_accepts_origin_elf_runpath(tmp_path):
    result = run_verifier(make_linux_runtime_archive(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "Verified" in result.stdout


def test_verify_runtime_archive_rejects_absolute_elf_runpath(tmp_path):
    result = run_verifier(make_linux_runtime_archive(tmp_path, rpath="/tmp/vcpkg/lib"))

    assert result.returncode != 0
    assert "non-relocatable ELF RPATH/RUNPATH" in result.stderr


def test_verify_runtime_archive_rejects_missing_elf_dependency(tmp_path):
    result = run_verifier(
        make_linux_runtime_archive(tmp_path, dependencies=("libdep.so",), include_dependencies=False)
    )

    assert result.returncode != 0
    assert "depends on libdep.so, which is not present in the archive" in result.stderr
