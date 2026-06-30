#!/usr/bin/env python3
import argparse
import json
import pathlib
import struct
import sys
import tarfile


MANIFEST_NAME = "SimpleGraphicRuntime.json"
REQUIRED_ENTRYPOINTS = {"RunLuaFileAsWin", "RunLuaFileAsConsole"}
MODULE_BASENAMES = ("lcurl", "lua-utf8", "socket", "lzip")
KNOWN_ARCHITECTURES = {
    "x64",
    "x86",
    "arm64",
    "arm64ec",
    "arm64x",
    "arm",
    "armv6",
    "armv7",
    "riscv32",
    "riscv64",
    "riscv128",
    "ppc",
    "ppc64",
    "ppc64le",
    "mips",
    "mips64",
    "s390",
    "s390x",
    "loongarch32",
    "loongarch64",
    "ia64",
}

ELF_MACHINES = {
    3: "x86",
    20: "ppc",
    21: "ppc64",
    40: "arm",
    62: "x64",
    183: "arm64",
}

ELF_CLASS_MACHINES = {
    8: {1: "mips", 2: "mips64"},
    22: {1: "s390", 2: "s390x"},
    243: {1: "riscv32", 2: "riscv64"},
    258: {1: "loongarch32", 2: "loongarch64"},
}

MACHO_CPU_TYPES = {
    7: "x86",
    12: "arm",
    0x01000007: "x64",
    0x0100000C: "arm64",
}

PE_MACHINES = {
    0x014C: "x86",
    0x01C0: "arm",
    0x0200: "ia64",
    0x5032: "riscv32",
    0x5064: "riscv64",
    0x5128: "riscv128",
    0x6232: "loongarch32",
    0x6264: "loongarch64",
    0x8664: "x64",
    0xA641: "arm64ec",
    0xA64E: "arm64x",
    0xAA64: "arm64",
}

LINUX_SYSTEM_DEPENDENCIES = {
    "ld-linux-aarch64.so.1",
    "ld-linux-armhf.so.3",
    "ld-linux-x86-64.so.2",
    "libc.so.6",
    "libdl.so.2",
    "libgcc_s.so.1",
    "libm.so.6",
    "libpthread.so.0",
    "librt.so.1",
    "libstdc++.so.6",
    "libX11.so.6",
    "libXcursor.so.1",
    "libXext.so.6",
    "libXi.so.6",
    "libXinerama.so.1",
    "libXrandr.so.2",
    "libxcb.so.1",
    "libxkbcommon.so.0",
    "libwayland-client.so.0",
    "libwayland-cursor.so.0",
    "libwayland-egl.so.1",
}

WINDOWS_SYSTEM_DEPENDENCIES = {
    "advapi32.dll",
    "bcrypt.dll",
    "cfgmgr32.dll",
    "comctl32.dll",
    "comdlg32.dll",
    "crypt32.dll",
    "d3d11.dll",
    "d3d9.dll",
    "d3dcompiler_47.dll",
    "dnsapi.dll",
    "dwmapi.dll",
    "dxgi.dll",
    "gdi32.dll",
    "imm32.dll",
    "iphlpapi.dll",
    "kernel32.dll",
    "mpr.dll",
    "ncrypt.dll",
    "normaliz.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleacc.dll",
    "oleaut32.dll",
    "opengl32.dll",
    "powrprof.dll",
    "propsys.dll",
    "rpcrt4.dll",
    "sechost.dll",
    "secur32.dll",
    "setupapi.dll",
    "shell32.dll",
    "shcore.dll",
    "shlwapi.dll",
    "user32.dll",
    "userenv.dll",
    "uxtheme.dll",
    "version.dll",
    "winhttp.dll",
    "winmm.dll",
    "winspool.drv",
    "wldap32.dll",
    "ws2_32.dll",
    "wtsapi32.dll",
}

ELF_SECTION_DYNSYM = 11
ELF_SECTION_SYMTAB = 2
ELF_SECTION_DYNAMIC = 6
ELF_DYNAMIC_NEEDED = 1
ELF_DYNAMIC_RPATH = 15
ELF_DYNAMIC_RUNPATH = 29
MACHO_LOAD_SYMTAB = 0x2
MACHO_LOAD_ID_DYLIB = 0xD
MACHO_LOAD_DYLIB_COMMANDS = {0xC, 0x18, 0x1F, 0x23, MACHO_LOAD_ID_DYLIB}
MACHO_LOAD_RPATH = 0x1C
MACHO_REQ_DYLD = 0x80000000
MACHO_N_EXT = 0x01
MACHO_N_TYPE = 0x0E
MACHO_N_UNDF = 0x00


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def split_archive_target(path: pathlib.Path) -> tuple[str, str, str]:
    name = path.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    else:
        fail(f"{name} is not a supported tar archive")

    prefix = "SimpleGraphicRuntime-"
    if not stem.startswith(prefix):
        fail(f"{name} does not start with {prefix}")

    target = stem[len(prefix) :]
    if "-" not in target:
        fail(f"{name} target must look like <platform>-<architecture>")
    if target.count("-") != 1:
        fail(f"{name} target must be a two-part <platform>-<architecture> value")

    first, sep, second = target.partition("-")
    if sep and is_known_architecture(first):
        platform = normalize_platform_label(second)
        architecture = normalize_architecture_label(first)
    else:
        platform, architecture = target.rsplit("-", 1)
        platform = normalize_platform_label(platform)
        architecture = normalize_architecture_label(architecture)
    target = f"{platform}-{architecture}"
    if not platform or not architecture:
        fail(f"{name} target must include both platform and architecture")

    return target, platform, architecture


def normalize_platform_label(platform: str) -> str:
    platform = platform.lower()
    if platform in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if platform in {"windows", "win", "win32"} or platform.startswith(("mingw", "msys", "cygwin")):
        return "win32"
    return platform


def normalize_architecture_label(architecture: str) -> str:
    architecture = architecture.lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "armhf": "armv7",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "ppc64el": "ppc64le",
    }
    if architecture.startswith("armv7"):
        return "armv7"
    if architecture.startswith("armv6"):
        return "armv6"
    if architecture.startswith("armv5"):
        return "arm"
    return aliases.get(architecture, architecture)


def is_known_architecture(architecture: str) -> bool:
    return normalize_architecture_label(architecture) in KNOWN_ARCHITECTURES


def expected_entry_library(platform: str) -> str | None:
    if platform == "win32":
        return "SimpleGraphic.dll"
    if platform == "macos":
        return "libSimpleGraphic.dylib"
    if platform == "linux":
        return "libSimpleGraphic.so"
    return None


def expected_lua_modules(platform: str) -> tuple[str, ...] | None:
    if platform == "win32":
        return tuple(f"{name}.dll" for name in MODULE_BASENAMES)
    if platform in ("linux", "macos"):
        return tuple(f"{name}.so" for name in MODULE_BASENAMES)
    return None


def normalized_architecture(architecture: str) -> str:
    architecture = architecture.lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "armhf": "arm",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "ppc64el": "ppc64",
        "ppc64le": "ppc64",
    }
    if architecture.startswith(("armv5", "armv6", "armv7")):
        return "arm"
    return aliases.get(architecture, architecture)


def detect_elf_architectures(data: bytes) -> set[str]:
    if len(data) < 20 or not data.startswith(b"\x7fELF"):
        return set()
    elf_class = data[4]
    endian = {"\x01": "<", "\x02": ">"}.get(chr(data[5]))
    if not endian:
        return set()
    machine = struct.unpack_from(f"{endian}H", data, 18)[0]
    if machine in ELF_CLASS_MACHINES:
        architecture = ELF_CLASS_MACHINES[machine].get(elf_class)
        return {architecture} if architecture else set()
    return {ELF_MACHINES[machine]} if machine in ELF_MACHINES else set()


def detect_macho_architectures(data: bytes) -> set[str]:
    if len(data) < 8:
        return set()

    magic_be = struct.unpack_from(">I", data, 0)[0]
    magic_le = struct.unpack_from("<I", data, 0)[0]

    if magic_be in (0xCAFEBABE, 0xCAFEBABF):
        if len(data) < 8:
            return set()
        arch_count = struct.unpack_from(">I", data, 4)[0]
        arches = set()
        offset = 8
        arch_record_size = 24 if magic_be == 0xCAFEBABF else 20
        for _ in range(arch_count):
            if len(data) < offset + arch_record_size:
                return set()
            cpu_type = struct.unpack_from(">I", data, offset)[0]
            if cpu_type in MACHO_CPU_TYPES:
                arches.add(MACHO_CPU_TYPES[cpu_type])
            offset += arch_record_size
        return arches

    if magic_le in (0xFEEDFACE, 0xFEEDFACF):
        cpu_type = struct.unpack_from("<I", data, 4)[0]
        return {MACHO_CPU_TYPES[cpu_type]} if cpu_type in MACHO_CPU_TYPES else set()

    if magic_be in (0xFEEDFACE, 0xFEEDFACF):
        cpu_type = struct.unpack_from(">I", data, 4)[0]
        return {MACHO_CPU_TYPES[cpu_type]} if cpu_type in MACHO_CPU_TYPES else set()

    return set()


def detect_pe_architectures(data: bytes) -> set[str]:
    if len(data) < 0x40 or not data.startswith(b"MZ"):
        return set()
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if len(data) < pe_offset + 6 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        return set()
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    return {PE_MACHINES[machine]} if machine in PE_MACHINES else set()


def detect_binary_architectures(data: bytes) -> set[str]:
    return (
        detect_pe_architectures(data)
        or detect_elf_architectures(data)
        or detect_macho_architectures(data)
    )


def is_elf(data: bytes) -> bool:
    return len(data) >= 4 and data.startswith(b"\x7fELF")


def is_macho(data: bytes) -> bool:
    if len(data) < 4:
        return False
    magic_be = struct.unpack_from(">I", data, 0)[0]
    magic_le = struct.unpack_from("<I", data, 0)[0]
    return magic_be in (0xCAFEBABE, 0xCAFEBABF, 0xFEEDFACE, 0xFEEDFACF) or magic_le in (
        0xFEEDFACE,
        0xFEEDFACF,
    )


def is_pe(data: bytes) -> bool:
    return len(data) >= 2 and data.startswith(b"MZ")


def read_c_string(data: bytes, offset: int) -> str | None:
    if offset < 0 or offset >= len(data):
        return None
    end = data.find(b"\0", offset)
    if end < 0:
        return None
    return data[offset:end].decode("utf-8", errors="replace")


def normalize_export_name(name: str) -> set[str]:
    names = {name}
    if name.startswith("_"):
        names.add(name[1:])
    return names


def pe_rva_to_offset(
    rva: int, sections: list[tuple[int, int, int, int]]
) -> int | None:
    for virtual_address, virtual_size, raw_size, raw_pointer in sections:
        span = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + span:
            return raw_pointer + (rva - virtual_address)
    return None


def detect_pe_exports(data: bytes) -> set[str]:
    if len(data) < 0x40 or not data.startswith(b"MZ"):
        return set()
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if len(data) < pe_offset + 24 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        return set()

    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header_offset = pe_offset + 24
    if len(data) < optional_header_offset + optional_header_size:
        return set()

    optional_magic = struct.unpack_from("<H", data, optional_header_offset)[0]
    if optional_magic == 0x10B:
        data_directory_offset = optional_header_offset + 96
    elif optional_magic == 0x20B:
        data_directory_offset = optional_header_offset + 112
    else:
        return set()

    if len(data) < data_directory_offset + 8:
        return set()
    export_rva, export_size = struct.unpack_from("<II", data, data_directory_offset)
    if export_rva == 0 or export_size == 0:
        return set()

    section_offset = optional_header_offset + optional_header_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if len(data) < offset + 40:
            return set()
        virtual_size = struct.unpack_from("<I", data, offset + 8)[0]
        virtual_address = struct.unpack_from("<I", data, offset + 12)[0]
        raw_size = struct.unpack_from("<I", data, offset + 16)[0]
        raw_pointer = struct.unpack_from("<I", data, offset + 20)[0]
        sections.append((virtual_address, virtual_size, raw_size, raw_pointer))

    export_offset = pe_rva_to_offset(export_rva, sections)
    if export_offset is None or len(data) < export_offset + 40:
        return set()

    name_count = struct.unpack_from("<I", data, export_offset + 24)[0]
    names_rva = struct.unpack_from("<I", data, export_offset + 32)[0]
    names_offset = pe_rva_to_offset(names_rva, sections)
    if names_offset is None or len(data) < names_offset + name_count * 4:
        return set()

    exports: set[str] = set()
    for index in range(name_count):
        name_rva = struct.unpack_from("<I", data, names_offset + index * 4)[0]
        name_offset = pe_rva_to_offset(name_rva, sections)
        if name_offset is None:
            continue
        name = read_c_string(data, name_offset)
        if name:
            exports.update(normalize_export_name(name))
    return exports


def detect_pe_imports(data: bytes) -> set[str]:
    if len(data) < 0x40 or not data.startswith(b"MZ"):
        return set()
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if len(data) < pe_offset + 24 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        return set()

    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header_offset = pe_offset + 24
    if len(data) < optional_header_offset + optional_header_size:
        return set()

    optional_magic = struct.unpack_from("<H", data, optional_header_offset)[0]
    if optional_magic == 0x10B:
        data_directory_offset = optional_header_offset + 96
    elif optional_magic == 0x20B:
        data_directory_offset = optional_header_offset + 112
    else:
        return set()

    import_directory_offset = data_directory_offset + 8
    if len(data) < import_directory_offset + 8:
        return set()
    import_rva, import_size = struct.unpack_from("<II", data, import_directory_offset)
    if import_rva == 0 or import_size == 0:
        return set()

    section_offset = optional_header_offset + optional_header_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if len(data) < offset + 40:
            return set()
        virtual_size = struct.unpack_from("<I", data, offset + 8)[0]
        virtual_address = struct.unpack_from("<I", data, offset + 12)[0]
        raw_size = struct.unpack_from("<I", data, offset + 16)[0]
        raw_pointer = struct.unpack_from("<I", data, offset + 20)[0]
        sections.append((virtual_address, virtual_size, raw_size, raw_pointer))

    import_offset = pe_rva_to_offset(import_rva, sections)
    if import_offset is None:
        return set()

    imports: set[str] = set()
    descriptor_count = import_size // 20 if import_size else 0
    for index in range(descriptor_count):
        descriptor_offset = import_offset + index * 20
        if len(data) < descriptor_offset + 20:
            break
        descriptor = struct.unpack_from("<IIIII", data, descriptor_offset)
        if descriptor == (0, 0, 0, 0, 0):
            break
        name_rva = descriptor[3]
        name_offset = pe_rva_to_offset(name_rva, sections)
        if name_offset is None:
            continue
        name = read_c_string(data, name_offset)
        if name:
            imports.add(name)
    return imports


def detect_elf_exports(data: bytes) -> set[str]:
    if len(data) < 0x40 or not data.startswith(b"\x7fELF"):
        return set()
    elf_class = data[4]
    endian = {"\x01": "<", "\x02": ">"}.get(chr(data[5]))
    if endian is None:
        return set()

    if elf_class == 1:
        header_format = f"{endian}HHIIIIIHHHHHH"
        header_offset = 16
        symbol_size_default = 16
    elif elf_class == 2:
        header_format = f"{endian}HHIQQQIHHHHHH"
        header_offset = 16
        symbol_size_default = 24
    else:
        return set()

    header_size = struct.calcsize(header_format)
    if len(data) < header_offset + header_size:
        return set()
    header = struct.unpack_from(header_format, data, header_offset)
    section_header_offset = header[5]
    section_header_entry_size = header[10]
    section_header_count = header[11]
    if section_header_offset == 0 or section_header_entry_size == 0:
        return set()

    section_format = f"{endian}IIIIIIIIII" if elf_class == 1 else f"{endian}IIQQQQIIQQ"
    expected_section_size = struct.calcsize(section_format)
    if section_header_entry_size < expected_section_size:
        return set()

    sections = []
    for index in range(section_header_count):
        offset = section_header_offset + index * section_header_entry_size
        if len(data) < offset + expected_section_size:
            return set()
        section = struct.unpack_from(section_format, data, offset)
        sections.append(section)

    exports: set[str] = set()
    for section in sections:
        section_type = section[1]
        if section_type not in (ELF_SECTION_DYNSYM, ELF_SECTION_SYMTAB):
            continue

        section_offset = section[4]
        section_size = section[5]
        linked_string_index = section[6]
        entry_size = section[9] or symbol_size_default
        if linked_string_index >= len(sections) or entry_size == 0:
            continue

        string_section = sections[linked_string_index]
        string_offset = string_section[4]
        string_size = string_section[5]
        if len(data) < string_offset + string_size:
            continue

        for symbol_offset in range(section_offset, section_offset + section_size, entry_size):
            if len(data) < symbol_offset + entry_size:
                break
            if elf_class == 1:
                name_offset = struct.unpack_from(f"{endian}I", data, symbol_offset)[0]
                symbol_info = data[symbol_offset + 12]
                section_index = struct.unpack_from(f"{endian}H", data, symbol_offset + 14)[0]
            else:
                name_offset = struct.unpack_from(f"{endian}I", data, symbol_offset)[0]
                symbol_info = data[symbol_offset + 4]
                section_index = struct.unpack_from(f"{endian}H", data, symbol_offset + 6)[0]

            symbol_binding = symbol_info >> 4
            if name_offset == 0 or section_index == 0 or symbol_binding not in (1, 2):
                continue
            name = read_c_string(data, string_offset + name_offset)
            if name:
                exports.update(normalize_export_name(name))
    return exports


def detect_elf_dynamic_info(data: bytes) -> tuple[set[str], set[str]]:
    if len(data) < 0x40 or not data.startswith(b"\x7fELF"):
        return set(), set()
    elf_class = data[4]
    endian = {"\x01": "<", "\x02": ">"}.get(chr(data[5]))
    if endian is None:
        return set(), set()

    if elf_class == 1:
        header_format = f"{endian}HHIIIIIHHHHHH"
        header_offset = 16
        dynamic_format = f"{endian}iI"
    elif elf_class == 2:
        header_format = f"{endian}HHIQQQIHHHHHH"
        header_offset = 16
        dynamic_format = f"{endian}qQ"
    else:
        return set(), set()

    header_size = struct.calcsize(header_format)
    if len(data) < header_offset + header_size:
        return set(), set()
    header = struct.unpack_from(header_format, data, header_offset)
    section_header_offset = header[5]
    section_header_entry_size = header[10]
    section_header_count = header[11]
    if section_header_offset == 0 or section_header_entry_size == 0:
        return set(), set()

    section_format = f"{endian}IIIIIIIIII" if elf_class == 1 else f"{endian}IIQQQQIIQQ"
    expected_section_size = struct.calcsize(section_format)
    if section_header_entry_size < expected_section_size:
        return set(), set()

    sections = []
    for index in range(section_header_count):
        offset = section_header_offset + index * section_header_entry_size
        if len(data) < offset + expected_section_size:
            return set(), set()
        sections.append(struct.unpack_from(section_format, data, offset))

    dynamic_entry_size = struct.calcsize(dynamic_format)
    dependencies: set[str] = set()
    rpaths: set[str] = set()
    for section in sections:
        if section[1] != ELF_SECTION_DYNAMIC:
            continue
        section_offset = section[4]
        section_size = section[5]
        linked_string_index = section[6]
        entry_size = section[9] or dynamic_entry_size
        if linked_string_index >= len(sections) or entry_size < dynamic_entry_size:
            continue

        string_section = sections[linked_string_index]
        string_offset = string_section[4]
        string_size = string_section[5]
        if len(data) < string_offset + string_size:
            continue

        for entry_offset in range(section_offset, section_offset + section_size, entry_size):
            if len(data) < entry_offset + dynamic_entry_size:
                break
            tag, value = struct.unpack_from(dynamic_format, data, entry_offset)
            if tag not in (ELF_DYNAMIC_NEEDED, ELF_DYNAMIC_RPATH, ELF_DYNAMIC_RUNPATH):
                continue
            text = read_c_string(data, string_offset + value)
            if not text:
                continue
            if tag == ELF_DYNAMIC_NEEDED:
                dependencies.add(text)
            else:
                rpaths.update(part for part in text.split(":") if part)
    return dependencies, rpaths


def detect_macho_thin_exports(data: bytes) -> set[str]:
    if len(data) < 28:
        return set()

    magic_be = struct.unpack_from(">I", data, 0)[0]
    magic_le = struct.unpack_from("<I", data, 0)[0]
    if magic_le == 0xFEEDFACE:
        endian = "<"
        header_size = 28
        symbol_size = 12
    elif magic_le == 0xFEEDFACF:
        endian = "<"
        header_size = 32
        symbol_size = 16
    elif magic_be == 0xFEEDFACE:
        endian = ">"
        header_size = 28
        symbol_size = 12
    elif magic_be == 0xFEEDFACF:
        endian = ">"
        header_size = 32
        symbol_size = 16
    else:
        return set()

    if len(data) < header_size:
        return set()
    command_count = struct.unpack_from(f"{endian}I", data, 16)[0]
    command_offset = header_size
    symoff = nsyms = stroff = strsize = 0
    for _ in range(command_count):
        if len(data) < command_offset + 8:
            return set()
        command, command_size = struct.unpack_from(f"{endian}II", data, command_offset)
        if command_size < 8 or len(data) < command_offset + command_size:
            return set()
        if command == MACHO_LOAD_SYMTAB and command_size >= 24:
            symoff, nsyms, stroff, strsize = struct.unpack_from(
                f"{endian}IIII", data, command_offset + 8
            )
        command_offset += command_size

    if not symoff or not nsyms or not stroff or not strsize:
        return set()
    if len(data) < stroff + strsize:
        return set()

    exports: set[str] = set()
    for index in range(nsyms):
        symbol_offset = symoff + index * symbol_size
        if len(data) < symbol_offset + symbol_size:
            break
        string_index = struct.unpack_from(f"{endian}I", data, symbol_offset)[0]
        symbol_type = data[symbol_offset + 4]
        if string_index == 0 or not (symbol_type & MACHO_N_EXT):
            continue
        if (symbol_type & MACHO_N_TYPE) == MACHO_N_UNDF:
            continue
        name = read_c_string(data, stroff + string_index)
        if name:
            exports.update(normalize_export_name(name))
    return exports


def detect_macho_exports(data: bytes) -> set[str]:
    if len(data) < 8:
        return set()

    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_be in (0xCAFEBABE, 0xCAFEBABF):
        arch_count = struct.unpack_from(">I", data, 4)[0]
        offset = 8
        exports: set[str] = set()
        for _ in range(arch_count):
            if magic_be == 0xCAFEBABF:
                if len(data) < offset + 24:
                    return exports
                slice_offset = struct.unpack_from(">Q", data, offset + 8)[0]
                slice_size = struct.unpack_from(">Q", data, offset + 16)[0]
                offset += 24
            else:
                if len(data) < offset + 20:
                    return exports
                slice_offset = struct.unpack_from(">I", data, offset + 8)[0]
                slice_size = struct.unpack_from(">I", data, offset + 12)[0]
                offset += 20
            if len(data) >= slice_offset + slice_size:
                exports.update(detect_macho_thin_exports(data[slice_offset : slice_offset + slice_size]))
        return exports

    return detect_macho_thin_exports(data)


def read_macho_load_command_string(data: bytes, command_offset: int, command_size: int, string_offset: int) -> str | None:
    if string_offset <= 0 or string_offset >= command_size:
        return None
    return read_c_string(data[: command_offset + command_size], command_offset + string_offset)


def detect_macho_thin_dynamic_info(data: bytes) -> tuple[set[str], set[str]]:
    if len(data) < 28:
        return set(), set()

    magic_be = struct.unpack_from(">I", data, 0)[0]
    magic_le = struct.unpack_from("<I", data, 0)[0]
    if magic_le == 0xFEEDFACE:
        endian = "<"
        header_size = 28
    elif magic_le == 0xFEEDFACF:
        endian = "<"
        header_size = 32
    elif magic_be == 0xFEEDFACE:
        endian = ">"
        header_size = 28
    elif magic_be == 0xFEEDFACF:
        endian = ">"
        header_size = 32
    else:
        return set(), set()

    if len(data) < header_size:
        return set(), set()

    command_count = struct.unpack_from(f"{endian}I", data, 16)[0]
    command_offset = header_size
    dependencies: set[str] = set()
    rpaths: set[str] = set()
    for _ in range(command_count):
        if len(data) < command_offset + 8:
            return dependencies, rpaths
        command, command_size = struct.unpack_from(f"{endian}II", data, command_offset)
        if command_size < 8 or len(data) < command_offset + command_size:
            return dependencies, rpaths

        bare_command = command & ~MACHO_REQ_DYLD
        if bare_command in MACHO_LOAD_DYLIB_COMMANDS and command_size >= 24:
            string_offset = struct.unpack_from(f"{endian}I", data, command_offset + 8)[0]
            dependency = read_macho_load_command_string(data, command_offset, command_size, string_offset)
            if dependency:
                dependencies.add(dependency)
        elif bare_command == MACHO_LOAD_RPATH and command_size >= 12:
            string_offset = struct.unpack_from(f"{endian}I", data, command_offset + 8)[0]
            rpath = read_macho_load_command_string(data, command_offset, command_size, string_offset)
            if rpath:
                rpaths.add(rpath)
        command_offset += command_size
    return dependencies, rpaths


def detect_macho_dynamic_info(data: bytes) -> tuple[set[str], set[str]]:
    if len(data) < 8:
        return set(), set()

    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_be in (0xCAFEBABE, 0xCAFEBABF):
        arch_count = struct.unpack_from(">I", data, 4)[0]
        offset = 8
        dependencies: set[str] = set()
        rpaths: set[str] = set()
        for _ in range(arch_count):
            if magic_be == 0xCAFEBABF:
                if len(data) < offset + 24:
                    return dependencies, rpaths
                slice_offset = struct.unpack_from(">Q", data, offset + 8)[0]
                slice_size = struct.unpack_from(">Q", data, offset + 16)[0]
                offset += 24
            else:
                if len(data) < offset + 20:
                    return dependencies, rpaths
                slice_offset = struct.unpack_from(">I", data, offset + 8)[0]
                slice_size = struct.unpack_from(">I", data, offset + 12)[0]
                offset += 20
            if len(data) >= slice_offset + slice_size:
                slice_dependencies, slice_rpaths = detect_macho_thin_dynamic_info(data[slice_offset : slice_offset + slice_size])
                dependencies.update(slice_dependencies)
                rpaths.update(slice_rpaths)
        return dependencies, rpaths

    return detect_macho_thin_dynamic_info(data)


def detect_exported_symbols(data: bytes) -> set[str]:
    return detect_pe_exports(data) or detect_elf_exports(data) or detect_macho_exports(data)


def archive_dependency_name(dependency: str) -> str:
    return dependency.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def archive_contains_dependency(names: set[str], dependency: str, platform: str) -> bool:
    dependency_name = archive_dependency_name(dependency)
    if not dependency_name:
        return False
    if platform == "win32":
        archive_names = {name.lower() for name in names}
        return dependency_name.lower() in archive_names
    return dependency_name in names


def is_allowed_linux_system_dependency(dependency: str) -> bool:
    return dependency in LINUX_SYSTEM_DEPENDENCIES or dependency.startswith("ld-linux-")


def is_allowed_windows_system_dependency(dependency: str) -> bool:
    name = archive_dependency_name(dependency).lower()
    return (
        name in WINDOWS_SYSTEM_DEPENDENCIES
        or name.startswith("api-ms-")
        or name.startswith("ext-ms-")
        or name.startswith("msvcp")
        or name.startswith("ucrtbase")
        or name.startswith("vcruntime")
    )


def is_system_dependency(platform: str, dependency: str) -> bool:
    if platform == "win32":
        return is_allowed_windows_system_dependency(dependency)
    if platform == "linux":
        return is_allowed_linux_system_dependency(dependency)
    if platform == "macos":
        return dependency.startswith(("/System/Library/", "/usr/lib/"))
    return False


def detect_binary_dependencies(data: bytes, platform: str) -> set[str]:
    if platform == "win32" and is_pe(data):
        return detect_pe_imports(data)
    if is_elf(data):
        dependencies, _ = detect_elf_dynamic_info(data)
        return dependencies
    if is_macho(data):
        dependencies, _ = detect_macho_dynamic_info(data)
        return dependencies
    return set()


def validate_dependency_closure(name: str, data: bytes, platform: str, names: set[str]) -> None:
    for dependency in sorted(detect_binary_dependencies(data, platform)):
        if is_system_dependency(platform, dependency):
            continue
        if archive_contains_dependency(names, dependency, platform):
            continue
        fail(f"{name} depends on {dependency}, which is not present in the archive")


def validate_elf_relocatability(name: str, data: bytes) -> None:
    dependencies, rpaths = detect_elf_dynamic_info(data)
    for dependency in sorted(dependencies):
        if "/" in dependency:
            fail(f"{name} has non-relocatable ELF dependency path: {dependency}")

    for rpath in sorted(rpaths):
        if rpath == "$ORIGIN" or rpath.startswith("$ORIGIN/"):
            continue
        fail(f"{name} has non-relocatable ELF RPATH/RUNPATH: {rpath}")

    if dependencies and "$ORIGIN" not in rpaths and not any(path.startswith("$ORIGIN/") for path in rpaths):
        fail(f"{name} must include $ORIGIN in ELF RPATH/RUNPATH")


def is_allowed_macho_dependency(path: str) -> bool:
    return path.startswith(("@rpath/", "@loader_path/", "@executable_path/", "/System/Library/", "/usr/lib/"))


def is_allowed_macho_rpath(path: str) -> bool:
    return path == "@loader_path" or path.startswith(("@loader_path/", "@executable_path/"))


def validate_macho_relocatability(name: str, data: bytes) -> None:
    dependencies, rpaths = detect_macho_dynamic_info(data)
    for dependency in sorted(dependencies):
        if not is_allowed_macho_dependency(dependency):
            fail(f"{name} has non-relocatable Mach-O dependency path: {dependency}")

    for rpath in sorted(rpaths):
        if not is_allowed_macho_rpath(rpath):
            fail(f"{name} has non-relocatable Mach-O RPATH: {rpath}")

    if any(dependency.startswith("@rpath/") for dependency in dependencies) and not any(
        is_allowed_macho_rpath(rpath) for rpath in rpaths
    ):
        fail(f"{name} uses @rpath dependencies but does not include a local Mach-O RPATH")


def clean_member_name(member: tarfile.TarInfo, archive_path: pathlib.Path) -> str:
    member_path = pathlib.PurePosixPath(member.name)
    if member_path.is_absolute() or ".." in member_path.parts:
        fail(f"unsafe path in {archive_path.name}: {member.name}")

    clean = member.name
    while clean.startswith("./"):
        clean = clean[2:]
    return "" if clean in ("", ".") else clean.rstrip("/")


def validate_member_name(name: str, archive_path: pathlib.Path) -> None:
    if name == ".DS_Store" or name.startswith("._"):
        fail(f"runtime archive must not contain macOS metadata files: {archive_path.name}:{name}")


def validate_link(member: tarfile.TarInfo, archive_path: pathlib.Path) -> None:
    if not (member.issym() or member.islnk()):
        return
    link_path = pathlib.PurePosixPath(member.linkname)
    if link_path.is_absolute() or ".." in link_path.parts:
        fail(f"unsafe link in {archive_path.name}: {member.name} -> {member.linkname}")
    if "/" in member.linkname.strip("/"):
        fail(f"runtime archive links must stay flat: {member.name} -> {member.linkname}")


def load_archive(archive_path: pathlib.Path) -> tuple[dict, set[str], dict[str, bytes]]:
    names: set[str] = set()
    file_data: dict[str, bytes] = {}
    manifest_data: bytes | None = None

    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            clean = clean_member_name(member, archive_path)
            validate_link(member, archive_path)
            if not clean:
                continue
            validate_member_name(clean, archive_path)
            if member.isdir():
                fail(f"runtime archive must not contain directories: {member.name}")
            if "/" in clean:
                fail(f"runtime archive must be flat: {member.name}")
            names.add(clean)
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    fail(f"{clean} is not readable")
                file_data[clean] = extracted.read()
            if clean == MANIFEST_NAME:
                manifest_data = file_data.get(clean)

    if manifest_data is None:
        fail(f"{MANIFEST_NAME} is missing")

    try:
        manifest = json.loads(manifest_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{MANIFEST_NAME} is invalid JSON: {exc}")

    if not isinstance(manifest, dict):
        fail(f"{MANIFEST_NAME} must contain a JSON object")

    return manifest, names, file_data


def require_value(manifest: dict, key: str, expected: object) -> None:
    actual = manifest.get(key)
    if actual != expected:
        fail(f"{MANIFEST_NAME} field {key!r} expected {expected!r}, got {actual!r}")


def require_flat_file_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{MANIFEST_NAME} field {label!r} must be a non-empty string")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "/" in value or "\\" in value:
        fail(f"{MANIFEST_NAME} field {label!r} must be a flat file name")
    return value


def lua_module_basename(module: str) -> str:
    return module.split(".", 1)[0]


def require_lua_modules(value: object, platform: str) -> list[str]:
    if not isinstance(value, list):
        fail(f"{MANIFEST_NAME} field 'luaModules' must be a list")

    lua_modules: list[str] = []
    seen_modules: set[str] = set()
    for module in value:
        name = require_flat_file_name(module, "luaModules")
        if name in seen_modules:
            fail(f"{MANIFEST_NAME} field 'luaModules' contains duplicate entry {name!r}")
        seen_modules.add(name)
        lua_modules.append(name)

    platform_lua_modules = expected_lua_modules(platform)
    if platform_lua_modules is not None:
        expected_modules = set(platform_lua_modules)
        if set(lua_modules) != expected_modules or len(lua_modules) != len(platform_lua_modules):
            fail(f"{MANIFEST_NAME} must list Lua modules {sorted(expected_modules)}")
        return lua_modules

    basenames = [lua_module_basename(module) for module in lua_modules]
    duplicate_basenames = sorted(
        basename for basename in set(basenames) if basenames.count(basename) > 1
    )
    if duplicate_basenames:
        fail(
            f"{MANIFEST_NAME} field 'luaModules' contains duplicate module base names "
            f"{duplicate_basenames}"
        )

    expected_basenames = set(MODULE_BASENAMES)
    if set(basenames) != expected_basenames or len(basenames) != len(MODULE_BASENAMES):
        fail(f"{MANIFEST_NAME} must list Lua modules {sorted(MODULE_BASENAMES)}")

    return lua_modules


def require_entrypoints(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        fail(f"{MANIFEST_NAME} field 'entrypoints' must be a non-empty string list")

    entrypoints: list[str] = []
    seen_entrypoints: set[str] = set()
    for entrypoint in value:
        if entrypoint in seen_entrypoints:
            fail(f"{MANIFEST_NAME} field 'entrypoints' contains duplicate entry {entrypoint!r}")
        seen_entrypoints.add(entrypoint)
        entrypoints.append(entrypoint)

    if seen_entrypoints != REQUIRED_ENTRYPOINTS or len(entrypoints) != len(REQUIRED_ENTRYPOINTS):
        fail(f"{MANIFEST_NAME} must list only entrypoints {sorted(REQUIRED_ENTRYPOINTS)}")

    return entrypoints


def require_manifest_files(value: object, archive_names: set[str]) -> list[str]:
    if not isinstance(value, list):
        fail(f"{MANIFEST_NAME} field 'files' must be a list")

    files: list[str] = []
    seen_files: set[str] = set()
    for item in value:
        name = require_flat_file_name(item, "files")
        if name in seen_files:
            fail(f"{MANIFEST_NAME} field 'files' contains duplicate entry {name!r}")
        seen_files.add(name)
        files.append(name)

    if set(files) != archive_names:
        missing = archive_names - set(files)
        extra = set(files) - archive_names
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if extra:
            details.append(f"unknown {sorted(extra)}")
        fail(f"{MANIFEST_NAME} field 'files' must match archive files: {', '.join(details)}")
    return files


def require_binary_architecture(
    name: str, data: bytes, expected_architecture: str, manifest_architecture: str
) -> None:
    binary_architectures = detect_binary_architectures(data)
    if not binary_architectures:
        fail(f"{name} does not look like a supported native binary")
    if expected_architecture not in binary_architectures:
        fail(
            f"{name} architecture expected {manifest_architecture!r}, "
            f"found {sorted(binary_architectures)}"
        )


def validate_manifest(archive_path: pathlib.Path) -> None:
    target, platform, architecture = split_archive_target(archive_path)
    manifest, names, file_data = load_archive(archive_path)

    require_value(manifest, "schemaVersion", 1)
    require_value(manifest, "name", "SimpleGraphic")
    require_value(manifest, "target", target)
    require_value(manifest, "platform", platform)
    require_value(manifest, "architecture", architecture)
    require_value(manifest, "layout", "flat")

    entry_library = require_flat_file_name(manifest.get("entryLibrary"), "entryLibrary")
    platform_entry_library = expected_entry_library(platform)
    if platform_entry_library is not None and entry_library != platform_entry_library:
        fail(
            f"{MANIFEST_NAME} field 'entryLibrary' expected "
            f"{platform_entry_library!r}, got {entry_library!r}"
        )

    require_entrypoints(manifest.get("entrypoints"))

    lua_modules = require_lua_modules(manifest.get("luaModules"), platform)
    require_manifest_files(manifest.get("files"), names)

    missing = ({entry_library, *lua_modules, MANIFEST_NAME} - names)
    if missing:
        fail(f"{archive_path.name} is missing required files: {', '.join(sorted(missing))}")

    expected_architecture = normalized_architecture(architecture)
    for required_binary in (entry_library, *sorted(lua_modules)):
        if required_binary not in file_data:
            fail(f"{required_binary} must be a regular file")
        require_binary_architecture(
            required_binary, file_data[required_binary], expected_architecture, architecture
        )

    entry_exports = detect_exported_symbols(file_data[entry_library])
    missing_entrypoints = REQUIRED_ENTRYPOINTS - entry_exports
    if missing_entrypoints:
        fail(f"{entry_library} is missing exports: {', '.join(sorted(missing_entrypoints))}")

    for name, data in sorted(file_data.items()):
        binary_architectures = detect_binary_architectures(data)
        if not binary_architectures:
            continue
        if expected_architecture not in binary_architectures:
            fail(
                f"{name} architecture expected {architecture!r}, "
                f"found {sorted(binary_architectures)}"
            )
        if is_elf(data):
            validate_elf_relocatability(name, data)
        elif is_macho(data):
            validate_macho_relocatability(name, data)
        validate_dependency_closure(name, data, platform, names)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the SimpleGraphic runtime archive contract."
    )
    parser.add_argument("archives", nargs="+", type=pathlib.Path)
    args = parser.parse_args(argv)

    for archive in args.archives:
        validate_manifest(archive)
        print(f"Verified {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
