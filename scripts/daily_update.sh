#!/bin/bash
# Daily deals refresh: fetch latest drops, commit + push to GitHub Pages.
set -e
cd "$HOME/workspace/deons-deals-site"
cp deals.json /tmp/deals.json.bak
python3 scripts/update_deals.py
count=$(python3 -c "import json;print(json.load(open('deals.json'))['count'])")
if [ "$count" -eq 0 ]; then
  echo "fetcher returned 0 deals - keeping previous deals.json (2026-10-06 guard)"
  cp /tmp/deals.json.bak deals.json
else
  git add deals.json
  if git diff --cached --quiet; then
    echo "no deal changes"
  else
    git -c user.name=D30N -c user.email=D30N@users.noreply.github.com \
      commit -qm "Daily deals update $(date +%F)"
  fi
fi
# Always push: also clears any stranded unpushed commits (2026-10-07 fix)
git push origin main
echo "pushed"
