#!/bin/bash
#
# update-faa-charts.sh — Thin wrapper for backwards compatibility.
# Delegates to update-charts.sh faa.
#
exec "$(dirname "$0")/update-charts.sh" faa "$@"
