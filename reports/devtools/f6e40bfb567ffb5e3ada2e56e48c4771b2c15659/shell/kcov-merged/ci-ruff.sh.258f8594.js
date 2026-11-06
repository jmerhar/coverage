var data = {lines:[
{"lineNum":"    1","line":"#!/usr/bin/env bash"},
{"lineNum":"    2","line":"# Lint and format-check all the Python in the repository with ruff."},
{"lineNum":"    3","line":"#"},
{"lineNum":"    4","line":"# One ruff.toml at the root covers every project, its tests and its scripts; it extends the shared"},
{"lineNum":"    5","line":"# base, .devtools/config/ruff.toml. CI runs this with the runner\'s ruff on PATH, and a local run"},
{"lineNum":"    6","line":"# names the virtualenv\'s through RUFF."},
{"lineNum":"    7","line":"#"},
{"lineNum":"    8","line":"# Usage: .devtools/bin/ci-ruff.sh    (from the repository root)"},
{"lineNum":"    9","line":"#   RUFF   the ruff command (default: ruff)"},
{"lineNum":"   10","line":"set -euo pipefail","class":"lineCov","hits":"1","order":"21",},
{"lineNum":"   11","line":""},
{"lineNum":"   12","line":"ruff=\"${RUFF:-ruff}\"","class":"lineCov","hits":"1","order":"20",},
{"lineNum":"   13","line":"\"$ruff\" check .","class":"lineCov","hits":"1","order":"19",},
{"lineNum":"   14","line":"\"$ruff\" format --check .","class":"lineCov","hits":"1","order":"18",},
]};
var percent_low = 25;var percent_high = 75;
var header = { "command" : "dev.sh", "date" : "2026-11-06 18:16:05", "instrumented" : 4, "covered" : 4,};
var merged_data = [];
