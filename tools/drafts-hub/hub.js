(() => {
  function show(title,message) {
    const p=Prompt.create(); p.title=title; p.addLabel('message',message); p.addButton('OK'); p.show();
  }
  function cancel() { context.cancel(); }
  function next(m,path) {
    const verbs={'subsystem-setup':'new','unit-setup':'unit','role-change':'role'};
    return verbs[m.type] ? 'mach subsystem '+verbs[m.type]+' '+(m.id||m.subsystem)+' --from '+path : 'mach run --inbox';
  }
  try {
    const templates=HUB.templates, labels=templates.map(t=>t.label).concat(['Check frontmatter','Send to mach','Show next step']);
    const menu=Prompt.create(); menu.title=HUB.name;
    menu.addSelect('choice','Action',labels,[labels[0]],false); menu.addButton('Go');
    if (!menu.show()) { cancel(); return; }
    const choice=labels.indexOf((menu.fieldValues.choice||[])[0]);
    if (choice<0) { cancel(); return; }
    if (choice<templates.length) {
      const t=templates[choice], d=Draft.create(), tomorrow=new Date();
      tomorrow.setDate(tomorrow.getDate()+1);
      const date=tomorrow.getFullYear()+'-'+String(tomorrow.getMonth()+1).padStart(2,'0')+'-'+String(tomorrow.getDate()).padStart(2,'0');
      d.content=t.text.replace(/^due:[ \t]*(?:""|'')?[ \t]*(?:#.*)?$/m,'due: '+date);
      HUB.tags.concat([t.type]).forEach(tag=>d.addTag(tag)); d.update(); editor.load(d); return;
    }
    const result=check(draft.content), m=result.m;
    if (result.problems.length) { show('Frontmatter problems',result.problems.join('\n')); return; }
    if (choice===templates.length) { show('Frontmatter','Valid '+m.type+(result.warnings.length?'\nWarning: '+result.warnings.join('\n'):'')); return; }
    const folder=HUB.destinations[m.type]||HUB.destinations.default;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(draft.uuid)) throw Error('Invalid Drafts UUID');
    const path=folder+'/drafts-'+draft.uuid.toLowerCase()+'.md';
    if (choice===templates.length+2) { show('Next step',next(m,path)); return; }
    if (draft.tags.includes('mach-sent')) {
      const confirm=Prompt.create(); confirm.title='Resend this draft?'; confirm.addButton('Resend');
      if (!confirm.show()) { cancel(); return; }
    }
    let reason='';
    if (device.systemName==='macOS') {
      try {
        const bookmark=Bookmark.find(HUB.bookmark);
        if (!bookmark) throw Error('Missing '+HUB.bookmark+' folder bookmark');
        const fm=FileManager.createForBookmark(bookmark);
        fm.createDirectory('/files/inbox'); fm.createDirectory('/'+folder);
        if (!fm.writeString('/'+path,draft.content)) throw Error('FileManager.writeString returned false');
        draft.removeTag('mach-outbox'); draft.addTag('mach-sent'); draft.update();
        show('Sent to mach',path+'\n\n'+next(m,path)); return;
      } catch(e) { reason=String(e)+'\n'; }
    }
    draft.addTag('mach-outbox'); draft.update();
    show('Saved to outbox',reason+'tagged mach-outbox; run mach inbox pull-drafts --apply on the Mac');
  } catch(e) { context.fail(String(e)); }
})();
