cmake_minimum_required(VERSION 3.21)
project(SimpleGraphic C CXX)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if (POLICY CMP0207)
    cmake_policy(SET CMP0207 NEW)
endif ()

option(SIMPLEGRAPHIC_USE_BUNDLED_VCPKG "Use the bundled vcpkg checkout when no toolchain has already configured vcpkg." ${PROJECT_IS_TOP_LEVEL})
option(SIMPLEGRAPHIC_INSTALL_RUNTIME_DEPENDENCIES "Install shared-library runtime dependencies next to SimpleGraphic." ON)

if (APPLE)
    enable_language(OBJCXX)
endif ()

if (MSVC)
    add_compile_options("/Zi")
    add_link_options("/DEBUG:FULL")
endif ()

list(APPEND CMAKE_MODULE_PATH "${PROJECT_SOURCE_DIR}/cmake")

if (SIMPLEGRAPHIC_USE_BUNDLED_VCPKG
        AND NOT DEFINED VCPKG_INSTALLED_DIR
        AND EXISTS "${PROJECT_SOURCE_DIR}/vcpkg/scripts/buildsystems/vcpkg.cmake")
    include("${PROJECT_SOURCE_DIR}/vcpkg/scripts/buildsystems/vcpkg.cmake")
endif ()

set(SIMPLEGRAPHIC_INSTALL_RPATH)
if (APPLE)
    set(SIMPLEGRAPHIC_INSTALL_RPATH "@loader_path")
elseif (UNIX)
    set(SIMPLEGRAPHIC_INSTALL_RPATH "$ORIGIN")
endif ()

function(simplegraphic_apply_shared_defaults target_name)
    if (SIMPLEGRAPHIC_INSTALL_RPATH)
        set_target_properties(${target_name} PROPERTIES
            INSTALL_RPATH "${SIMPLEGRAPHIC_INSTALL_RPATH}"
        )
    endif ()
endfunction()

function(simplegraphic_apply_lua_module_defaults target_name output_name)
    simplegraphic_apply_shared_defaults(${target_name})
    set_target_properties(${target_name} PROPERTIES
        OUTPUT_NAME "${output_name}"
        PREFIX ""
    )
endfunction()

function(simplegraphic_install_target target_name)
    if (SIMPLEGRAPHIC_INSTALL_RUNTIME_DEPENDENCIES)
        install(TARGETS ${target_name}
            RUNTIME_DEPENDENCY_SET SimpleGraphicRuntimeDependencies
            RUNTIME DESTINATION "."
            LIBRARY DESTINATION "."
        )
    else ()
        install(TARGETS ${target_name}
            RUNTIME DESTINATION "."
            LIBRARY DESTINATION "."
        )
    endif ()
endfunction()

set(CMAKE_INSTALL_SYSTEM_RUNTIME_DESTINATION ".")
include(InstallRequiredSystemLibraries)
add_subdirectory(dep/glm)

set(SIMPLEGRAPHIC_SOURCES
    "config.h"
    "dep/stb/stb_image.h"
    "dep/stb/stb_image_resize.h"
    "dep/stb/stb_image_write.h"
    "engine/common.h"
    "engine/common/base64.c"
    "engine/common/base64.h"
    "engine/common/common.cpp"
    "engine/common/console.cpp"
    "engine/common/console.h"
    "engine/common/keylist.h"
    "engine/common/memtrak3.cpp"
    "engine/common/memtrak3.h"
    "engine/common/streams.cpp"
    "engine/common/streams.h"
    "engine/core/core_compress.cpp"
    "engine/core/core_compress.h"
    "engine/core/core_config.cpp"
    "engine/core/core_config.h"
    "engine/core/core_image.cpp"
    "engine/core/core_image.h"
    "engine/core/core_main.cpp"
    "engine/core/core_main.h"
    "engine/core/core_tex_manipulation.cpp"
    "engine/core/core_tex_manipulation.h"
    "engine/core/core_video.cpp"
    "engine/core/core_video.h"
    "engine/render/r_font.cpp"
    "engine/render/r_font.h"
    "engine/render/r_main.cpp"
    "engine/render/r_main.h"
    "engine/render/r_texture.cpp"
    "engine/render/r_texture.h"
    "engine/system/win/sys_local.h"
    "engine/system/win/sys_main.cpp"
    "engine/system/win/sys_opengl.cpp"
    "engine/system/win/sys_video.cpp"
    "engine/system/sys_console.h"
    "engine/system/sys_main.h"
    "engine/system/sys_opengl.h"
    "engine/system/sys_video.h"
    "win/entry.cpp"
    "ui.h"
    "ui_api.cpp"
    "ui_console.cpp"
    "ui_console.h"
    "ui_debug.cpp"
    "ui_debug.h"
    "ui_local.h"
    "ui_main.cpp"
    "ui_main.h"
    "ui_subscript.cpp"
    "ui_subscript.h"
)

set(SIMPLEGRAPHIC_PLATFORM_SOURCES)
if (APPLE)
    list(APPEND SIMPLEGRAPHIC_PLATFORM_SOURCES
        "engine/system/win/sys_macos.mm"
    )
endif()

if (WIN32)
    list(APPEND SIMPLEGRAPHIC_PLATFORM_SOURCES
        "engine/system/win/sys_console.cpp"
        "SimpleGraphic.rc"
    )
else()
    list(APPEND SIMPLEGRAPHIC_PLATFORM_SOURCES
        "engine/system/win/sys_console_unix.cpp"
    )
endif()

add_library(SimpleGraphic SHARED
    ${SIMPLEGRAPHIC_SOURCES}
    ${SIMPLEGRAPHIC_PLATFORM_SOURCES}
)
simplegraphic_apply_shared_defaults(SimpleGraphic)
target_compile_definitions(SimpleGraphic
    PRIVATE
    "UNICODE"
    "_CRT_SECURE_NO_DEPRECATE"
    "_CRT_SECURE_NO_WARNINGS"
    "_SCL_SECURE_NO_DEPRECATE"
    "_SCL_SECURE_NO_WARNINGS"
    "GLFW_INCLUDE_NONE"
    "GL_SILENCE_DEPRECATION"
    "SIMPLEGRAPHIC_EXPORTS"
)

target_include_directories(SimpleGraphic
    PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/engine"
)

find_package(unofficial-angle CONFIG REQUIRED)
find_package(CURL CONFIG REQUIRED)
find_package(fmt CONFIG REQUIRED)
find_package(glfw3 CONFIG REQUIRED)
find_package(gli CONFIG REQUIRED)
find_package(LuaJIT REQUIRED)
find_package(Microsoft.GSL CONFIG REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(re2 CONFIG REQUIRED)
find_package(sol2 CONFIG REQUIRED)
find_package(Threads REQUIRED)
find_package(zstd REQUIRED)
find_package(ZLIB REQUIRED)
find_package(WebP REQUIRED)

if (TARGET zstd::libzstd_shared)
    set(SIMPLEGRAPHIC_ZSTD_TARGET zstd::libzstd_shared)
elseif (TARGET zstd::libzstd_static)
    set(SIMPLEGRAPHIC_ZSTD_TARGET zstd::libzstd_static)
elseif (TARGET zstd::libzstd)
    set(SIMPLEGRAPHIC_ZSTD_TARGET zstd::libzstd)
else ()
    message(FATAL_ERROR "Could not find a usable zstd CMake target.")
endif ()

add_library(cmp_core STATIC
    dep/compressonator/cmp_core/source/cmp_core.cpp
    dep/compressonator/cmp_core/source/cmp_core.h
    dep/compressonator/cmp_core/shaders/bc3_encode_kernel.cpp
    dep/compressonator/cmp_core/shaders/bc7_encode_kernel.cpp
)

target_include_directories(cmp_core PRIVATE
    dep/compressonator/applications/_libs/cmp_math
)

target_include_directories(cmp_core PUBLIC
    dep/compressonator/cmp_core/shaders
    dep/compressonator/cmp_core/source
)

add_library(imgui STATIC
    dep/imgui/imconfig.h
    dep/imgui/imgui.cpp
    dep/imgui/imgui.h
    dep/imgui/imgui_demo.cpp
    dep/imgui/imgui_draw.cpp
    dep/imgui/imgui_internal.h
    dep/imgui/imgui_tables.cpp
    dep/imgui/imgui_widgets.cpp
    dep/imgui/imstb_rectpack.h
    dep/imgui/imstb_textedit.h
    dep/imgui/imstb_truetype.h
    dep/imgui/backends/imgui_impl_glfw.cpp
    dep/imgui/backends/imgui_impl_glfw.h
    dep/imgui/backends/imgui_impl_opengl3.cpp
    dep/imgui/backends/imgui_impl_opengl3.h
    dep/imgui/backends/imgui_impl_opengl3_loader.h
    dep/imgui/misc/cpp/imgui_stdlib.cpp
    dep/imgui/misc/cpp/imgui_stdlib.h
)

target_compile_definitions(imgui PUBLIC
    "IMGUI_IMPL_OPENGL_ES2"
)

target_include_directories(imgui PUBLIC
    dep/imgui
    dep/imgui/backends
    dep/imgui/misc/cpp
)

target_link_libraries(imgui PUBLIC
    unofficial::angle::libGLESv2
    glfw
)

target_include_directories(SimpleGraphic
    PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/dep/glad/include
    ${CMAKE_CURRENT_SOURCE_DIR}/dep/stb
)

if (CMAKE_SYSTEM_NAME MATCHES "Linux")
    target_link_options(SimpleGraphic
        PRIVATE
        "-export-dynamic"
    )
endif ()

if (WIN32)
    if (MSVC)
        target_compile_options(SimpleGraphic
            PRIVATE
            "/EHa"
        )
    endif ()
    target_compile_definitions(SimpleGraphic
        PRIVATE
        "_CRT_SECURE_NO_DEPRECATE=1"
        "_CRT_SECURE_NO_WARNINGS=1"
        "_SCL_SECURE_NO_DEPRECATE=1"
        "_SCL_SECURE_NO_WARNINGS=1"
    )
    if (MSVC)
        target_link_libraries(SimpleGraphic
            PRIVATE
            "winmm.lib"
        )
    else ()
        target_link_libraries(SimpleGraphic
            PRIVATE
            winmm
        )
    endif ()
endif ()

if (APPLE)
    find_library(CORE_FOUNDATION_LIBRARY CoreFoundation)
    find_library(APPLICATION_SERVICES_LIBRARY ApplicationServices)
    target_link_libraries(SimpleGraphic
        PRIVATE
        ${CORE_FOUNDATION_LIBRARY}
        ${APPLICATION_SERVICES_LIBRARY}
    )
endif ()

target_link_libraries(SimpleGraphic
    PRIVATE
    unofficial::angle::libEGL
    unofficial::angle::libGLESv2
    cmp_core
    fmt::fmt
    glfw
    gli
    glm::glm
    imgui
    LuaJIT::LuaJIT
    Microsoft.GSL::GSL
    re2::re2
    Threads::Threads
    WebP::webpdecoder
    ZLIB::ZLIB
    ${SIMPLEGRAPHIC_ZSTD_TARGET}
)

simplegraphic_install_target(SimpleGraphic)

if (WIN32)
    set(DEPS_DIR "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}")

    if (NOT VCPKG_TARGET_TRIPLET MATCHES "-release")
        find_file(LuaJIT_DLL_DEBUG NAMES "lua51.dll"
            PATHS "${DEPS_DIR}" PATH_SUFFIXES "debug/bin" REQUIRED NO_DEFAULT_PATH)
        find_file(ZLIB_DLL_DEBUG NAMES "zlibd1.dll"
            PATHS "${DEPS_DIR}" PATH_SUFFIXES "debug/bin" REQUIRED NO_DEFAULT_PATH)

        install(FILES
            ${LuaJIT_DLL_DEBUG}
            ${ZLIB_DLL_DEBUG}
            DESTINATION "."
            CONFIGURATIONS Debug
        )
    endif ()

    find_file(LuaJIT_DLL_RELEASE NAMES "lua51.dll"
        PATHS "${DEPS_DIR}" PATH_SUFFIXES "bin" REQUIRED NO_DEFAULT_PATH)
    find_file(ZLIB_DLL_RELEASE NAMES "zlib1.dll"
        PATHS "${DEPS_DIR}" PATH_SUFFIXES "bin" REQUIRED NO_DEFAULT_PATH)

    install(FILES
        ${LuaJIT_DLL_RELEASE}
        ${ZLIB_DLL_RELEASE}
        DESTINATION "."
        CONFIGURATIONS Release MinSizeRel RelWithDebInfo
    )
endif ()


# lcurl module

set(LCURL_SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/libs/Lua-cURLv3)
file(GLOB LCURL_SOURCES ${LCURL_SOURCE_DIR}/src/**.c)
add_library(lcurl MODULE ${LCURL_SOURCES})
simplegraphic_apply_lua_module_defaults(lcurl lcurl)

target_include_directories(lcurl
    PRIVATE
    ${LCURL_SOURCE_DIR}/src
)

target_link_libraries(lcurl
    PRIVATE
    CURL::libcurl
    LuaJIT::LuaJIT
)

simplegraphic_install_target(lcurl)

# luautf8 module

add_library(lua-utf8 MODULE libs/luautf8/lutf8lib.c)
simplegraphic_apply_lua_module_defaults(lua-utf8 lua-utf8)

if (WIN32)
    target_compile_definitions(lua-utf8
        PRIVATE
        LUA_BUILD_AS_DLL
    )
endif ()
if (NOT MSVC)
    target_compile_options(lua-utf8
        PRIVATE
        -include limits.h
    )
endif ()

target_include_directories(lua-utf8
    PRIVATE
)

target_link_libraries(lua-utf8
    PRIVATE
    LuaJIT::LuaJIT
)

simplegraphic_install_target(lua-utf8)

# luasocket module

set(LUASOCKET_SOURCES
   "libs/luasocket/src/auxiliar.c"
   "libs/luasocket/src/buffer.c"
   "libs/luasocket/src/compat.c"
   "libs/luasocket/src/except.c"
   "libs/luasocket/src/inet.c"
   "libs/luasocket/src/io.c"
   "libs/luasocket/src/luasocket.c"
   "libs/luasocket/src/options.c"
   "libs/luasocket/src/select.c"
   "libs/luasocket/src/tcp.c"
   "libs/luasocket/src/timeout.c"
   "libs/luasocket/src/udp.c"
)

if (WIN32)
    list(APPEND LUASOCKET_SOURCES "libs/luasocket/src/wsocket.c")
else ()
    list(APPEND LUASOCKET_SOURCES "libs/luasocket/src/usocket.c")
endif ()

add_library(luasocket MODULE ${LUASOCKET_SOURCES})
simplegraphic_apply_lua_module_defaults(luasocket socket)

target_include_directories(luasocket
    PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/libs/luasocket/src
)

target_link_libraries(luasocket
    PRIVATE
    LuaJIT::LuaJIT
)

if (WIN32)
    target_link_libraries(luasocket
        PRIVATE
        wsock32
        ws2_32
    )
endif ()

simplegraphic_install_target(luasocket)

# lzip module

add_library(lzip MODULE libs/LZip/lzip.cpp)
simplegraphic_apply_lua_module_defaults(lzip lzip)

target_include_directories(lzip
    PRIVATE
)

target_link_libraries(lzip
    PRIVATE
    LuaJIT::LuaJIT
    ZLIB::ZLIB
)

simplegraphic_install_target(lzip)

if (SIMPLEGRAPHIC_INSTALL_RUNTIME_DEPENDENCIES)
    install(RUNTIME_DEPENDENCY_SET SimpleGraphicRuntimeDependencies
        DESTINATION "."
        PRE_EXCLUDE_REGEXES
            [[api-ms-.*]]
            [[ext-ms-.*]]
            [[AzureAttest.*[.]dll]]
            [[HvsiFileTrust[.]dll]]
            [[PdmUtilities[.]dll]]
            [[WTDSENSOR[.]dll]]
            [[wpaxholder[.]dll]]
            [[wtdccm[.]dll]]
        POST_EXCLUDE_REGEXES
            [[.*[\\/]Windows[\\/]System32[\\/].*]]
            [[.*[\\/]Windows[\\/]SysWOW64[\\/].*]]
            [[.*[\\/]Windows[\\/]WinSxS[\\/].*]]
            [[^/System/Library/.*]]
            [[^/usr/lib/.*]]
            [[^/usr/lib64/.*]]
            [[^/lib/.*]]
            [[^/lib64/.*]]
    )
endif ()
