"""Generic subsystem manifests, deterministic draft ingestion, and text-preserving edits."""
import difflib
import json
import os
import re
import stat

import frontmatter as fm
import mach_common as mc
import minitoml

ID = re.compile(r'^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$')
KINDS = {'pillar', 'service', 'product', 'publication', 'pipeline', 'event'}
DESTS = set(mc.KNOWN_TOOLS) | {'user'}
# Role destination syntax -> (kind, how it is delivered). docs/sheets/destinations.csv is generated from this table (mach sheets refresh mach).
DEST_DOCS = [
    ('<tool>', 'role/ai-tool', 'headless CLI run in the unit working folder, read-only unless --write; one run record'),
    ('user', 'role/person', 'note captured to the manifest note_dest (default inbox), tagged with the subsystem and unit'),
    ('grokbot:<Service>', 'role/chat-bot', 'POST to the Grok Bot router webhook with secrets from the unsynced local file; without safe credentials a paste-ready queued run'),
    ('note:<dest>', 'role/note', 'note captured to the named mach note destination, tagged with the subsystem and unit'),
]
LIST_FIELDS = {'types', 'routines', 'agent_files', 'recipes', 'changed', 'assignments', 'strengths', 'limits', 'workloads'}
BOOL_FIELDS = {'special', 'verified'}
TOP = ('schema', 'id', 'name', 'working_root', 'linear_team', 'note_dest')
UNIT_FIELDS = {'name', 'kind', 'parent', 'special', 'repo', 'folder', 'types', 'routines', 'agent_files', 'recipes', 'verified', 'notes', 'todo'}
ROLE_META = {'since', 'changed', 'notes', 'assignments'}


def root():
    return os.environ.get('MACH_SUBSYSTEMS_DIR') or os.path.join(mc.mf_root(), 'subsystems')


def path(sid):
    return os.path.join(root(), sid, 'subsystem.toml')


def ids():
    if not os.path.isdir(root()):
        return []
    return [x for x in sorted(os.listdir(root())) if not x.startswith('_') and os.path.isfile(path(x))]


def parse(text):
    seen_units = set()
    for match in re.finditer(r'(?m)^\[units\.([a-z][a-z0-9-]*)\]\s*$', text):
        if match.group(1) in seen_units:
            raise ValueError('duplicate unit table ' + match.group(1))
        seen_units.add(match.group(1))
    if os.environ.get('MACH_FORCE_MINITOML'):
        return minitoml.parse(text)
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        return minitoml.parse(text)


def load(sid):
    with open(path(sid), encoding='utf-8') as fh:
        return parse(fh.read())


def dest_ok(d):
    return isinstance(d, str) and (d in DESTS or bool(re.match(r'^grokbot:[^\s].*$', d)) or bool(re.match(r'^note:[a-z][a-z0-9-]*$', d)))


def lint(data, folder):
    out = []
    def fail(msg): out.append(('FAIL', msg))
    def info(msg): out.append(('INFO', msg))
    if data.get('schema') != 1: fail('schema must be 1')
    sid = data.get('id')
    if not isinstance(sid, str) or not ID.fullmatch(sid) or sid != folder: fail('id must be lowercase kebab and match folder')
    if sid in {'help', 'version'} or os.path.isfile(os.path.join(mc.mach_home(), 'libexec', 'mach-' + str(sid))): fail('id collides with built-in command')
    for k in ('name', 'working_root'):
        if not isinstance(data.get(k), str) or not data[k]: fail('missing ' + k)
    delivery = data.get('delivery', {})
    if not isinstance(delivery, dict): fail('delivery must be a table'); delivery = {}
    if type(delivery.get('max_fires_per_day', 20)) is not int or delivery.get('max_fires_per_day', 20) < 1: fail('max_fires_per_day must be a positive integer')
    if delivery.get('reply', 'chat') not in ('chat', 'inbox'): fail('delivery.reply must be chat or inbox')
    repos, units, services = (data.get(k, {}) for k in ('repos', 'units', 'services'))
    if not all(isinstance(x, dict) for x in (repos, units, services)): fail('repos, units and services must be keyed tables'); return out
    for rid, repo in repos.items():
        if not ID.fullmatch(rid) or not isinstance(repo, dict): fail('bad repo ' + rid); continue
        for k in ('path', 'remote', 'source'):
            if not isinstance(repo.get(k), str): fail('repo %s missing %s' % (rid, k))
        if type(repo.get('verified')) is not bool: fail('repo %s verified must be bool' % rid)
    for uid, u in units.items():
        if not ID.fullmatch(uid) or not isinstance(u, dict): fail('bad unit ' + uid); continue
        if u.get('kind') not in KINDS: fail('%s invalid kind' % uid)
        if u.get('parent') and u['parent'] not in units: fail('%s parent missing' % uid)
        if u.get('repo') and u['repo'] not in repos: fail('%s repo missing' % uid)
        for k in LIST_FIELDS & UNIT_FIELDS:
            if k in u and (not isinstance(u[k], list) or not all(isinstance(x, str) for x in u[k])): fail('%s %s must be string array' % (uid, k))
        roles = u.get('roles', {})
        if not isinstance(roles, dict): fail('%s roles must be table' % uid); continue
        if not roles.get('lead'): info('%s has no lead' % uid)
        if u.get('todo'): info('%s todo: %s' % (uid, u['todo']))
        for role, dest in roles.items():
            if role in ROLE_META: continue
            if not dest_ok(dest): fail('%s role %s has invalid dest' % (uid, role))
            elif dest.startswith('grokbot:') and dest not in services: fail('%s dest %s lacks service profile' % (uid, dest))
    return out


def quote(v):
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, int): return str(v)
    if isinstance(v, list): return '[' + ', '.join(quote(x) for x in v) + ']'
    return json.dumps(str(v), ensure_ascii=False)


def render_table(head, vals):
    return '[' + head + ']\n' + ''.join('%s = %s\n' % (k, quote(v)) for k, v in vals.items()) + '\n'


def render(data):
    out = ''.join('%s = %s\n' % (k, quote(data[k])) for k in TOP if k in data)
    out += '\n' + render_table('delivery', data.get('delivery', {}))
    for group in ('repos', 'units', 'services'):
        for key, vals in data.get(group, {}).items():
            h = group + '.' + (key if ID.fullmatch(key) else json.dumps(key))
            out += render_table(h, {k: v for k, v in vals.items() if k != 'roles'})
            if group == 'units' and vals.get('roles'):
                out += render_table(h + '.roles', vals['roles'])
    return out


def draft(pathname, expected):
    d = fm.load_prompt_doc(pathname)
    if d.errors: raise ValueError('; '.join(x[1] for x in d.errors))
    if d.meta.get('mach') != 1 or d.meta.get('type') != expected: raise ValueError('expected mach: 1, type: ' + expected)
    return d


def section_blocks(body):
    blocks = []
    for chunk in re.split(r'(?m)^## ', body):
        if not chunk.strip() or ':' not in chunk.splitlines()[0]: continue
        head, *lines = chunk.splitlines()
        group, key = head.split(':', 1)
        group, key = group.strip().lower(), key.strip()
        if group not in ('repo', 'unit', 'service') or not key: raise ValueError('bad heading: ## ' + head)
        vals = {}
        for line in lines:
            if not line.strip() or line.lstrip().startswith('#'): continue
            if ':' not in line: raise ValueError('expected key: value under ' + head)
            k, v = line.split(':', 1)
            k, v = k.strip(), v.strip()
            if k in vals: raise ValueError('duplicate key ' + k)
            vals[k] = fm.parse_value(v)
        blocks.append((group, key, vals))
    return blocks


def unit_from(vals):
    u, roles = {}, {}
    for k, v in vals.items():
        if k.startswith('roles.'):
            roles[k[6:]] = v
        elif k in UNIT_FIELDS: u[k] = v
        else: raise ValueError('unknown unit field ' + k)
    if roles: u['roles'] = roles
    return u


def from_setup(d):
    m = d.meta
    data = {k: m[k] for k in TOP if k != 'schema' if k in m}
    data['schema'] = 1
    data['delivery'] = {k: m[k] for k in ('max_fires_per_day', 'reply') if k in m}
    for group in ('repos', 'units', 'services'): data[group] = {}
    for group, key, vals in section_blocks(d.body):
        target = {'repo': 'repos', 'unit': 'units', 'service': 'services'}[group]
        if key in data[target]: raise ValueError('duplicate ' + group + ' ' + key)
        data[target][key] = unit_from(vals) if group == 'unit' else vals
    return data


def replace_block(text, head, block):
    pattern = r'(?m)^\[' + re.escape(head) + r'\]\s*\n'
    match = re.search(pattern, text)
    if match:
        end = re.search(r'(?m)^\[', text[match.end():])
        stop = match.end() + end.start() if end else len(text)
        return text[:match.start()] + block + text[stop:]
    return text.rstrip() + '\n\n' + block


def update_unit(text, uid, u):
    h = 'units.' + uid
    text = replace_block(text, h, render_table(h, {k:v for k,v in u.items() if k != 'roles'}))
    if 'roles' in u: text = replace_block(text, h + '.roles', render_table(h + '.roles', u['roles']))
    return text


def diff(old, new, label):
    return ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=label, tofile=label + ' (proposed)'))


def save(pathname, text, replace=False):
    if os.path.exists(pathname):
        if not replace: raise ValueError('manifest exists; use --replace')
        mc.backup_file(pathname)
    os.makedirs(os.path.dirname(pathname), exist_ok=True)
    mc.write_text(pathname, text)
