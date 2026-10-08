"""mach_common: shared helpers for the python mach commands (stdlib only, python 3.9+).

Mirrors lib/common.sh: host map, roots, colours, printers, exit codes, backup/rollback
helpers, plus config loading with the precedence flags > env > local > host > shared > defaults.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import minitoml  # noqa: E402

EXIT_OK, EXIT_WARN, EXIT_FAIL, EXIT_WAIT = 0, 1, 2, 3

KNOWN_TOOLS = ["claude", "codex", "cursor-agent", "grokcli-agent", "kiro"]


# ----------------------------------------------------------------- environment

def mach_home():
    return os.environ.get("MACH_HOME") or os.path.dirname(LIB_DIR)


def version():
    try:
        with open(os.path.join(mach_home(), "VERSION"), "r") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def expand(path):
    """Expand ~ using $HOME (not the passwd entry), so tests can redirect it."""
    if path == "~" or path.startswith("~/"):
        return home() + path[1:]
    return path


def tilde(path):
    h = home()
    if path == h:
        return "~"
    if path.startswith(h + "/"):
        return "~" + path[len(h):]
    return path


def shell_path(path):
    """A path to paste into a shell: '~/…' stays unquoted so the shell expands it, the rest is quoted only if needed."""
    import shlex
    t = tilde(path)
    if t.startswith("~/"):
        return "~/" + shlex.quote(t[2:])
    return shlex.quote(t)


def _machines_layer():
    """[machines] from the shared and local config layers only (the host layer is chosen by the host name itself)."""
    cdir = config_dir()
    local = os.path.join(cdir, "local.toml") if os.environ.get("MACH_CONFIG_DIR") else os.path.join(home(), ".config", "mach", "local.toml")
    out = {}
    for path in (os.path.join(cdir, "config.toml"), local):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = minitoml.parse(fh.read())
        except (OSError, ValueError):
            continue
        m = data.get("machines")
        if isinstance(m, dict):
            out = _deep_merge(out, m)
    return out


def host():
    """This machine's name. MACH_HOST overrides; else the short hostname, mapped by [machines.match]
    (lower-case hostname prefix -> machine name); unmatched hostnames stay as they are."""
    env = os.environ.get("MACH_HOST")
    if env:
        return env
    import socket
    short = (os.environ.get("MACH_HOSTNAME") or socket.gethostname()).split(".")[0]   # MACH_HOSTNAME: tests
    low = short.lower()
    match = _machines_layer().get("match")
    if isinstance(match, dict):
        for prefix in sorted(match, key=len, reverse=True):
            if low.startswith(str(prefix).lower()):
                return str(match[prefix])
    return short


def machine_names(cfg=None):
    """Known machine names: [machines] names, plus the match targets, plus this machine."""
    data = cfg.section("machines") if cfg is not None else _machines_layer()
    names = [str(n) for n in (data.get("names") or []) if n]
    match = data.get("match")
    if isinstance(match, dict):
        names += [str(v) for v in match.values()]
    names.append(host())
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def mac_machine(cfg=None):
    """Name of the macOS machine that delivers Agenda/Drafts notes ([machines] mac); '' when not configured."""
    data = cfg.section("machines") if cfg is not None else _machines_layer()
    return str(data.get("mac") or "")


def collector_machine(cfg=None):
    """Machine that runs `mach docs collect` (single writer): $MACH_DOCS_COLLECTOR, else [machines] collector, else this machine."""
    data = cfg.section("machines") if cfg is not None else _machines_layer()
    return os.environ.get("MACH_DOCS_COLLECTOR") or str(data.get("collector") or "") or host()


def is_mac():
    forced = os.environ.get("MACH_OS")
    if forced:
        return forced.lower() in ("darwin", "mac", "macos")
    return sys.platform == "darwin"


def mf_root():
    return os.environ.get("MACH_MF_ROOT") or os.path.join(home(), "machine-flows")


def staging():
    return os.environ.get("MACH_STAGING") or os.path.join(home(), "machine-flows-staging")


def state_dir():
    """Docs-index state (births-seen.json, mac-stat.tsv): outside the synced folder."""
    return os.environ.get("MACH_STATE_DIR") or os.path.join(staging(), "docs-index")


def local_state_dir():
    return os.environ.get("MACH_LOCAL_STATE") or os.path.join(home(), ".local", "state", "mach")


def log_dir():
    return os.environ.get("MACH_LOG_DIR") or os.path.join(local_state_dir(), "logs")


def runs_dir(cfg=None):
    env = os.environ.get("MACH_RUNS_DIR")
    if env:
        return expand(env)
    if cfg is not None:
        c = cfg.get("runs.dir", "")
        if c:
            return rel_to_mf(c)
    return os.path.join(mf_root(), "files", "runs")


def rel_to_mf(path):
    path = expand(path)
    return path if os.path.isabs(path) else os.path.join(mf_root(), path)


def now():
    """Local time; MACH_NOW='YYYY-MM-DD HH:MM[:SS]' pins it for tests."""
    env = os.environ.get("MACH_NOW")
    if env:
        fmt = "%Y-%m-%d %H:%M:%S" if env.count(":") == 2 else "%Y-%m-%d %H:%M"
        return datetime.datetime.strptime(env, fmt)
    return datetime.datetime.now()


def env_flag(name):
    return os.environ.get(name, "") not in ("", "0", "false", "no")


def mktemp_dir(prefix="mach"):
    """Temp dir under the staging area (unsynced, under ~), never /tmp, unless staging is unusable."""
    base = os.path.join(staging(), "tmp")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = None
    import tempfile
    return tempfile.mkdtemp(prefix=prefix + ".", dir=base)


# ----------------------------------------------------------------- output

def use_color(stream=None):
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("MACH_NO_COLOR"):
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


_COL = {"OK": "32", "WARN": "33", "FAIL": "31", "INFO": "36", "bold": "1", "dim": "2"}


def paint(text, kind, stream=None):
    if use_color(stream) and kind in _COL:
        return "\033[%sm%s\033[0m" % (_COL[kind], text)
    return text


def eprint(*a):
    print(*a, file=sys.stderr)


def die(msg, code=EXIT_FAIL):
    eprint("mach: " + msg)
    sys.exit(code)


def status_line(level, check, detail=""):
    return "%s  %s  %s" % (paint("%-4s" % level, level), check, detail)


def truncate(s, n=60):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def slugify(text, maxlen=30):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    s = s[:maxlen].strip("-")
    return s or "run"


def shown_cmd(argv, prompt_index=None, limit=60):
    """Command as a shell-ish string with the prompt argument truncated."""
    import shlex
    parts = []
    for i, a in enumerate(argv):
        if prompt_index is not None and i == prompt_index:
            a = truncate(a, limit)
        parts.append(shlex.quote(a))
    return " ".join(parts)


def should_apply(apply, yes=False, prompt="Apply these changes?"):
    """State changes preview by default: act with --apply (or --yes), or an interactive y on a tty."""
    if apply or yes:
        return True
    if sys.stdin.isatty() and sys.stdout.isatty():
        return confirm(prompt)
    return False


def confirm(question, assume_yes=False, default=False):
    """Ask on a tty; non-tty without --yes means no."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        ans = input("%s [%s] " % (question, "Y/n" if default else "y/N")).strip().lower()
    except EOFError:
        return False
    if ans == "":
        return default
    return ans in ("y", "yes")


# ----------------------------------------------------------------- config

DEFAULTS = {
    "note": {
        "default": "inbox",
        "inbox": {"dir": "files/inbox/notes"},
        "agenda": {"project": "Inbox", "method": ["mcp", "url"], "mcp_url": "http://127.0.0.1:16106/mcp", "tags": []},
        "drafts": {"method": ["cli", "url"], "tags": ["mach"]},
        "dest": {},
    },
    "routes": {"default_tool": "claude", "default_machine": "", "permission": "read-only", "project": {}},
    "tools": {},
    "doctor": {
        "peer_ssh": "",
        "disk_min_free_pct": 10,
        "mem_min_avail_mb": 500,
        "outbox_max_age_hours": 24,
        "agents_max_lines": 130,
        "lessons_index_max_lines": 300,
        "proposed_max": 30,
        "grokbot_heartbeat_max_age_s": 180,
        "syncthing_url": "http://127.0.0.1:8384",
        "syncthing_folder": "machine-flows",
        "scan_budget_s": 4,
    },
    "runs": {"dir": "", "retention_days": 90},
    "queue": {"background_machine": ""},
    "machines": {"names": [], "match": {}, "mac": "", "collector": ""},
    "drafts": {"hub_name": "Mach Hub", "hub_group_uuid": ""},
    "docs": {"macstat_paths": [], "macstat_cron_pattern": "machine-flows"},
    "memory": {"lessons_dir": "service-memories/lessons", "reviews_dir": ""},
}

# env var -> config key (precedence: flags > env > local > host > shared > defaults)
ENV_KEYS = {
    "MACH_NOTE_DEFAULT": "note.default",
    "MACH_DEFAULT_TOOL": "routes.default_tool",
    "MACH_PEER_SSH": "doctor.peer_ssh",
    "MACH_RETENTION_DAYS": "runs.retention_days",
}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def config_dir():
    env = os.environ.get("MACH_CONFIG_DIR")
    if env:
        return expand(env)
    return os.path.join(mf_root(), "service-settings", "mach")


def config_files(h=None):
    h = h or host()
    cdir = config_dir()
    local = os.path.join(cdir, "local.toml") if os.environ.get("MACH_CONFIG_DIR") else os.path.join(home(), ".config", "mach", "local.toml")
    return [("shared", os.path.join(cdir, "config.toml")),
            ("host", os.path.join(cdir, "hosts", "%s.toml" % h)),
            ("local", local)]


class Config(object):
    def __init__(self, data, sources, errors):
        self.data = data
        self.sources = sources   # [(layer, path)] actually loaded
        self.errors = errors     # [str]

    def get(self, dotted, default=None):
        env_name = None
        for env, key in ENV_KEYS.items():
            if key == dotted:
                env_name = env
        if env_name and os.environ.get(env_name):
            val = os.environ[env_name]
            if isinstance(default, int) and not isinstance(default, bool) and val.isdigit():
                return int(val)
            return val
        cur = self.data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def section(self, dotted):
        v = self.get(dotted, {})
        return v if isinstance(v, dict) else {}


def load_config(h=None):
    data = _deep_merge({}, DEFAULTS)
    sources, errors = [], []
    for layer, path in config_files(h):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                layer_data = minitoml.parse(fh.read())
        except (OSError, ValueError) as exc:
            errors.append("%s: %s" % (tilde(path), exc))
            continue
        data = _deep_merge(data, layer_data)
        sources.append((layer, path))
    return Config(data, sources, errors)


def load_config_or_warn(h=None):
    cfg = load_config(h)
    for e in cfg.errors:
        eprint("mach: warning: config not loaded: " + e)
    return cfg


# ----------------------------------------------------------------- tools

TOOL_BINARY = {"claude": "claude", "codex": "codex", "cursor-agent": "cursor-agent",
               "grokcli-agent": "grokcli-agent", "kiro": "kiro-cli"}


def which(name, path=None):
    return shutil.which(name, path=path)


def ext_cmd(var, default):
    """The program mach runs for an outside tool: $<var> if set (tests point it into a sandbox; a path that does not exist
    means "not available"), else `default`. Everything that can cause side effects (open, drafts, osascript, the AI CLIs,
    tmux, launchctl, systemctl, crontab, ssh) must be resolved through here, never by a bare name."""
    return os.environ.get(var) or default


# environment variable that overrides each external program (see ext_cmd)
CMD_VARS = {"open": "MACH_OPEN_CMD", "drafts": "MACH_DRAFTS_CMD", "osascript": "MACH_OSASCRIPT_CMD", "tmux": "MACH_TMUX",
            "launchctl": "MACH_LAUNCHCTL_CMD", "systemctl": "MACH_SYSTEMCTL_CMD", "crontab": "MACH_CRONTAB_CMD", "ssh": "MACH_SSH_CMD",
            "claude": "MACH_CLAUDE_CMD", "codex": "MACH_CODEX_CMD", "cursor-agent": "MACH_CURSOR_AGENT_CMD",
            "kiro": "MACH_KIRO_CMD", "grokcli-agent": "MACH_GROKCLI_AGENT_CMD", "curl": "MACH_CURL_CMD"}


def cmd(name):
    """Resolved program for `name` (a key of CMD_VARS): the override variable, else the plain name."""
    default = TOOL_BINARY.get(name, name)
    return ext_cmd(CMD_VARS[name], default)


def tool_argv(tool, prompt, write=False, cfg=None):
    """Headless argv for each tool. Read-only by default. Returns (argv, prompt_index, note).

    Flags confirmed with each CLI's --help on 2026-10-08, except grokcli-agent (see docs/DECISIONS.md).
    """
    cfg = cfg or load_config()
    binary = tool_binary_name(tool, cfg)
    custom = cfg.get("tools.%s.write_args" % tool if write else "tools.%s.read_args" % tool, None)
    if isinstance(custom, list) and custom:
        argv = [binary] + [str(x) for x in custom] + [prompt]
        return argv, len(argv) - 1, "args from config"
    if tool == "claude":
        argv = [binary, "-p", prompt, "--permission-mode", "acceptEdits" if write else "plan"]
        return argv, 2, ""
    if tool == "codex":
        argv = [binary, "exec", "--sandbox", "workspace-write" if write else "read-only", "--skip-git-repo-check", prompt]
        return argv, len(argv) - 1, ""
    if tool == "cursor-agent":
        argv = [binary, "-p", "--output-format", "text", "--trust"]
        if not write:
            argv += ["--mode", "ask"]
        argv.append(prompt)
        return argv, len(argv) - 1, ""
    if tool == "kiro":
        argv = [binary, "chat", "--no-interactive", "--trust-tools=fs_read,fs_write" if write else "--trust-tools=", prompt]
        return argv, len(argv) - 1, ""
    if tool == "grokcli-agent":
        argv = [binary, "-p", prompt]
        return argv, 2, "best guess: grok CLI flags unverified on this machine (no read-only switch known)"
    raise ValueError("unknown tool %r (use one of %s)" % (tool, ", ".join(KNOWN_TOOLS)))


def tool_binary_name(tool, cfg=None):
    """Program for an AI tool: env override (MACH_<TOOL>_CMD) > config tools.<tool>.command > the default name."""
    if tool in CMD_VARS and os.environ.get(CMD_VARS[tool]):
        return os.environ[CMD_VARS[tool]]
    cfg = cfg or load_config()
    return cfg.get("tools.%s.command" % tool, TOOL_BINARY.get(tool, tool))


def tool_available(tool, cfg=None):
    return which(tool_binary_name(tool, cfg)) is not None


# ----------------------------------------------------------------- backups

class Backup(object):
    """Backs files up to $MACH_STAGING/backups/<ts>-mach-<cmd>/ and writes a rollback script."""

    def __init__(self, cmd):
        ts = now().strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(staging(), "backups", "%s-mach-%s" % (ts, cmd))
        self.items = []     # (kind, backup_or_target, original)
        self._made = False

    def _ensure(self):
        if not self._made:
            os.makedirs(self.dir, exist_ok=True)
            self._made = True

    def save(self, path):
        """Copy an existing file or symlink aside before it is changed or removed."""
        self._ensure()
        name = "%03d-%s" % (len(self.items) + 1, re.sub(r"[^A-Za-z0-9._-]+", "_", tilde(path)).strip("_"))
        dest = os.path.join(self.dir, name)
        if os.path.islink(path):
            self.items.append(("link", os.readlink(path), path))
        elif os.path.isdir(path):
            shutil.copytree(path, dest, symlinks=True)
            self.items.append(("dir", dest, path))
        elif os.path.exists(path):
            shutil.copy2(path, dest)
            self.items.append(("file", dest, path))
        else:
            self.items.append(("created", "", path))

    def created(self, path):
        self._ensure()
        self.items.append(("created", "", path))

    def created_dir(self, path):
        """A directory this run made: rollback uses rmdir, so it never removes anything added there later."""
        self._ensure()
        self.items.append(("newdir", "", path))

    def finish(self, quiet=False):
        """Write rollback.sh and return the one-line rollback hint."""
        if not self._made:
            return ""
        script = os.path.join(self.dir, "rollback.sh")
        import shlex
        lines = ["#!/usr/bin/env bash", "# generated by mach: restores what this run changed", "set -u"]
        for kind, a, orig in reversed(self.items):
            if kind == "file":
                lines.append("cp -p %s %s" % (shlex.quote(a), shlex.quote(orig)))
            elif kind == "dir":
                lines.append("rm -rf %s && cp -pR %s %s" % (shlex.quote(orig), shlex.quote(a), shlex.quote(orig)))
            elif kind == "link":
                lines.append("rm -f %s && ln -s %s %s" % (shlex.quote(orig), shlex.quote(a), shlex.quote(orig)))
            elif kind == "created":
                lines.append("rm -rf %s" % shlex.quote(orig))
            elif kind == "newdir":
                lines.append("rmdir %s 2>/dev/null" % shlex.quote(orig))
        with open(script, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(script, 0o755)
        hint = "rollback: bash %s" % shell_path(script)
        if not quiet:
            print("backup: " + tilde(self.dir))
            print(hint)
        return hint


# ----------------------------------------------------------------- subprocess

def run_capture(argv, timeout=5, cwd=None, env=None):
    """Run a command, capture output, never raise, never hang. Returns (rc, stdout, stderr).

    rc is 127 when the program is missing and 124 on timeout.
    """
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                           cwd=cwd, env=env, universal_newlines=True)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "not found: %s" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss" % timeout
    except OSError as exc:
        return 126, "", str(exc)


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return default


def write_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def emit_json(obj):
    print(json.dumps(obj, indent=2, sort_keys=False))


def is_inside(path, root):
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def peer_host(h=None, cfg=None):
    h = h or host()
    for x in machine_names(cfg):
        if x != h:
            return x
    return ""


def background_machine(cfg=None):
    """Where `machine: any` work runs: [queue] background_machine, else this machine."""
    cfg = cfg or load_config()
    return str(cfg.get("queue.background_machine", "") or "") or host()


if __name__ == "__main__":
    # tiny CLI for the bash scripts: host | mac | collector | names | get <dotted.key>
    arg = sys.argv[1:2]
    if arg == ["host"]:
        print(host())
    elif arg == ["mac"]:
        print(mac_machine())
    elif arg == ["collector"]:
        print(collector_machine())
    elif arg == ["names"]:
        print(" ".join(machine_names()))
    elif arg == ["get"] and len(sys.argv) > 2:
        v = load_config().get(sys.argv[2], "")
        if isinstance(v, list):
            print("\n".join(str(x) for x in v))
        else:
            print(v)
    else:
        sys.exit(2)
