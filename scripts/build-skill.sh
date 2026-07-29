#!/usr/bin/env bash
# Build a portable Agent Skills archive from the canonical skill directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo "error: working tree is dirty; commit or stash before building" >&2
  exit 1
fi

mkdir -p dist
OUT="dist/apex-competition-builder.skill"
git archive \
  --format=zip \
  --prefix=apex-competition-builder/ \
  --output="$OUT" \
  HEAD:skills/apex-competition-builder

test "$(unzip -Z1 "$OUT" | grep -c 'apex-competition-builder/SKILL.md')" -eq 1
test "$(unzip -Z1 "$OUT" | grep -c 'apex-competition-builder/scripts/scaffold_competition.py')" -eq 1
test "$(unzip -Z1 "$OUT" | wc -l | tr -d ' ')" -le 200

echo "built $OUT"
