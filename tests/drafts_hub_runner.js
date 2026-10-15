/* Runs generated action scripts in a fresh Drafts mock for each request. */
const fs=require('fs'), vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
function run(req) {
  const events={messages:[],writes:[],bookmarks:0,cancelled:false,failed:null};
  function makeDraft(content='',tags=[]) {
    return {uuid:'ABCDEF01-2345-6789-ABCD-0123456789AB',content,tags:tags.slice(),
      addTag(t){if(!this.tags.includes(t))this.tags.push(t);},removeTag(t){this.tags=this.tags.filter(x=>x!==t);},update(){}};
  }
  const draft=makeDraft(req.text,req.tags||[]);
  const sandbox={Date:req.now ? class extends Date { constructor(...args){super(...(args.length?args:[req.now]));} } : Date,draft,device:{systemName:req.platform||'macOS'},
    context:{cancel(){events.cancelled=true;},fail(e){events.failed=e;}},
    editor:{load(d){events.created=d;}},Draft:{create(){return makeDraft();},query(){return (req.results||[]).map(r=>makeDraft(r.content,r.tags));}},
    Prompt:{create(){return {fieldValues:{},addSelect(k,l,labels){this.fieldValues[k]=[typeof req.choice==='number'?labels[req.choice]:req.choice];},addTextField(k){this.fieldValues[k]=req.reason||"";},addButton(){},addLabel(k,v){events.messages.push(v);},show(){return this.title==='Resend this draft?'?!req.cancelResend:!req.cancel;}};}},
    Bookmark:{find(){events.bookmarks++;if(req.missingBookmark)return null;return {};}},
    FileManager:{createForBookmark(){return {createDirectory(){return true;},writeString(p,s){if(req.throwWrite)throw Error('disk full');events.writes.push([p,s]);return !req.failWrite;}};}}
  };
  vm.createContext(sandbox);
  vm.runInContext(input.script+'\nglobalThis.validation=check('+JSON.stringify(req.text)+');',sandbox);
  return {...events,tags:draft.tags,content:draft.content,validation:sandbox.validation};
}
process.stdout.write(JSON.stringify(input.requests.map(run)));
