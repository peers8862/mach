#!/bin/bash
# mach-docs-macstat.sh: light, read-only fact gathering on the Mac for the docs index. Prints path facts only (no file contents).
# Run on the Mac via `mach docs macstat`. Output goes to stdout; `mach docs macstat --apply` saves it as mac-stat.tsv in the
# (unsynced) state folder.
# Environment (set by mach docs from the config): MACH_MAC_NAME ([machines] mac), MACH_MACSTAT_PATHS (newline-separated extra
# paths relative to ~, [docs] macstat_paths) and MACH_MACSTAT_CRON_PATTERN ([docs] macstat_cron_pattern, default machine-flows).
cd ~ || exit 1
EXTRA=()
while IFS= read -r line; do [ -n "$line" ] && EXTRA+=("$line"); done <<EOF_PATHS
${MACH_MACSTAT_PATHS:-}
EOF_PATHS
MAC_INV=()
if [ -n "${MACH_MAC_NAME:-}" ]; then MAC_INV=("machine-flows/inventory/$MACH_MAC_NAME" "machine-flows/inventory/$MACH_MAC_NAME"/*); fi
for p in machine-flows machine-flows/drafts machine-flows/drafts/Importing machine-flows/drafts/Importing/* \
  ${MAC_INV[@]+"${MAC_INV[@]}"} machine-flows/scripts/inventory-macos.sh \
  machine-flows/.stignore machine-flows/.stfolder machine-flows/.stversions \
  Library/LaunchAgents/net.syncthing.syncthing.plist Library/Logs/syncthing.log \
  "Library/Application Support/Syncthing" "Library/Application Support/Syncthing/config.xml" \
  machine-flows-staging machine-flows-staging/* machine-flows-staging/backups/* \
  .local/bin/agent .local/bin/grokcli-agent .local/bin/cursor-agent \
  ${EXTRA[@]+"${EXTRA[@]}"}; do
  if [ -e "$p" ] || [ -L "$p" ]; then stat -f '%B|%m|%c|%HT|~/%N' "$p"; else echo "0|0|0|MISSING|~/$p"; fi
done
echo "#CRON"; "${MACH_CRONTAB_CMD:-crontab}" -l 2>/dev/null | grep -n -E "${MACH_MACSTAT_CRON_PATTERN:-machine-flows}" | sed 's/^/#CRON|/'
echo "#AGENTLINK|$(readlink ~/.local/bin/agent 2>/dev/null)"
echo "#GROKCLILINK|$(readlink ~/.local/bin/grokcli-agent 2>/dev/null)"
