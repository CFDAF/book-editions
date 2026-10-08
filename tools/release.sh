#!/bin/bash
# The release flow: dev -> stage -> public main.
#
# Remotes: `origin` is the private repo (dev, stage), `public` the public one
# (main only). The pre-push hook that guards `public` is local to a checkout,
# not tracked; both subcommands refuse to run without it.
#
#   1. commit       git add -p && git commit          (on dev, by hand)
#   2. push         git push origin dev
#   3. promote      tools/release.sh stage [--lookup]
#   4. release      tools/release.sh public
#
# `stage` pushes dev, fast-forwards stage to it, pushes stage, then checks a
# fresh clone of stage (pytest, core coverage; --lookup adds one live lookup).
# `public` builds ONE commit on top of public main carrying stage's tree, shows
# it, dry-runs it against the pre-push hook and asks before pushing.
# Never push dev, stage or a tag to `public`; never --no-verify.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

die() { echo "release: $*" >&2; exit 1; }

# Paths that must never reach the public tree.
PRIVATE='^bench/|STRATEGY|HANDOFF|archive/|RELEASE-PLAN'

preflight() {
  [ "$(git branch --show-current)" = dev ] || die "not on dev"
  [ -z "$(git status --porcelain)" ] || die "the working tree is not clean"
  [ -x .git/hooks/pre-push ] || die ".git/hooks/pre-push is missing: the public remote is unguarded"
}

promote() {
  preflight
  git fetch origin
  git merge-base --is-ancestor origin/dev dev || die "origin/dev is not behind dev: pull --rebase first"
  git push origin dev
  # A fetch into a local branch is fast-forward-only: a diverged stage is refused.
  git fetch . dev:stage || die "stage is not an ancestor of dev"
  git push origin stage

  local sha
  sha=$(git rev-parse stage)
  tmp=$(mktemp -d)  # global: the EXIT trap outlives this function
  trap 'rm -rf "$tmp"' EXIT
  # Shallow: the check needs stage's tree, and its history is some 65 MB.
  git clone --depth 1 -b stage --single-branch "$(git remote get-url origin)" "$tmp/clone"
  [ "$(git -C "$tmp/clone" rev-parse HEAD)" = "$sha" ] || die "the clone is not at stage $sha"
  (
    cd "$tmp/clone"
    python3 -m pytest -q
    python3 tools/core_coverage.py
    if [ "${1:-}" = --lookup ]; then
      python3 book_editions.py "Il nome della rosa" --author "Umberto Eco" | tail -20
    fi
  )
  echo "release: stage is at ${sha:0:8} on origin and its fresh clone passes"
}

publish() {
  preflight
  git fetch origin
  git fetch public
  [ "$(git rev-parse stage)" = "$(git rev-parse origin/stage)" ] \
    || die "local stage is not origin/stage: run 'tools/release.sh stage' first"
  [ "$(git rev-parse 'stage^{tree}')" != "$(git rev-parse 'public/main^{tree}')" ] \
    || die "public main already carries stage's tree: nothing to release"

  local leaked c answer
  leaked=$(git ls-tree -r --name-only stage | grep -E "$PRIVATE" || true)
  [ -z "$leaked" ] || die "stage tracks private paths:"$'\n'"$leaked"

  c=$(git commit-tree 'stage^{tree}' -p public/main \
        -m "Release $(date +%F) (stage $(git rev-parse --short=8 stage))")
  git --no-pager diff --stat public/main "$c" | tail -15
  git push --dry-run public "${c}:refs/heads/main" \
    || die "the dry run was refused: public main moved, or the hook objects. Do not bypass it."

  printf 'Push %s to PUBLIC main? Type "release" to go: ' "${c:0:8}"
  read -r answer
  [ "$answer" = release ] || die "not pushed; the commit $c is unreferenced and will be collected"

  git push public "${c}:refs/heads/main"
  git branch -f main "$c"
  git fetch public
  git ls-remote public
  git --no-pager log --oneline -3 public/main
}

case "${1:-}" in
  stage)  promote "${2:-}" ;;
  public) publish ;;
  *)      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
