#include <unistd.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static int resolve_workspace(char *buf, size_t len) {
    const char *env = getenv("SOLAR_WORKSPACE");
    if (env != NULL && env[0] != '\0') {
        if (strlen(env) >= len) {
            return -1;
        }
        strncpy(buf, env, len - 1);
        buf[len - 1] = '\0';
        return 0;
    }
    if (getcwd(buf, len) == NULL) {
        return -1;
    }
    return 0;
}

static int path_exists(const char *path) {
    return access(path, F_OK) == 0;
}

static int resolve_orchestrator_script(char *buf, size_t len, const char *workspace) {
    const char *root = getenv("SOLAR_ROOT");
    if (root != NULL && root[0] != '\0') {
        if ((size_t)snprintf(buf, len, "%s/core/skills/solar-system/scripts/run_orchestrator.sh", root) >= len) {
            return -1;
        }
        return 0;
    }
    if ((size_t)snprintf(buf, len, "%s/solar/core/skills/solar-system/scripts/run_orchestrator.sh", workspace) < len
        && path_exists(buf)) {
        return 0;
    }
    if ((size_t)snprintf(buf, len, "%s/core/skills/solar-system/scripts/run_orchestrator.sh", workspace) >= len) {
        return -1;
    }
    return 0;
}

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    char workspace[PATH_MAX];
    char script_path[PATH_MAX];

    if (resolve_workspace(workspace, sizeof(workspace)) != 0) {
        perror("resolve_workspace");
        return 1;
    }

    if (resolve_orchestrator_script(script_path, sizeof(script_path), workspace) != 0) {
        fprintf(stderr, "resolve_orchestrator_script: path too long\n");
        return 1;
    }

    char *new_argv[] = { "/bin/bash", script_path, "--once", NULL };
    execv("/bin/bash", new_argv);

    perror("execv");
    return 1;
}
