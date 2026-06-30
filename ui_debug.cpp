// DyLua: SimpleGraphic
// (c) David Gowor, 2014
//
// Module: UI Debug
//

#include "ui_local.h"

#include <atomic>

// =======
// Classes
// =======

struct d_lineHit_s {
	char* source;
	char* name;
	int		line;
	int		count;
};

struct d_callHit_s {
	char* source;
	char* name;
	int		count;
	int		lineHitNum;
	int		lineHitSz;
	d_lineHit_s* lineHits;
};

// ===================
// ui_IDebug Interface
// ===================

class ui_debug_c : public ui_IDebug, public thread_c {
public:
	// Interface
	void	SetProfiling(bool enable) override;
	void	ToggleProfiling() override;

	// Encapsulated
	ui_debug_c(ui_main_c* ui);
	~ui_debug_c();

	ui_main_c* ui = nullptr;

	std::atomic_bool doRun{ false };
	std::atomic_bool isRunning{ false };

	std::atomic_bool profiling{ false };

	std::atomic_bool hookHold{ false };
	std::atomic_bool hookHolding{ false };

	volatile int	lineHitNum = 0;
	int		lineHitSz = 0;
	d_lineHit_s* lineHits = nullptr;

	volatile int	callHitNum = 0;
	int		callHitSz = 0;
	int		callHitInitCount = 0;
	d_callHit_s* callHits = nullptr;

	void	ThreadProc() override;
};

ui_IDebug* ui_IDebug::GetHandle(ui_main_c* ui)
{
	return new ui_debug_c(ui);
}

void ui_IDebug::FreeHandle(ui_IDebug* hnd)
{
	delete (ui_debug_c*)hnd;
}

ui_debug_c::ui_debug_c(ui_main_c* ui)
	: thread_c(ui->sys), ui(ui)
{
	profiling.store(false);

	hookHold.store(false);
	hookHolding.store(false);

	lineHitNum = 0;
	lineHitSz = 16;
	lineHits = new d_lineHit_s[lineHitSz];

	callHitNum = 0;
	callHitSz = 16;
	callHitInitCount = 0;
	callHits = new d_callHit_s[callHitSz];

	doRun.store(true);
	ThreadStart();
}

ui_debug_c::~ui_debug_c()
{
	profiling.store(false);
	while (lineHitNum || callHitNum);
	doRun.store(false);
	ThreadJoin();
	delete lineHits;
	for (int i = 0; i < callHitInitCount; i++) {
		delete callHits[i].lineHits;
	}
	delete callHits;
}

// ==============
// UI Debug Class
// ==============

// Grab UI main pointer from the registry
static ui_debug_c* GetDebugPtr(lua_State* L)
{
	lua_rawgeti(L, LUA_REGISTRYINDEX, 0);
	ui_main_c* ui = (ui_main_c*)lua_touserdata(L, -1);
	lua_pop(L, 1);
	return (ui_debug_c*)ui->debug;
}

static void debugHook(lua_State* L, lua_Debug* ar)
{
	ui_debug_c* d = GetDebugPtr(L);
	d->hookHolding.store(true);
	while (d->hookHold.load());
	d->hookHolding.store(false);
}

static int lineComp(const void* aVoid, const void* bVoid)
{
	d_lineHit_s* a = (d_lineHit_s*)aVoid;
	d_lineHit_s* b = (d_lineHit_s*)bVoid;
	if (a->count == b->count) {
		return 0;
	}
	else {
		return a->count > b->count ? -1 : 1;
	}
}

static int callComp(const void* aVoid, const void* bVoid)
{
	d_callHit_s* a = (d_callHit_s*)aVoid;
	d_callHit_s* b = (d_callHit_s*)bVoid;
	if (a->count == b->count) {
		return 0;
	}
	else {
		return a->count > b->count ? -1 : 1;
	}
}

void ui_debug_c::ThreadProc()
{
	isRunning.store(true);
	while (doRun.load()) {
		ui->sys->Sleep(1);

		if (profiling.load()) {
			if (!ui->inLua) {
				continue;
			}
			hookHold.store(true);
			lua_sethook(ui->L, &debugHook, LUA_MASKLINE, 0);
			while (profiling.load() && !hookHolding.load());
			lua_sethook(ui->L, &debugHook, 0, 0);
			if (!profiling.load()) {
				hookHold.store(false);
				continue;
			}
			lua_Debug dbg;
			memset(&dbg, 0, sizeof(dbg));
			if (lua_getstack(ui->L, 0, &dbg) && lua_getinfo(ui->L, "Sln", &dbg) && dbg.source) {
				int l;
				for (l = 0; l < lineHitNum; l++) {
					if (dbg.currentline == lineHits[l].line && !strcmp(dbg.source, lineHits[l].source)) {
						if (dbg.name && !lineHits[l].name) {
							lineHits[l].name = AllocString(dbg.name);
						}
						lineHits[l].count++;
						break;
					}
				}
				if (l == lineHitNum) {
					if (lineHitNum == lineHitSz) {
						lineHitSz <<= 1;
						trealloc(lineHits, lineHitSz);
					}
					lineHits[l].source = AllocString(dbg.source);
					lineHits[l].name = AllocString(dbg.name);
					lineHits[l].line = dbg.currentline;
					lineHits[l].count = 1;
					lineHitNum++;
				}
				const char* funcSource = dbg.source;
				const char* funcName = dbg.name;
				if (funcName && lua_getstack(ui->L, 1, &dbg) && lua_getinfo(ui->L, "Sln", &dbg) && dbg.source) {
					int c;
					for (c = 0; c < callHitNum; c++) {
						if (!strcmp(funcSource, callHits[c].source) && !strcmp(funcName, callHits[c].name)) {
							callHits[c].count++;
							break;
						}
					}
					if (c == callHitNum) {
						if (callHitNum == callHitSz) {
							callHitSz <<= 1;
							trealloc(callHits, callHitSz);
						}
						if (callHitNum == callHitInitCount) {
							callHits[c].lineHitSz = 16;
							callHits[c].lineHits = new d_lineHit_s[16];
							callHitInitCount++;
						}
						callHits[c].source = AllocString(funcSource);
						callHits[c].name = AllocString(funcName);
						callHits[c].count = 1;
						callHits[c].lineHitNum = 0;
						callHitNum++;
					}
					d_callHit_s* call = callHits + c;
					int l;
					for (l = 0; l < call->lineHitNum; l++) {
						if (dbg.currentline == call->lineHits[l].line && !strcmp(dbg.source, call->lineHits[l].source)) {
							if (dbg.name && !call->lineHits[l].name) {
								call->lineHits[l].name = AllocString(dbg.name);
							}
							call->lineHits[l].count++;
							break;
						}
					}
					if (l == call->lineHitNum) {
						if (call->lineHitNum == call->lineHitSz) {
							call->lineHitSz <<= 1;
							trealloc(call->lineHits, call->lineHitSz);
						}
						call->lineHits[l].source = AllocString(dbg.source);
						call->lineHits[l].name = AllocString(dbg.name);
						call->lineHits[l].line = dbg.currentline;
						call->lineHits[l].count = 1;
						call->lineHitNum++;
					}
				}
			}
			hookHold.store(false);
			while (hookHolding.load());
		}
		else if (lineHitNum) {
			ui->sys->con->Printf("Hot lines:\n");
			qsort(lineHits, lineHitNum, sizeof(d_lineHit_s), lineComp);
			for (int l = 0; l < lineHitNum; l++) {
				if (l < 20) {
					ui->sys->con->Printf("%s(%d) in '%s': %d\n", lineHits[l].source, lineHits[l].line, lineHits[l].name ? lineHits[l].name : "?", lineHits[l].count);
				}
				delete lineHits[l].source;
				delete lineHits[l].name;
			}
			lineHitNum = 0;
			ui->sys->con->Printf("Hot calls:\n");
			qsort(callHits, callHitNum, sizeof(d_callHit_s), callComp);
			for (int c = 0; c < callHitNum; c++) {
				qsort(callHits[c].lineHits, callHits[c].lineHitNum, sizeof(d_lineHit_s), lineComp);
				if (c < 10) {
					ui->sys->con->Printf("%s in '%s': %d\n", callHits[c].source, callHits[c].name, callHits[c].count);
				}
				for (int l = 0; l < callHits[c].lineHitNum; l++) {
					if (c < 10 && l < 5) {
						ui->sys->con->Printf("\t%s(%d) in '%s': %d\n", callHits[c].lineHits[l].source, callHits[c].lineHits[l].line, callHits[c].lineHits[l].name ? callHits[c].lineHits[l].name : "?", callHits[c].lineHits[l].count);
					}
					delete callHits[c].lineHits[l].source;
					delete callHits[c].lineHits[l].name;
				}
				delete callHits[c].source;
				delete callHits[c].name;
			}
			callHitNum = 0;
		}
	}
	isRunning.store(false);
}

void ui_debug_c::SetProfiling(bool enable)
{
	if (enable) {
		ui->sys->con->Printf("Profiling enabled.\n");
		profiling.store(true);
	}
	else {
		ui->sys->con->Printf("Profiling finished:\n");
		profiling.store(false);
		while (lineHitNum || callHitNum);
	}
}

void ui_debug_c::ToggleProfiling()
{
	SetProfiling(!profiling.load());
}
