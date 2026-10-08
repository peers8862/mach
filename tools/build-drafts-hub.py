#!/usr/bin/env python3
"""Build the Mach Hub Drafts action from the shared Markdown templates.

Config: [drafts] hub_name, hub_group_uuid (the Drafts action group to import into; default: a stable generated id).

usage: build-drafts-hub.py [--name NAME] [--templates DIR] [--out FILE]
  --name       action name (default: [drafts] hub_name in the mach config, else "Mach Hub")
  --templates  folder of prompt templates (default: <machine-flows>/ai-authored/templates)
  --out        output file (default: <machine-flows>/drafts/Importing/<Name-with-dashes>.draftsAction)
"""
import argparse
import json
import os
import pathlib
import re
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'lib'))
import mach_common as mc  # noqa: E402

NS = uuid.NAMESPACE_URL

def uid(s): return str(uuid.uuid5(NS, 'machine-flows/' + s)).upper()

def default_name():
    return str(mc.load_config().get('drafts.hub_name', '') or 'Mach Hub')

def default_out(name):
    slug = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-') or 'Mach-Hub'
    return pathlib.Path(mc.mf_root()) / 'drafts' / 'Importing' / (slug + '.draftsAction')

def main(out=None, name=None, templates=None):
    """Write the action JSON to `out` (default: drafts/Importing/<Name>.draftsAction)."""
    NAME = name or default_name()
    out = pathlib.Path(out) if out else default_out(NAME)
    GROUP = str(mc.load_config().get('drafts.hub_group_uuid', '') or uid('group'))
    TEMPLATES = pathlib.Path(templates) if templates else pathlib.Path(mc.mf_root()) / 'ai-authored' / 'templates'
    entries = []
    for p in sorted(TEMPLATES.glob('*.md')):
        if p.name == 'README.md': continue
        text = p.read_text(encoding='utf-8')
        title = re.search(r'(?m)^title:\s*(.+)$',text)
        typ = re.search(r'(?m)^type:\s*(.+)$',text)
        if not title or not typ: raise ValueError('template needs type and title: ' + str(p))
        entries.append({'title':title.group(1).strip(), 'type':typ.group(1).strip(), 'text':text})
    requirements = {
      'task':['mach','type','title','goal','tool','output'],
      'research':['mach','type','title','question','output'],
      'flow':['mach','type','title','flow','input'],
      'subsystem-prompt':['mach','type','title','subsystem','unit'],
      'subsystem-setup':['mach','type','title','id','name','working_root','max_fires_per_day','reply'],
      'unit-setup':['mach','type','title','subsystem','unit'],
      'role-change':['mach','type','title','subsystem','unit','role','to','date','reason']}
    script = '''(() => {
  const TEMPLATES = __TEMPLATES__;
  const REQUIRED = __REQUIRED__;
  function show(title,message){const p=Prompt.create();p.title=title;p.addLabel('message',message);p.addButton('OK');p.show();}
  function frontmatter(s){
    const lines=String(s).split(/\\r?\\n/);if(lines[0]!=='---')throw Error('First line must be ---');
    const end=lines.indexOf('---',1);if(end<0)throw Error('Missing closing ---');
    const m={};for(let i=1;i<end;i++){const line=lines[i].replace(/\\s+#.*$/,'').trim();if(!line||line.startsWith('#'))continue;
      const hit=/^([a-z_]+):\\s*(.*)$/.exec(line);if(!hit)throw Error('Invalid frontmatter at line '+(i+1));
      if(Object.prototype.hasOwnProperty.call(m,hit[1]))throw Error('Duplicate '+hit[1]);m[hit[1]]=hit[2].trim().replace(/^["']|["']$/g,'');}
    return m;
  }
  function check(s){const m=frontmatter(s),problems=[];if(m.mach!=='1')problems.push('mach must be 1');
    if(!REQUIRED[m.type])problems.push('Unknown type: '+m.type);
    else REQUIRED[m.type].forEach(k=>{if(!Object.prototype.hasOwnProperty.call(m,k)||String(m[k]).trim()==='')problems.push('Missing '+k);});
    const optional={task:['path','machine','due','approval','tags'],research:['depth','tool','sources','machine','due','approval','tags'],flow:['machine','due','approval','output','tags'],'subsystem-prompt':['to','role','reply','tags','machine','due'],'subsystem-setup':['linear_team','note_dest','due','tags'],'unit-setup':['due','tags'],'role-change':['due','tags']};
    if(REQUIRED[m.type])Object.keys(m).forEach(k=>{if(!REQUIRED[m.type].includes(k)&&!(optional[m.type]||[]).includes(k))problems.push('Unknown '+k);});
    if(m.reply&&!['chat','inbox'].includes(m.reply))problems.push('reply must be chat or inbox');
    return {m,problems};
  }
  function choose(){const p=Prompt.create();p.title=__NAME__;const labels=TEMPLATES.map(t=>'New: '+t.title).concat(['Check frontmatter','Send to mach','Show next step']);
    p.addSelect('choice','Action',labels,[labels[0]],false);p.addButton('Go');if(!p.show())return null;return labels.indexOf((p.fieldValues.choice||[])[0]);}
  function next(m,path){if(m.type==='subsystem-setup')return 'mach subsystem new '+m.id+' --from '+path;
    if(m.type==='unit-setup')return 'mach subsystem unit '+m.subsystem+' --from '+path;
    if(m.type==='role-change')return 'mach subsystem role '+m.subsystem+' --from '+path;
    return 'mach run --inbox';}
  try {const choice=choose();if(choice===null||choice<0)return;
    if(choice<TEMPLATES.length){const t=TEMPLATES[choice],d=Draft.create();let body=t.text;
      const tomorrow=new Date(Date.now()+86400000).toISOString().slice(0,10);body=body.replace(/^due:\\s*(?:""|''|)\\s*$/m,'due: '+tomorrow);
      d.content=body;d.addTag('mach');d.addTag(t.type);d.update();editor.load(d);return;}
    const result=check(draft.content),m=result.m;if(result.problems.length){show('Frontmatter problems',result.problems.join('\\n'));return;}
    if(choice===TEMPLATES.length){show('Frontmatter', 'Valid '+m.type);return;}
    const setup=['subsystem-setup','unit-setup','role-change'].includes(m.type),folder=setup?'subsystems':'prompts';
    const slug=String(m.title||m.type).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,40);
    const date=new Date(),stamp=date.getFullYear()+String(date.getMonth()+1).padStart(2,'0')+String(date.getDate()).padStart(2,'0')+'-'+String(date.getHours()).padStart(2,'0')+String(date.getMinutes()).padStart(2,'0');
    const path='files/inbox/'+folder+'/'+stamp+'-'+slug+'.md';
    if(choice===TEMPLATES.length+2){const sent=/Sent to mach: (files\/inbox\/[^\s]+)/.exec(draft.content);show('Next step',next(m,sent?sent[1]:'<path-to-draft.md>'));return;}
    let saved=false;
    try {const fm=FileManager.createForBookmark(Bookmark.findOrCreate('machine-flows'));fm.createDirectory('/files/inbox');fm.createDirectory('/files/inbox/'+folder);saved=!!fm.writeString('/'+path,draft.content);}
    catch(e){saved=false;}
    if(!saved){draft.addTag('mach-outbox');draft.update();show('Saved to outbox','The machine-flows folder bookmark is unavailable. On a Mac, grant the folder and send again.');return;}
    draft.addTag('mach-sent');draft.content+='\\n\\nSent to mach: '+path+'\\n';draft.update();show('Sent to mach',path+'\\n\\n'+next(m,path));
  }catch(e){show(__NAME__,String(e));context.fail(String(e));}
})();'''
    script = script.replace('__NAME__',"'" + NAME.replace('\\', '\\\\').replace("'", "\\'") + "'").replace('__TEMPLATES__',json.dumps(entries,ensure_ascii=False)).replace('__REQUIRED__',json.dumps(requirements))
    action = {'uuid':uid(NAME),'name':NAME,'groupUUID':GROUP,
      'steps':[{'uuid':uid(NAME+'/script'),'isEnabled':True,'platforms':3,'type':'script','data':{'script':script,'allowAsync':'false'}}],
      'assignTags':[],'shortName':'','shouldConfirm':False,'disposition':0,'groupDisposition':0,'visibility':2016,
      'backingActionType':'action','backingPlatforms':3,'backingIsSeparator':False,'logLevel':1,'notificationType':1,
      'tintColor':'yellow','icon':'460-api2','keyUseIcon':False,'actionDescription':'Create and validate mach drafts; drop them into machine-flows inbox on Mac.',
      'keyCommand':{'input':'','commandKey':False,'controlKey':False,'shiftKey':False,'optionKey':False,'type':'action','discoverabilityTitle':NAME}}
    out.write_text(json.dumps(action,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out)

if __name__=='__main__':
    ap = argparse.ArgumentParser(description='Build the Mach Hub Drafts action.')
    ap.add_argument('--name'); ap.add_argument('--templates'); ap.add_argument('--out')
    a = ap.parse_args()
    main(a.out, a.name, a.templates)
