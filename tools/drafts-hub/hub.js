(() => {
  function show(title,message) {
    const p=Prompt.create(); p.title=title; p.addLabel('message',message); p.addButton('OK'); p.show();
  }
  function cancel() { context.cancel(); }
  function next(m,path) {
    if (m.type==='subsystem-prompt') return 'mach run '+path+' --dry-run\nReview routing, then run: mach run '+path;
    const verbs={'subsystem-setup':'new','unit-setup':'unit','role-change':'role'};
    return verbs[m.type] ? 'mach subsystem '+verbs[m.type]+' '+(m.id||m.subsystem)+' --from '+path : 'mach run --inbox';
  }
  try {
    const templates=HUB.templates, labels=templates.map(t=>t.label).concat(HUB.actions || ['Check frontmatter','Send to mach','Show next step']);
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
    const action=labels[choice];
    if (action==='Quick capture') {
      draft.addTag('mach-outbox'); draft.update();
      show('Captured','Tagged mach-outbox for triage; the collector wraps plain notes as task briefs.'); return;
    }
    if (['Status','Open result','Approve','Reject'].includes(action)) {
      const uuidPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      const links=draft.tags.filter(t=>t.startsWith('mach-request-'));
      const request=draft.tags.includes('mach-result') ? (links.length===1 ? links[0].slice(13) : '') : draft.uuid;
      if (!uuidPattern.test(request)) throw Error('Missing or invalid request UUID');
      const id=request.toLowerCase(), tag='mach-request-'+id;
      const results=Draft.query('', 'all', ['mach-result',tag], false, 'modified', true, false);
      if (action==='Open result') {
        if (results.length===1) editor.load(results[0]);
        else show('Result',results.length ? 'Multiple linked results; resolve duplicate results first.' : 'Not connected yet: no linked mach-result draft.');
        return;
      }
      if (action==='Status') {
        show('Status',results.length===1 ? results[0].content : 'Not connected yet: mach does not publish run status to Drafts.');
        return;
      }
      if (device.systemName!=='macOS') {
        show('Decision','Not connected yet: decisions require the Mac folder bookmark.'); return;
      }
      const decision=Prompt.create(); decision.title=action+' request?';
      decision.addTextField('reason','Reason',''); decision.addButton(action);
      if (!decision.show()) { cancel(); return; }
      const reason=String(decision.fieldValues.reason||'').trim();
      if (action==='Reject' && !reason) { show('Decision','A rejection reason is required.'); return; }
      const bookmark=Bookmark.find(HUB.bookmark);
      if (!bookmark) throw Error('Missing '+HUB.bookmark+' folder bookmark');
      const fm=FileManager.createForBookmark(bookmark);
      if (!fm.createDirectory('/files/inbox/decisions')) throw Error('Cannot create decisions directory');
      const path='/files/inbox/decisions/'+id+'.md';
      const body='---\nrequest: '+id+'\ndecision: '+action.toLowerCase()+'\n---\n'+reason+'\n';
      if (!fm.writeString(path,body)) throw Error('Decision write failed');
      show('Decision saved',path+'\nNot connected yet: mach does not consume decision files. Use mach approve/reject with the run ID.'); return;
    }
    const result=check(draft.content), m=result.m;
    if (result.problems.length) { show('Frontmatter problems',result.problems.join('\n')); return; }
    if (action==='Check frontmatter') { show('Frontmatter','Valid '+m.type+(result.warnings.length?'\nWarning: '+result.warnings.join('\n'):'')); return; }
    const folder=HUB.destinations[m.type]||HUB.destinations.default;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(draft.uuid)) throw Error('Invalid Drafts UUID');
    const path=folder+'/drafts-'+draft.uuid.toLowerCase()+'.md';
    if (action==='Show next step') { show('Next step',next(m,path)); return; }
    if (HUB.send_types && !HUB.send_types.includes(m.type)) throw Error('This send action requires: '+HUB.send_types.join(', '));
    if (HUB.subsystem && m.subsystem!==HUB.subsystem) throw Error('Brief subsystem must be '+HUB.subsystem);
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
