// SimpleGraphic Engine
// (c) David Gowor, 2014
//
// Module: System Main
// Platform: Windows
//

#include <fmt/chrono.h>
#include <re2/re2.h>

#include "sys_local.h"

#include "core.h"

#ifdef _WIN32
#include <eh.h>
#include <Shlobj.h>
#elif __linux__
#include <unistd.h>
#include <limits.h>
#elif __APPLE__ && __MACH__
#include <libproc.h>
#endif

#ifndef _WIN32
#include <cerrno>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <pwd.h>
#endif

#include <GLFW/glfw3.h>
#include <filesystem>
#include <map>
#include <set>
#include <thread>

#include <fmt/core.h>

// ======
// Locals
// ======

#ifdef _WIN32
static void SE_ErrorTrans(unsigned int code, EXCEPTION_POINTERS* exPtr)
{
	throw exPtr;
}
#endif
#define GLFW_HAS_GET_KEY_NAME 1

static const char* DetectArchitecture()
{
#if defined(_M_ARM64EC)
	return "arm64ec";
#elif defined(_M_X64) || defined(__x86_64__) || defined(__amd64__)
	return "x64";
#elif defined(_M_IX86) || defined(__i386__)
	return "x86";
#elif defined(_M_ARM64) || defined(__aarch64__)
	return "arm64";
#elif (defined(_M_ARM) && _M_ARM >= 7) \
	|| defined(__ARM_ARCH_7__) \
	|| defined(__ARM_ARCH_7A__) \
	|| defined(__ARM_ARCH_7R__) \
	|| defined(__ARM_ARCH_7M__) \
	|| defined(__ARM_ARCH_7EM__) \
	|| (defined(__ARM_ARCH) && __ARM_ARCH >= 7)
	return "armv7";
#elif (defined(_M_ARM) && _M_ARM == 6) \
	|| defined(__ARM_ARCH_6__) \
	|| defined(__ARM_ARCH_6J__) \
	|| defined(__ARM_ARCH_6K__) \
	|| defined(__ARM_ARCH_6Z__) \
	|| defined(__ARM_ARCH_6ZK__) \
	|| defined(__ARM_ARCH_6T2__) \
	|| defined(__ARM_ARCH_6M__) \
	|| (defined(__ARM_ARCH) && __ARM_ARCH == 6)
	return "armv6";
#elif defined(_M_ARM) || defined(__arm__)
	return "arm";
#elif defined(__riscv) && __riscv_xlen == 64
	return "riscv64";
#elif defined(__riscv) && __riscv_xlen == 32
	return "riscv32";
#elif defined(__loongarch64) || (defined(__loongarch__) && __loongarch_grlen == 64)
	return "loongarch64";
#elif defined(__loongarch32) || (defined(__loongarch__) && __loongarch_grlen == 32)
	return "loongarch32";
#elif defined(__powerpc64__) || defined(__ppc64__)
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
	return "ppc64le";
#else
	return "ppc64";
#endif
#elif defined(__powerpc__) || defined(__ppc__)
	return "ppc";
#elif defined(__mips64) || defined(__mips64__)
	return "mips64";
#elif defined(__mips__)
	return "mips";
#elif defined(__s390x__)
	return "s390x";
#elif defined(__s390__)
	return "s390";
#else
	return "unknown";
#endif
}

#ifndef _WIN32
static std::string ShellQuote(std::string_view value)
{
	std::string quoted = "'";
	for (char ch : value) {
		if (ch == '\'') {
			quoted += "'\\''";
		}
		else {
			quoted += ch;
		}
	}
	quoted += "'";
	return quoted;
}

static std::optional<std::filesystem::path> FindHomePath()
{
	if (char const* homePath = getenv("HOME"); homePath && *homePath) {
		return std::filesystem::path(homePath);
	}
	uid_t uid = getuid();
	struct passwd* pw = getpwuid(uid);
	if (pw && pw->pw_dir && *pw->pw_dir) {
		return std::filesystem::path(pw->pw_dir);
	}
	return {};
}

static bool WaitForDetachedLauncher(pid_t pid)
{
	if (pid < 0) {
		return false;
	}
	int status{};
	while (waitpid(pid, &status, 0) == -1) {
		if (errno != EINTR) {
			return false;
		}
	}
	return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}
#endif

// ===========
// Timer class
// ===========

timer_c::timer_c()
{}

void timer_c::Start()
{
	startTime = std::chrono::system_clock::now();
}

int timer_c::Get()
{
	auto curTime = std::chrono::system_clock::now();
	return (int)std::chrono::duration_cast<std::chrono::milliseconds>(curTime - startTime).count();
}

// ============
// Thread class
// ============

thread_c::thread_c(sys_IMain* sys)
{
	_sysMain = (sys_main_c*)sys;
}

unsigned long thread_c::statThreadProc(void* obj)
{
	thread_c* thread = (thread_c*)obj;
	try {
#ifdef _WIN32
		// Enable translation to catch C exceptions if debugger is not present
		if ( !thread->_sysMain->debuggerRunning ) {
			_set_se_translator(SE_ErrorTrans);
		}
#endif
		// Run thread procedure
		thread->ThreadProc();
	}
#ifdef _WIN32
	catch (EXCEPTION_POINTERS* exPtr) {
		// C exception
		PEXCEPTION_RECORD exRec = exPtr->ExceptionRecord;
		DWORD code =  exRec->ExceptionCode;
		char detail[512];
		if (code == EXCEPTION_ACCESS_VIOLATION && exRec->NumberParameters == 2) {
			sprintf_s(detail, 512, "Access violation: attempted to %s address %08Xh",
				exRec->ExceptionInformation[0]? "write to":"read from", static_cast<int>(exRec->ExceptionInformation[1]));
		} else if (code == EXCEPTION_STACK_OVERFLOW) {
			strcpy_s(detail, 512, "Stack overflow");
		} else {
			sprintf_s(detail, 512, "Error code: %08Xh", code);
		}
		char err[1024];
		sprintf_s(err, 1024, "Critical error at address %08Xh in thread %d:\n%s", static_cast<int>((ULONG_PTR)exRec->ExceptionAddress), GetCurrentThreadId(), detail);
		thread->_sysMain->threadError = AllocString(err);
	}
#else
	catch (std::exception& e) {
		thread->_sysMain->threadError = AllocString(fmt::format("Exception: {}", e.what()).c_str());
	}
#endif
	return 0;
}

void thread_c::ThreadStart(bool lowPri)
{
	std::thread t(statThreadProc, this);
#ifdef _WIN32
	HANDLE thr = t.native_handle();
	if (thr && lowPri) {
		SetThreadPriority(thr, THREAD_PRIORITY_BELOW_NORMAL);
	}
#endif
	t.detach();
}

// ===========
// File Finder
// ===========

find_c::find_c()
{}

find_c::~find_c()
{}

std::optional<std::string> BuildGlobPattern(std::filesystem::path const& glob)
{
	using namespace std::literals::string_view_literals;
	auto globStr = glob.generic_u8string();
	auto globView = std::string_view(globStr);

	// Deal with traditional "everything" wildcards.
	if (globView == "*" || globView == "*.*") {
		return {};
	}

	auto u32Str = IndexUTF8ToUTF32(globStr);
	auto& offsets = u32Str.sourceCodeUnitOffsets;

	fmt::memory_buffer buf;
	buf.reserve(globStr.size() * 3); // Decent estimate of final pattern size.

	// If no wildcards are present, test file path verbatim.
	// We use a regex rather than string comparisons to make it case-insensitive.
	if (u32Str.text.find_first_of(U"?*") == std::u32string::npos) {
		for (size_t offIdx = 0; offIdx < offsets.size(); ++offIdx) {
			int byteOffset = offsets[offIdx];
			int nextOffset = (offIdx + 1 < offsets.size()) ? offsets[offIdx + 1] : globStr.size();
			fmt::format_to(fmt::appender(buf), "[{}]", globView.substr(byteOffset, nextOffset - byteOffset));
		}
	}
	else {
		// Otherwise build a regular expression from the glob and use that to match files.
		auto it = fmt::appender(buf);
		for (size_t offIdx = 0; offIdx < offsets.size(); ++offIdx) {
			char32_t ch = u32Str.text[offIdx];
			if (ch == U'*') {
				it = fmt::format_to(it, ".*");
			}
			else if (ch == U'?') {
				*it++ = '.';
			}
			else if (U".+[]{}+()|"sv.find(ch) != std::u32string::npos) {
				// Escape metacharacters
				it = fmt::format_to(it, "\\{}", (char)ch);
			}
			else if (ch < 0x80 && std::isalnum((unsigned char)ch)) {
				*it++ = (char)ch;
			}
			else {
				// Emit as \x{10FFFF}.
				it = fmt::format_to(it, "\\x{{{:X}}}", (uint32_t)ch);
			}
		}
	}
	return to_string(buf);
}

bool GlobMatch(std::optional<std::string> const& globPattern, std::filesystem::path const& file)
{
	if (!globPattern.has_value()) {
		// Empty pattern is like "*" and "*.*".
		return true;
	}
	// Assume case-insensitive comparisons are desired.
	RE2::Options reOpts;
	reOpts.set_case_sensitive(false);
	RE2 reGlob{globPattern.value(), reOpts};

	auto fileStr = file.generic_u8string();
	return RE2::FullMatch(fileStr, reGlob);
}

bool find_c::FindFirst(std::filesystem::path const&& fileSpec)
{
	auto parent = fileSpec.parent_path();
	globPattern = BuildGlobPattern(fileSpec.filename());

	std::error_code ec;
	for (iter = std::filesystem::directory_iterator(parent, ec); iter != std::filesystem::directory_iterator{}; ++iter) {
		auto candFilename = iter->path().filename();
		if (GlobMatch(globPattern, candFilename)) {
			fileName = candFilename;
			isDirectory = iter->is_directory();
			fileSize = iter->file_size();
			auto mod = iter->last_write_time();
			modified = mod.time_since_epoch().count();
			return true;
		}
	}
	return false;
}

bool find_c::FindNext()
{
	if (iter == std::filesystem::directory_iterator{}) {
		return false;
	}

	for (++iter; iter != std::filesystem::directory_iterator{}; ++iter) {
		auto candFilename = iter->path().filename();
		if (GlobMatch(globPattern, candFilename)) {
			fileName = candFilename;
			isDirectory = iter->is_directory();
			fileSize = iter->file_size();
			auto mod = iter->last_write_time();
			modified = mod.time_since_epoch().count();
			return true;
		}
	}
	return false;
}

// ===========
// Key Mapping
// ===========


static int ImGui_ImplGlfw_TranslateUntranslatedKey(int key, int scancode)
{
#if GLFW_HAS_GET_KEY_NAME
	// GLFW 3.1+ attempts to "untranslate" keys, which goes the opposite of what every other framework does, making using lettered shortcuts difficult.
	// (It had reasons to do so: namely GLFW is/was more likely to be used for WASD-type game controls rather than lettered shortcuts, but IHMO the 3.1 change could have been done differently)
	// See https://github.com/glfw/glfw/issues/1502 for details.
	// Adding a workaround to undo this (so our keys are translated->untranslated->translated, likely a lossy process).
	// This won't cover edge cases but this is at least going to cover common cases.
	if (key >= GLFW_KEY_KP_0 && key <= GLFW_KEY_KP_EQUAL)
		return key;
	const char* key_name = glfwGetKeyName(key, scancode);
	if (key_name && key_name[0] != 0 && key_name[1] == 0)
	{
		const char char_names[] = "`-=[]\\,;\'./";
		const int char_keys[] = { GLFW_KEY_GRAVE_ACCENT, GLFW_KEY_MINUS, GLFW_KEY_EQUAL, GLFW_KEY_LEFT_BRACKET, GLFW_KEY_RIGHT_BRACKET, GLFW_KEY_BACKSLASH, GLFW_KEY_COMMA, GLFW_KEY_SEMICOLON, GLFW_KEY_APOSTROPHE, GLFW_KEY_PERIOD, GLFW_KEY_SLASH, 0 };
		if (key_name[0] >= '0' && key_name[0] <= '9') { key = GLFW_KEY_0 + (key_name[0] - '0'); }
		else if (key_name[0] >= 'A' && key_name[0] <= 'Z') { key = GLFW_KEY_A + (key_name[0] - 'A'); }
		else if (key_name[0] >= 'a' && key_name[0] <= 'z') { key = GLFW_KEY_A + (key_name[0] - 'a'); }
		else if (const char* p = strchr(char_names, key_name[0])) { key = char_keys[p - char_names]; }
	}
#endif
	return key;
}

byte sys_main_c::GlfwKeyToKey(int key, int scancode) {
	static std::map<int, byte> s_lookup = {
		{GLFW_KEY_BACKSPACE, KEY_BACK},
		{GLFW_KEY_TAB, KEY_TAB},
		{GLFW_KEY_ENTER, KEY_RETURN},
		{GLFW_KEY_LEFT_SHIFT, KEY_SHIFT},
		{GLFW_KEY_RIGHT_SHIFT, KEY_SHIFT},
		{GLFW_KEY_LEFT_CONTROL, KEY_CTRL},
		{GLFW_KEY_RIGHT_CONTROL, KEY_CTRL},
		{GLFW_KEY_LEFT_ALT, KEY_ALT},
		{GLFW_KEY_RIGHT_ALT, KEY_ALT},
		{GLFW_KEY_PAUSE, KEY_PAUSE},
		{GLFW_KEY_ESCAPE, KEY_ESCAPE},
		{GLFW_KEY_SPACE, ' '},
		{GLFW_KEY_PAGE_UP, KEY_PGUP},
		{GLFW_KEY_PAGE_DOWN, KEY_PGDN},
		{GLFW_KEY_END, KEY_END},
		{GLFW_KEY_HOME, KEY_HOME},
		{GLFW_KEY_LEFT, KEY_LEFT},
		{GLFW_KEY_UP, KEY_UP},
		{GLFW_KEY_RIGHT, KEY_RIGHT},
		{GLFW_KEY_DOWN, KEY_DOWN},
		{GLFW_KEY_PRINT_SCREEN, KEY_PRINTSCRN},
		{GLFW_KEY_INSERT, KEY_INSERT},
		{GLFW_KEY_DELETE, KEY_DELETE},
		{GLFW_KEY_NUM_LOCK, KEY_NUMLOCK},
		{GLFW_KEY_SCROLL_LOCK, KEY_SCROLL},
		{GLFW_KEY_SEMICOLON, ';'},
		// GLFW defines no plus key
		{GLFW_KEY_EQUAL, '+'},
		{GLFW_KEY_COMMA, ','},
		{GLFW_KEY_MINUS, '-'},
		{GLFW_KEY_PERIOD, '.'},
		{GLFW_KEY_SLASH, '/'},
		{GLFW_KEY_GRAVE_ACCENT, '`'},
		{GLFW_KEY_LEFT_BRACKET, '['},
		{GLFW_KEY_BACKSLASH, '\\'},
		{GLFW_KEY_RIGHT_BRACKET, ']'},
		{GLFW_KEY_APOSTROPHE, '\''},
		{GLFW_KEY_KP_0, '0'},
		{GLFW_KEY_KP_SUBTRACT, '-'},
		{GLFW_KEY_KP_ADD, '+'},
		{GLFW_KEY_KP_ENTER, KEY_RETURN},
	};

	key = ImGui_ImplGlfw_TranslateUntranslatedKey(key, scancode);

	auto I = s_lookup.find(key);
	if (I != s_lookup.end()) {
		return I->second;
	}

	if (key >= GLFW_KEY_F1 && key <= GLFW_KEY_F15) {
		return KEY_F1 + (key - GLFW_KEY_F1);
	}

	if (key >= GLFW_KEY_0 && key <= GLFW_KEY_9) {
		return '0' + (key - GLFW_KEY_0);
	}

	if (key >= GLFW_KEY_A && key <= GLFW_KEY_Z) {
		return 'a' + (key - GLFW_KEY_A);
	}

	return 0;
}

char sys_main_c::GlfwKeyExtraChar(int key) {
	static std::map<int, byte> s_lookup = {
		{GLFW_KEY_BACKSPACE, 0x8},
		{GLFW_KEY_TAB, 0x9},
		{GLFW_KEY_ENTER, 0xd},
		{GLFW_KEY_ESCAPE, 0x1b},
	};

	auto I = s_lookup.find(key);
	if (I != s_lookup.end()) {
		return I->second;
	}

	return 0;
}

// =====================
// Misc System Functions
// =====================

int sys_main_c::GetTime()
{
	auto curTime = std::chrono::system_clock::now();
	return (int)std::chrono::duration_cast<std::chrono::milliseconds>(curTime - baseTime).count();
}

void sys_main_c::Sleep(int msec)
{
	std::this_thread::sleep_for(std::chrono::milliseconds(msec));
}

bool sys_main_c::IsKeyDown(byte k)
{
	if (k < heldKeyState.size()) {
		return !!heldKeyState[k];
	}
	return false;
}

void sys_main_c::ClipboardCopy(const char* str)
{
	glfwSetClipboardString(nullptr, str);
}

char* sys_main_c::ClipboardPaste()
{
	return AllocString(glfwGetClipboardString(nullptr));
}

bool sys_main_c::SetWorkDir(std::filesystem::path const& newCwd)
{
#ifdef _WIN32
	auto changeDir = [](std::filesystem::path const& p) {
		return _wchdir(p.c_str());
	};
#else
	auto changeDir = [](std::filesystem::path const& p) {
		return _chdir(p.c_str());
	};
#endif
	if (newCwd.empty()) {
		return changeDir(basePath) != 0;
	} else {
		return changeDir(newCwd) != 0;
	}
}

void sys_main_c::SpawnProcess(std::filesystem::path cmdName, const char* argList)
{
#ifdef _WIN32
	if (!cmdName.has_extension()) {
		cmdName.replace_extension(".exe");
	}
	auto fileStr = cmdName.wstring();
	auto wideArgs = WidenUTF8String(argList);
	SHELLEXECUTEINFOW sinfo;
	memset(&sinfo, 0, sizeof(sinfo));
	sinfo.cbSize       = sizeof(sinfo);
	sinfo.fMask        = SEE_MASK_NOCLOSEPROCESS;
	sinfo.lpFile       = fileStr.c_str();
	sinfo.lpParameters = wideArgs;
	sinfo.lpVerb       = L"open";
	sinfo.nShow        = SW_SHOWMAXIMIZED;
	if ( !ShellExecuteExW(&sinfo) ) {
		sinfo.lpVerb = L"runas";
		ShellExecuteExW(&sinfo);
	}
	FreeWideString(wideArgs);
#else
	std::string command = ShellQuote(cmdName.generic_u8string());
	if (argList && *argList) {
		command += " ";
		command += argList;
	}
	pid_t pid = fork();
	if (pid == 0) {
		if (setsid() == -1) {
			_exit(127);
		}
		pid_t child = fork();
		if (child != 0) {
			_exit(child < 0 ? 127 : 0);
		}
		execl("/bin/sh", "sh", "-c", command.c_str(), (char*)nullptr);
		_exit(127);
	}
	WaitForDetachedLauncher(pid);
#endif
}

std::string GetWineHostVersion()
{
#ifdef _WIN32
	using WineHostVersionFun = void(const char** /*sysname*/, const char** /*release*/);
	HMODULE mod = GetModuleHandleA("ntdll.dll");
	if (!mod)
		return "";
	auto ptr = GetProcAddress(mod, "wine_get_host_version");
	if (!ptr)
		return "";
	auto fun = (WineHostVersionFun*)ptr;
	const char* sysname{};
	const char* release{};
	fun(&sysname, &release);
	return sysname ? sysname : "";
#else
	return "";
#endif
}

#ifdef _WIN32
const char* PlatformOpenURL(const char* url)
{
	const std::string wineHost = GetWineHostVersion();
	/*
	Wine has some loosely determined maximum length on how long of an URL
	can be, so we pick a "safe" maximum and refuse to open anything longer.
	*/
	if ((wineHost == "Linux" || wineHost == "Darwin") && strlen(url) > 1500)
		return AllocString("Did not open URL, length likely too long for the OS.");
	ShellExecuteA(NULL, "open", url, NULL, NULL, SW_SHOWDEFAULT);
	return nullptr;
}
#elif defined(__APPLE__) && defined(__MACH__)
const char* PlatformOpenURL(const char* url);
#else
const char* PlatformOpenURL(const char* url)
{
	const char* urlLauncher = getenv("SIMPLEGRAPHIC_OPEN_URL_COMMAND");
	if (!urlLauncher || !*urlLauncher) {
		urlLauncher = "xdg-open";
	}
	pid_t pid = fork();
	if (pid == 0) {
		if (setsid() == -1) {
			_exit(127);
		}
		pid_t child = fork();
		if (child != 0) {
			_exit(child < 0 ? 127 : 0);
		}
		execlp(urlLauncher, urlLauncher, url, (char*)nullptr);
		_exit(127);
	}
	if (!WaitForDetachedLauncher(pid)) {
		auto error = fmt::format("Could not launch {}.", urlLauncher);
		return AllocString(error.c_str());
	}
	return nullptr;
}
#endif

std::optional<std::string> sys_main_c::OpenURL(const char* url)
{
	if (auto err = PlatformOpenURL(url))
	{
		std::string ret = err;
		FreeString(err);
		return ret;
	}
	return {};
}

// ==============================
// System Initialisation/Shutdown
// ==============================

void sys_main_c::Error(const char *fmt, ...)
{
	if (errorRaised) return;
	errorRaised = true;

	if (initialised) {
		video->SetVisible(false);
		conWin->SetVisible(true);
	}

	va_list va;
	va_start(va, fmt);
#ifdef _WIN32
	char msg[4096];
	vsprintf_s(msg, 4096, fmt, va);
#else
	char* msg{};
	int msgLen = vasprintf(&msg, fmt, va);
#endif
	va_end(va);
#ifdef _WIN32
	con->Printf("\n--- ERROR ---\n%s", msg);
#else
	con->Printf("\n--- ERROR ---\n%s", (msgLen >= 0 && msg) ? msg : "Could not format error message");
#endif
#ifndef _WIN32
	free(msg);
#endif

	exitFlag = false;
	while (exitFlag == false) {
		Sleep(50);
	}

#ifdef _MEMTRAK_H
	_memTrak_suppressReport = true;
#endif
#ifdef _WIN32
	ExitProcess(0);
#else
	std::exit(0);
#endif
}

void sys_main_c::Exit(const char* msg)
{
	if (initialised) {
		video->SetVisible(false);
	}
	FreeString(exitMsg);
	exitMsg = msg? AllocString(msg) : NULL;
	if (exitMsg) {
		conWin->SetVisible(true);
	}
	exitFlag = true;
}

void sys_main_c::Restart()
{
	video->SetVisible(false);
	conWin->SetVisible(true);
	restartFlag = true;
	FreeString(exitMsg);
	exitMsg = NULL;
	exitFlag = true;
}

std::filesystem::path FindBasePath()
{
	std::filesystem::path progPath;
#ifdef _WIN32
	std::vector<wchar_t> basePath(1u << 16);
	GetModuleFileNameW(NULL, basePath.data(), basePath.size());
	progPath = basePath.data();
#elif __linux__
	char basePath[PATH_MAX];
	ssize_t len = ::readlink("/proc/self/exe", basePath, sizeof(basePath));
	if (len == -1 || len == sizeof(basePath))
		len = 0;
	basePath[len] = '\0';
	progPath = basePath;
#elif __APPLE__ && __MACH__
	pid_t pid = getpid();
	char basePath[PROC_PIDPATHINFO_MAXSIZE]{};
	proc_pidpath(pid, basePath, sizeof(basePath));
	progPath = basePath;
#endif
	if (progPath.empty()) {
		return weakly_canonical(std::filesystem::current_path());
	}
	progPath = weakly_canonical(progPath);
	return progPath.parent_path();
}

std::tuple<std::optional<std::filesystem::path>, std::optional<std::string>> FindUserPath()
{
#ifdef _WIN32
	PWSTR osPath{};
	HRESULT hr = SHGetKnownFolderPath(FOLDERID_Documents, KF_FLAG_DEFAULT, nullptr, &osPath);
	if (FAILED(hr)) {
		// The path may be inaccessible due to malfunctioning cloud providers.
		CoTaskMemFree(osPath);
		return std::make_tuple(std::optional<std::filesystem::path>{}, std::optional<std::string>{"Could not obtain Documents path from Windows"});
	}
	std::wstring pathStr = osPath;
	CoTaskMemFree(osPath);
	std::filesystem::path path(pathStr);
	return std::make_tuple(std::optional<std::filesystem::path>{weakly_canonical(path)}, std::optional<std::string>{});
#else
#if defined(__APPLE__) && defined(__MACH__)
	if (auto homePath = FindHomePath()) {
		return std::make_tuple(std::optional<std::filesystem::path>{*homePath / "Library/Application Support"}, std::optional<std::string>{});
	}
	return std::make_tuple(std::optional<std::filesystem::path>{}, std::optional<std::string>{"Could not determine home directory for macOS user data path"});
#else
	if (char const* data_home_path = getenv("XDG_DATA_HOME")) {
		return std::make_tuple(std::optional<std::filesystem::path>{data_home_path}, std::optional<std::string>{});
	}
	if (auto homePath = FindHomePath()) {
		return std::make_tuple(std::optional<std::filesystem::path>{*homePath / ".local/share"}, std::optional<std::string>{});
	}
	return std::make_tuple(std::optional<std::filesystem::path>{}, std::optional<std::string>{"Could not determine home directory for user data path"});
#endif
#endif
}

sys_main_c::sys_main_c()
	: heldKeyState(KEY_SCROLL + 1, (uint8_t)0)
{
	architecture = DetectArchitecture();
	x64 = architecture == "x64";
#ifdef _DEBUG
	debug = true;
#else
	debug = false;
#endif
#ifdef _WIN32
	debuggerRunning = IsDebuggerPresent() == TRUE;
#else
	debuggerRunning = false;
#endif
	processorCount = std::thread::hardware_concurrency();

	// Set the local system information
	basePath = FindBasePath();
	std::tie(userPath, userPathReason) = FindUserPath();
}

bool sys_main_c::Run(int argc, char** argv)
{
	initialised = false;
	exitFlag = false;
	restartFlag = false;
	exitMsg = NULL;
	threadError = NULL;
	errorRaised = false;
	baseTime = std::chrono::system_clock::now();

	SetWorkDir();

	// Get system interfaces
	con = IConsole::GetHandle();
	conWin = sys_IConsole::GetHandle(this);
	video = sys_IVideo::GetHandle(this);
	core = core_IMain::GetHandle(this);

	// Print some handy information
	con->Printf(CFG_VERSION" %s %s, built " __DATE__ "\n", architecture.c_str(), debug? "Debug":"Release");
	if (debuggerRunning) {
		con->Printf("Debugger is present.\n");
	}
	con->Printf("\n");

	initialised = true;

	try {
#ifdef _WIN32
		// Enable translation to catch C exceptions if debugger is not present
		if ( !debuggerRunning ) {
			_set_se_translator(SE_ErrorTrans);
		}
#endif

		// Initialise engine
		core->Init(argc, argv);

		// Run frame loop
		while (exitFlag == false) {
			if (minimized) {
				glfwWaitEventsTimeout(0.1);
			}
			else {
				glfwPollEvents();
			}
			auto wnd = (GLFWwindow*)video->GetWindowHandle();
			if (glfwWindowShouldClose(wnd)) {
				Exit();
				break;
			}
			core->Frame();

			if (threadError) {
				Error(threadError);
			}
		}

		// Shutdown engine
		core->Shutdown();
	}
#ifdef _WIN32
	catch (EXCEPTION_POINTERS* exPtr) {
		// C exception
		PEXCEPTION_RECORD exRec = exPtr->ExceptionRecord;
		DWORD code =  exRec->ExceptionCode;
		char detail[512];
		if (code == EXCEPTION_ACCESS_VIOLATION && exRec->NumberParameters == 2) {
			sprintf_s(detail, 512, "Access violation: attempted to %s address %08Xh",
				exRec->ExceptionInformation[0]? "write to":"read from", static_cast<int>(exRec->ExceptionInformation[1]));
		} else if (code == EXCEPTION_STACK_OVERFLOW) {
			strcpy_s(detail, 512, "Stack overflow");
		} else {
			sprintf_s(detail, 512, "Error code: %08Xh", code);
		}
		Error("Critical error at address %08Xh:\n%s", static_cast<int>((ULONG_PTR)exRec->ExceptionAddress), detail);
	}
#else
	catch (std::exception& e) {
		Error("Exception: %s", e.what());
	}
#endif

	if (exitMsg) {
		exitFlag = false;
		video->SetVisible(false);
		conWin->SetVisible(true);
		if (exitMsg) {
			con->Printf("\n%s", exitMsg);
			FreeString(exitMsg);
			exitMsg = NULL;
		}
		while (exitFlag == false) {
			Sleep(50);
		}
	}

	initialised = false;

	// Release system interfaces
	core_IMain::FreeHandle(core);
	sys_IVideo::FreeHandle(video);
	sys_IConsole::FreeHandle(conWin);
	IConsole::FreeHandle(con);

	return restartFlag;
}
