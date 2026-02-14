# Hook System for Resource Cleanup

## Overview

The async tasks system supports lifecycle hooks for managing MCP resources (or any other shared resources that require cleanup).

**Important:** Hooks are **user-defined** and live in your runtime workspace, not in the core skill. This allows you to manage hooks for the specific MCPs and resources you have configured.

## Hook Location

Hooks should be placed in:
```
$SOLAR_TASK_ROOT/hooks/<resource-name>/
├── pre_start.sh       (optional)
├── post_complete.sh   (optional)
└── on_error.sh        (optional)
```

Default location: `sun/runtime/async-tasks/hooks/`

## Hook Types

### 1. pre_start.sh
**When:** Before task execution starts
**Purpose:** Acquire resources, check availability, create locks
**Behavior:**
- If exits with 0: Task proceeds to active
- If exits with non-0: Task is skipped (worker tries next task in queue)

**Example use cases:**
- Acquire exclusive lock for MCP resource
- Check if resource is available
- Initialize connection pools

### 2. post_complete.sh
**When:** After task completes successfully
**Purpose:** Release resources, cleanup connections, remove locks
**Behavior:**
- If exits with 0: Task moves to completed (or re-queues if recurring)
- If exits with non-0: `on_error.sh` runs, task moves to error state

**Example use cases:**
- Close browser sessions
- Release database connections
- Delete temporary files
- Remove resource locks

### 3. on_error.sh
**When:** If post_complete.sh fails OR task execution fails
**Purpose:** Emergency cleanup, force-release resources
**Behavior:**
- Always exits with 0 (uses `|| true` in caller)
- Should be idempotent and safe to run multiple times

**Example use cases:**
- Force kill processes
- Force delete locks
- Emergency resource cleanup

## Hook Arguments

All hooks receive one argument:
- `$1` - Absolute path to the task file (e.g., `/path/to/task.md`)

You can extract task metadata using:
```bash
TASK_ID=$(grep "^id:" "$1" | sed 's/^id: //' | tr -d '"')
TITLE=$(grep "^title:" "$1" | sed 's/^title: //' | tr -d '"')
```

## Timeout Support

`post_complete.sh` hooks run with configurable timeout (default: 30 seconds).

Configure in task frontmatter:
```yaml
cleanup_timeout: 60  # seconds
```

Timeout uses `gtimeout` (macOS) or `timeout` (Linux) if available.

## Resource Locks (Queue-Wait Pattern)

Pre-start hooks can implement exclusive locks to prevent concurrent resource usage.

Lock files should be stored in:
```
$SOLAR_TASK_ROOT/.locks/<resource-name>.lock
```

Lock file format (recommended):
```
<task-id>
<timestamp>
```

See hook examples for implementation.

## Creating Hooks for Your Resources

1. **Identify your resource**: What MCP or shared resource needs lifecycle management?
2. **Install hook templates**: Run `install_hooks.sh <resource-name>` to copy templates from `assets/` to your runtime workspace
3. **Customize hooks**: Edit the generated hooks in `$SOLAR_TASK_ROOT/hooks/<resource-name>/` to add your cleanup logic
4. **Test**: Configure task with `resources: "<resource-name>"` and `cleanup_required: true`

**Quick start:**
```bash
# Install templates for chrome-dev-tools MCP
bash scripts/install_hooks.sh chrome-dev-tools

# Edit the hooks to add your cleanup logic
vim $SOLAR_TASK_ROOT/hooks/chrome-dev-tools/post_complete.sh

# Configure a task to use this resource
bash scripts/set_cleanup.sh <task_id> chrome-dev-tools
```

## Security Notes

- Hooks run with the same permissions as the task worker
- Always validate inputs in hooks
- Use absolute paths in hooks (avoid relative path vulnerabilities)
- Be careful with force-kill operations in `on_error.sh`
- Hooks can access environment variables (`.env`)
