#pragma once

#ifdef __cplusplus
extern "C" {
#endif

enum { LAUNCHER_QUIT = 0, LAUNCHER_PLAY = 1 };

int launcher_run(const char *exefs, const char *romfs);

#ifdef __cplusplus
}
#endif
