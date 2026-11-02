#!/bin/bash
# macOS: double-click in Finder to start the local server and open the browser.
cd "$(dirname "$0")"
export OPEN_BROWSER=1
exec ./scripts/start.sh
