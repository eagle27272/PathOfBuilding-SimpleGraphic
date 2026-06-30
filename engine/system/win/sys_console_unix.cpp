// SimpleGraphic Engine
// (c) David Gowor, 2014
//
// Module: System Console
// Platform: Windows
//

#include "sys_local.h"

#include <atomic>
#include <chrono>
#include <iostream>
#include <thread>

// ======================
// sys_IConsole Interface
// ======================

class sys_console_c: public sys_IConsole, public conPrintHook_c, public thread_c {
public:
	// Interface
	void	SetVisible(bool show);
	bool	IsVisible();
	void	SetForeground();
	void	SetTitle(const char* title);

	// Encapsulated
	sys_console_c(sys_IMain* sysHnd);
	~sys_console_c();

	sys_main_c* sys = nullptr;

	std::atomic_bool doRun{ false };
	std::atomic_bool isRunning{ false };

	void	RunMessages(void* = nullptr);
	void	ThreadProc();

	void	Print(const char* text);
	void	CopyToClipboard();

	void	ConPrintHook(const char* text);
	void	ConPrintClear();
};

sys_IConsole* sys_IConsole::GetHandle(sys_IMain* sysHnd)
{
	return new sys_console_c(sysHnd);
}

void sys_IConsole::FreeHandle(sys_IConsole* hnd)
{
	delete (sys_console_c*)hnd;
}

sys_console_c::sys_console_c(sys_IMain* sysHnd)
	: conPrintHook_c(sysHnd->con), sys((sys_main_c*)sysHnd), thread_c(sysHnd)
{
	isRunning.store(false);
	doRun.store(true);

	ThreadStart(true);
	while (!isRunning.load()) {
		std::this_thread::yield();
	}
}

void sys_console_c::RunMessages(void*)
{}

void sys_console_c::ThreadProc()
{
	// Flush any messages created
	RunMessages();

	InstallPrintHook();

	isRunning.store(true);
	while (doRun.load()) {
		RunMessages();
		sys->Sleep(1);
	}

	RemovePrintHook();

	isRunning.store(false);
}

sys_console_c::~sys_console_c()
{
	doRun.store(false);
	ThreadJoin();
}

// ==============
// System Console
// ==============

void sys_console_c::SetVisible(bool show)
{}

void sys_console_c::SetForeground()
{}

bool sys_console_c::IsVisible()
{
	return true;
}

void sys_console_c::SetTitle(const char* title)
{}

void sys_console_c::Print(const char* text)
{
	int escLen;

	// Find the required buffer length
	int len = 0;
	for (int b = 0; text[b]; b++) {
		if (text[b] == '\n') {
			// Newline takes 1 character
			len+= 1;
		} else if ((escLen = IsColorEscape(&text[b]))) {
			// Skip colour escapes
			b+= escLen - 1;
		} else {
			len++;
		}
	}

	// Parse into the buffer
	char* winText = AllocStringLen(len);
	char* p = winText;
	for (int b = 0; text[b]; b++) {
		if (text[b] == '\n') {
			// Append newline
			*(p++) = '\n';
		} else if ((escLen = IsColorEscape(&text[b]))) {
			// Skip colour escapes
			b+= escLen - 1;
		} else {
			// Add character
			*(p++) = text[b];
		}
	}

	// Append to the output
	std::cerr << winText << std::flush;
	FreeString(winText);
}

void sys_console_c::CopyToClipboard()
{}

void sys_console_c::ConPrintHook(const char* text)
{
	Print(text);
}

void sys_console_c::ConPrintClear()
{}
