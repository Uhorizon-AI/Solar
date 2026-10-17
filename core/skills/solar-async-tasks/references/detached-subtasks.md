# Detached subtasks are unsupported

The worker always waits for declared children. `detach_subtasks: true` does not
skip waiting and grants no authority. Independent tasks are created and approved
separately; independence does not grant concurrency.

For an approved review batch with one parent synthesis, use
[task with subtasks](task-with-subtasks.md). It requires a bounded approved policy,
immutable inputs, derived provenance and the shared claim gate. Production
capacity remains 1 with reader profiles disabled.
