#include <unistd.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static int resolve_repo_root(char *buf, size_t len) {
    const char *env = getenv("SOLAR_REPO_ROOT");
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

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    char repo_root[PATH_MAX];
    char script_path[PATH_MAX];

    if (resolve_repo_root(repo_root, sizeof(repo_root)) != 0) {
        perror("resolve_repo_root");
        return 1;
    }

    snprintf(
        script_path,
        sizeof(script_path),
        "%s/core/skills/solar-system/scripts/run_orchestrator.sh",
        repo_root
    );

    char *new_argv[] = { "/bin/bash", script_path, "--once", NULL };
    execv("/bin/bash", new_argv);

    perror("execv");
    return 1;
}
