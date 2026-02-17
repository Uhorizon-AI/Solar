#!/bin/bash

# Create a new draft task

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

TITLE="$1"
DESCRIPTION="$2"

if [ -z "$TITLE" ]; then
    echo "Usage: $0 \"Task Title\" [\"Description\"]"
    exit 1
fi

ID=$(generate_id)
FILENAME="$(build_task_filename "$DIR_DRAFTS" "$TITLE")"

cat > "$FILENAME" <<EOF
---
id: "$ID"
title: "$TITLE"
created: "$(date -Iseconds)"
status: draft
priority: normal
---

# $TITLE

$DESCRIPTION

EOF

echo "Task created: $FILENAME"
echo "ID: $ID"
