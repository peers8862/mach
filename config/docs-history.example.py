# docs-history.example.py: format of the personal history file read by `mach docs` (libexec/mach-docs-collect.py).
#
# Copy this file to docs-history.local.py (gitignored) in ONE of these places; the first one found wins:
#   1. $MACH_DOCS_HISTORY                                   (explicit path)
#   2. $MACH_CONFIG_DIR/docs-history.local.py
#   3. ~/machine-flows/service-settings/mach/docs-history.local.py   (synced between machines; the usual home)
#   4. <repo>/config/docs-history.local.py
# Without one, `mach docs` still works: it lists every file and folder it walks, with generic purposes, and prints one INFO line.
#
# The file is plain Python that is imported once. Every name below is optional. Paths inside machine-flows are relative to
# the machine-flows root ("plans/01-example.md"); paths elsewhere use "~/..." (the collector never prints absolute home paths).
# NOTE: machine names used in rows ("linux-box", "mac-laptop" below) must match [machines] collector / mac in your config.toml.
# Times are either "YYYY-MM-DD HH:MM[:SS]" strings (America/New_York wall-clock), integer epoch seconds, or "" for "unknown".
# Text fields may use the placeholders {BOTH} (the standard "present_on: linux-box, mac-laptop ..." note), {STAGE} (the staging folder),
# {walkfiles:REL} (number of files below machine-flows/REL) and {nfiles:REL} (number of entries directly in machine-flows/REL).

# --- purposes for walked files and folders -------------------------------------------------------------------------------------
PURPOSE = {
    "plans/01-example-plan.md": "Example plan: what this file is for",       # path relative to the machine-flows root -> purpose column
}
DEFAULT_PURPOSE = "No purpose recorded"                                       # purpose of walked files that are not in PURPOSE
FOLDER_PURPOSE = {"plans": "Living plan documents"}                           # folder rel path -> purpose
FOLDER_ONLY = ["drafts"]                                                      # walked folders listed as ONE row (children skipped)

# Fix a wrong created date: rel path -> (created time, note appended to notes).
CREATED_OVERRIDE = {
    "plans/01-example-plan.md": ("2026-01-02 03:04:05", "birth on disk is a later rewrite; created = when the doc was first placed"),
}

# --- items that originate on the other machine ---------------------------------------------------------------------------------
MAC_ORIGIN_PREFIX = ("drafts",)                      # walked paths starting with these are NOT collector-machine rows (listed under mac-laptop instead)
MAC_ORIGIN_EXACT = ["scripts/inventory-macos.sh"]    # exact walked rel paths with a mac-laptop origin
SKIP_EXACT = [".stignore"]                           # exact walked rel paths to leave out (because ROWS below describes them)

# --- backups folder (~/machine-flows-staging/backups/*) ------------------------------------------------------------------------
BACKUP_PURPOSE = {"20260101-000000-example-task": "Files before the example task"}   # backup folder name -> purpose
BACKUP_OVERRIDES = {"Old-folder-": {"created": "2026-01-02 03:04:05", "notes": "the original folder, moved here"}}  # name prefix -> created + notes

# --- Mac facts recorded by hand (used when mac-stat.tsv is missing) ------------------------------------------------------------
MAC_ORIG = {"inventory/mac-laptop/00-summary.md": 1790000000}   # rel path -> original Mac mtime (epoch)
MAC_ORIG_NOTE = {}                                            # rel path -> extra note for that file
CRON_NOTE_FALLBACK = "exact crontab text not re-read (Mac offline)"   # used by the {cron_note} placeholder

# --- row helpers (optional; you can also write plain dicts) --------------------------------------------------------------------
def R(machine, path, kind, area, scope, purpose, created_by, **kw):
    """Ordinary row. machine: 'linux-box' | 'mac-laptop'. kind: doc, plan, script, config, service, folder, link, backup, ...
    scope: 'shared-synced' | 'local'. created_by: 'agent' | 'user' | 'tool'.
    Optional keywords: status ('active' default | 'superseded' | 'retired' | 'deleted'), created, modified, retired_date, replaced_by,
    notes, name (display name), stat (False = do not stat the path; True/'@in_mac' = stat it / only if the Mac saw it),
    if_absent / if_lexists (a path; only add the row when it is absent / present), if_mf_exists (rel path inside machine-flows),
    modified='@mf_mtime:REL' (take the mtime of machine-flows/REL), kind_if_file (kind to use when the path is not a folder),
    mac_present (dict of overrides applied when mac-stat.tsv lists the path)."""
    d = dict(machine=machine, path=path, kind=kind, area=area, scope=scope, purpose=purpose, created_by=created_by)
    d.update(kw)
    return d


ROWS = [
    # A local item outside machine-flows that still exists.
    R("linux-box", "~/.config/example/app.conf", "config", "example", "local", "Example app settings we changed", "agent",
      notes="edited 2026-01-02; backup in ~/machine-flows-staging/backups/20260101-000000-example-task/"),
    # A retired item: status + retired_date + replaced_by. stat=False because the file no longer exists.
    R("linux-box", "~/.config/example/old.conf", "config", "example", "local", "Old example settings", "user",
      status="retired", created="2025-12-31 10:00", modified="", stat=False, retired_date="2026-01-02 03:04:05",
      replaced_by="~/.config/example/app.conf", notes="superseded by app.conf; times approximate"),
    # A Mac-origin file inside machine-flows (collector mac_file): created may be a time or '@min_child:REL'.
    dict(type="mac_file", rel="inventory/mac-laptop/00-summary.md", purpose="mac-laptop inventory: summary", kind="inventory",
         area="inventory", created_override=None, extra=""),
    # A Mac-only item outside machine-flows (collector mac_out); approx_created is used while the Mac is offline.
    dict(type="mac_out", path="~/Library/Logs/example.log", kind="service", area="example", purpose="Example log on the Mac",
         created_by="tool", approx_created="2026-01-02 03:04"),
]


def dynamic_rows(ctx):
    """Optional: rows that depend on the live state. Return a list of row dicts (same shapes as ROWS).
    ctx.os, ctx.MF (machine-flows root), ctx.STAGE, ctx.HOME, ctx.MAC (dict from mac-stat.tsv: '~/path' -> (birth, mtime, type)),
    ctx.MAC_CRON (list of crontab lines), ctx.MAC_GROKCLI, ctx.tilde(path)."""
    return []
