var data = {lines:[
{"lineNum":"    1","line":"#!/usr/bin/env bash"},
{"lineNum":"    2","line":"# Archive a built site as the tar GitHub Pages deploys, keeping its hidden files."},
{"lineNum":"    3","line":"#"},
{"lineNum":"    4","line":"# A site\'s hidden files, such as .well-known/assetlinks.json, are part of it, so they stay; links"},
{"lineNum":"    5","line":"# are replaced by what they point to, and .git and .github are left out."},
{"lineNum":"    6","line":"#"},
{"lineNum":"    7","line":"# Usage: .devtools/bin/pages-artifact.sh SITE_DIR ARCHIVE"},
{"lineNum":"    8","line":"set -euo pipefail","class":"lineCov","hits":"1","order":"81",},
{"lineNum":"    9","line":""},
{"lineNum":"   10","line":"site=\"${1:?usage: pages-artifact.sh SITE_DIR ARCHIVE}\"","class":"lineCov","hits":"1","order":"79",},
{"lineNum":"   11","line":"archive=\"${2:?usage: pages-artifact.sh SITE_DIR ARCHIVE}\"","class":"lineCov","hits":"1","order":"78",},
{"lineNum":"   12","line":"if [ ! -d \"$site\" ] || [ -z \"$(ls -A \"$site\")\" ]; then","class":"lineCov","hits":"1","order":"77",},
{"lineNum":"   13","line":"  echo \"pages-artifact: $site is missing or empty; the build wrote no site\" >&2","class":"lineCov","hits":"1","order":"76",},
{"lineNum":"   14","line":"  exit 1","class":"lineCov","hits":"1","order":"75",},
{"lineNum":"   15","line":"fi"},
{"lineNum":"   16","line":"# GNU tar, as on CI\'s runners, also stores each hard link as a file; BSD tar has no such option."},
{"lineNum":"   17","line":"links=(--dereference)","class":"lineCov","hits":"1","order":"74",},
{"lineNum":"   18","line":"if tar --version 2>/dev/null | grep -q \'GNU tar\'; then","class":"lineCov","hits":"1","order":"73",},
{"lineNum":"   19","line":"  links+=(--hard-dereference)","class":"lineCov","hits":"1","order":"72",},
{"lineNum":"   20","line":"fi"},
{"lineNum":"   21","line":"tar \"${links[@]}\" --exclude=.git --exclude=.github -cf \"$archive\" -C \"$site\" .","class":"lineCov","hits":"1","order":"80",},
{"lineNum":"   22","line":"echo \"pages-artifact: archived $site into $archive\"","class":"lineCov","hits":"1","order":"71",},
]};
var percent_low = 25;var percent_high = 75;
var header = { "command" : "dev.sh", "date" : "2026-11-14 13:30:39", "instrumented" : 11, "covered" : 11,};
var merged_data = [];
