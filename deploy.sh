#!/usr/bin/env bash
# Publish the built site to the gh-pages branch.
#
# The built data is ~64 MB. It is deliberately kept out of `main`: a clone of the
# source should not drag two thirds of a gigabyte of generated GeoJSON with it
# after a few rebuilds. Instead the build is pushed to an orphan gh-pages branch
# whose history is replaced each time, so the deployed payload exists exactly
# once rather than accumulating a new copy per deploy.
set -euo pipefail

cd "$(dirname "$0")"
BRANCH=gh-pages
WORKTREE=$(mktemp -d)
trap 'git worktree remove --force "$WORKTREE" 2>/dev/null || true; rm -rf "$WORKTREE"' EXIT

echo "→ building"
( cd web && OMNIGRID_BASE=/omnigrid/ npx vite build )

echo "→ preparing $BRANCH"
git worktree add --detach "$WORKTREE" >/dev/null
(
  cd "$WORKTREE"
  git checkout --orphan "$BRANCH" >/dev/null 2>&1
  git rm -rq --cached . 2>/dev/null || true
  find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +

  cp -r "$OLDPWD/web/dist/." .
  # Jekyll would otherwise skip files and folders beginning with an underscore.
  touch .nojekyll

  git add -A
  git -c user.name="D33ptar00p" -c user.email="deeptaroop2015@gmail.com" \
      commit -qm "Deploy $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git push -f origin "$BRANCH"
)
echo "→ deployed to https://d33ptar00p.github.io/omnigrid/"
