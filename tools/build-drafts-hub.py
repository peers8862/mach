#!/usr/bin/env python3
"""Build a deterministic Drafts hub from a project adapter and Markdown templates."""
import argparse
import json
import pathlib
import re
import sys
import uuid
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'lib'))
import mach_common as mc
import frontmatter as fm
ROOT = pathlib.Path(__file__).resolve().parents[1]
def uid(s):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'machine-flows/' + s)).upper()
def main(out=None, name=None, templates=None, adapter=None):
    adapter = json.loads(pathlib.Path(adapter or ROOT / 'config/drafts/mach.json').read_text())
    NAME = name or adapter['name']
    GROUP = adapter['group_uuid']
    if name and name != adapter['name']:
        adapter.update(action_uuid=uid(name), step_uuid=uid(name+'/script'))
    adapter['name'] = NAME
    out = pathlib.Path(out) if out else pathlib.Path(mc.mf_root()) / 'drafts/Importing' / (re.sub(r'[^A-Za-z0-9]+', '-', NAME).strip('-')+'.draftsAction')
    tdir = pathlib.Path(templates) if templates else pathlib.Path(mc.mf_root()) / 'ai-authored/templates'
    entries = []
    for item in adapter['templates']:
        text = (tdir / item['file']).read_text(encoding='utf-8')
        doc = fm.parse_text(text)
        entries.append(dict(item, text=text, type=doc.meta['type']))
    rules = dict(schema=fm.SCHEMA, version=fm.SCHEMA_VERSION,
                 enums=dict(permission=["read-only","write"], tool=fm.TOOLS, machine=fm.machines(), approval=fm.APPROVALS, depth=fm.DEPTHS, reply=['chat','inbox']),
                 sources=fm.SOURCES, text_required=fm.TEXT_REQUIRED, text_optional=fm.TEXT_OPTIONAL, dates=fm.DATE_KEYS, lists=fm.LIST_KEYS)
    script = 'const HUB = '+json.dumps(dict(adapter, templates=entries), ensure_ascii=False)+';\n'
    script += 'const RULES = '+json.dumps(rules, ensure_ascii=False)+';\n'
    for source in ('frontmatter.js', 'hub.js'):
        script += (ROOT / 'tools/drafts-hub' / source).read_text(encoding='utf-8')+'\n'
    action = {'uuid':adapter['action_uuid'],'name':NAME,'groupUUID':GROUP,
      'steps':[{'uuid':adapter['step_uuid'],'isEnabled':True,'platforms':3,'type':'script','data':{'script':script,'allowAsync':'false'}}],
      'assignTags':[],'shortName':'','shouldConfirm':False,'disposition':0,'groupDisposition':0,'visibility':2016,
      'backingActionType':'action','backingPlatforms':3,'backingIsSeparator':False,'logLevel':1,'notificationType':1,
      'tintColor':'yellow','icon':'460-api2','keyUseIcon':False,'actionDescription':'Create and validate mach drafts; drop them into machine-flows inbox on Mac.',
      'keyCommand':{'input':'','commandKey':False,'controlKey':False,'shiftKey':False,'optionKey':False,'type':'action','discoverabilityTitle':NAME}}
    out.write_text(json.dumps(action, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(out)
if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ('name', 'templates', 'out', 'adapter'):
        ap.add_argument('--'+flag)
    a = ap.parse_args()
    main(a.out, a.name, a.templates, a.adapter)
