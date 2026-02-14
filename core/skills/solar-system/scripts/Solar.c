#include <unistd.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>

int main(int argc, char *argv[]) {
    char exe_path[PATH_MAX];
    char script_path[PATH_MAX];
    
    // Get the path of the current executable
    if (realpath(argv[0], exe_path) == NULL) {
        perror("realpath");
        return 1;
    }
    
    // Calculate the script path (adjacent to this executable)
    char *dir = dirname(exe_path);
    snprintf(script_path, sizeof(script_path), "%s/solar_orchestrator.sh", dir);
    
    // Prepare arguments for execv
    // argv[0] should be the script name or a custom name
    // We pass the original arguments as well
    
    // Allocate new argv array: [bash, script_path, --once, NULL]
    // The orchestration script expects --once
    char *new_argv[] = { "/bin/bash", script_path, "--once", NULL };
    
    // Execute the script using bash
    // We use /bin/bash explicitly to ensure compatibility
    execv("/bin/bash", new_argv);
    
    // If execv returns, it failed
    perror("execv");
    return 1;
}
