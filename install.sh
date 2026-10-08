#!/usr/bin/env bash
# install.sh: link <this checkout>/bin/mach into ~/.local/bin (outside machine-flows; no symlinks inside machine-flows).
#   bash install.sh                 preview (default): says what it would do
#   bash install.sh --apply         create or update the link
#   bash install.sh --uninstall [--apply]   remove the link (only if it points at this checkout)
# Env: MACH_BIN_DIR overrides the target folder (default ~/.local/bin). Idempotent. Refuses to replace a non-symlink file.
# bash 3.2 compatible.
set -u
ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null
. "$ROOT/lib/common.sh"

APPLY=0; UNINSTALL=0; BIN=${MACH_BIN_DIR:-$HOME/.local/bin}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --bin-dir) [ $# -ge 2 ] || die "--bin-dir needs a value"; BIN=$2; shift ;;
    -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

SRC="$ROOT/bin/mach"
LINK="$BIN/mach"
[ -x "$SRC" ] || die "not executable: $SRC"

if [ "$UNINSTALL" = 1 ]; then
  if [ ! -e "$LINK" ] && [ ! -L "$LINK" ]; then ok "nothing to remove: $(mach_tilde "$LINK") does not exist"; exit 0; fi
  if [ ! -L "$LINK" ]; then die "$(mach_tilde "$LINK") is not a symlink: refusing to remove it"; fi
  if [ "$(readlink "$LINK")" != "$SRC" ]; then die "$(mach_tilde "$LINK") points at $(readlink "$LINK"), not this checkout: refusing to remove it"; fi
  if [ "$APPLY" = 0 ]; then printf 'would remove link %s\npreview only: add --apply\n' "$(mach_tilde "$LINK")"; exit 0; fi
  mach_bk_init install
  mach_bk_link "$LINK"
  rm -f "$LINK" && ok "removed $(mach_tilde "$LINK")"
  mach_bk_finish
  exit 0
fi

if [ -L "$LINK" ]; then
  CUR=$(readlink "$LINK")
  if [ "$CUR" = "$SRC" ]; then ok "already installed: $(mach_tilde "$LINK") -> $(mach_tilde "$SRC")"; exit 0; fi
  printf 'would replace link %s -> %s with -> %s\n' "$(mach_tilde "$LINK")" "$CUR" "$(mach_tilde "$SRC")"
  ACTION=replace
elif [ -e "$LINK" ]; then
  die "$(mach_tilde "$LINK") exists and is not a symlink: refusing to touch it (move it away first)"
else
  printf 'would create link %s -> %s\n' "$(mach_tilde "$LINK")" "$(mach_tilde "$SRC")"
  ACTION=create
fi
case ":$PATH:" in *":$BIN:"*) ;; *) warn "$(mach_tilde "$BIN") is not on PATH" ;; esac

if [ "$APPLY" = 0 ]; then printf 'preview only: add --apply to do it\n'; exit 0; fi

mkdir -p "$BIN" || die "cannot create $BIN"
mach_bk_init install
if [ "$ACTION" = replace ]; then mach_bk_link "$LINK"; rm -f "$LINK"; else mach_bk_created "$LINK"; fi
ln -s "$SRC" "$LINK" || die "ln failed"
ok "linked $(mach_tilde "$LINK") -> $(mach_tilde "$SRC")"
mach_bk_finish
printf 'record the new link in the docs index (plan 00 rule 9): mach docs   (preview)\n'
exit 0
