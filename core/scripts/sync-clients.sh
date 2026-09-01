#!/usr/bin/env bash
exec bash "$(dirname "$0")/_shim_exec.sh" ../skills/solar-client/scripts/sync-clients.sh "$@"
