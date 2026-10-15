/* Flat YAML subset used by lib/frontmatter.py. No Drafts globals needed. */
function stripComment(s) {
  let quote = null;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quote) { if (c === quote) quote = null; }
    else if ('\"\''.includes(c)) quote = c;
    else if (c === '#' && (i === 0 || /[ \t]/.test(s[i-1]))) return s.slice(0,i).trimEnd();
  }
  return s.trimEnd();
}
function unquote(s) {
  s = s.trim();
  if (s.length >= 2 && s[0] === s[s.length-1] && '"\''.includes(s[0])) {
    const inner = s.slice(1,-1);
    return s[0] === '"' ? inner.replace(/\\"/g,'"').replace(/\\\\/g,'\\') : inner;
  }
  return s;
}
function parseValue(raw) {
  const s = stripComment(raw).trim();
  if (!s) return '';
  if (s[0] === '[') {
    if (!s.endsWith(']')) throw Error('unterminated list');
    let quote = null, buf = '', parts = [];
    for (const c of s.slice(1,-1)) {
      if (quote) { buf += c; if (c === quote) quote = null; }
      else if ('"\''.includes(c)) { quote = c; buf += c; }
      else if (c === ',') { parts.push(buf); buf = ''; }
      else buf += c;
    }
    parts.push(buf);
    return parts.filter(x=>x.trim()).map(unquote);
  }
  if (s[0] === '{') throw Error('nested values are not supported');
  if ('"\''.includes(s[0])) {
    if (s.length < 2 || s[s.length-1] !== s[0]) throw Error('unterminated quoted string');
    return unquote(s);
  }
  if (/^-?\d+$/.test(s)) return Number(s);
  if (s === 'true' || s === 'false') return s === 'true';
  return s;
}
function check(text) {
  const m = Object.create(null), problems = [], warnings = [], lines = String(text).split('\n');
  if (lines[0].trimEnd() !== '---') return {m, problems:['Missing frontmatter'], warnings};
  const end = lines.findIndex((x,i)=>i>0 && x.trimEnd()==='---');
  if (end < 0) problems.push('Missing closing ---');
  else for (let i=1;i<end;i++) {
    const raw=lines[i];
    if (!raw.trim() || raw.trimStart().startsWith('#')) continue;
    const hit=/^([A-Za-z_][A-Za-z0-9_-]*)\s*:(?:\s+(.*)|\s*)$/.exec(raw.trimEnd());
    if (/^[ \t]/.test(raw) || !hit) { problems.push('Invalid line '+(i+1)); continue; }
    const key=hit[1];
    if (Object.prototype.hasOwnProperty.call(m,key)) { problems.push('Duplicate '+key); continue; }
    try { m[key]=parseValue(hit[2] || ''); } catch(e) { problems.push(key+': '+e.message); }
  }
  const has=k=>Object.prototype.hasOwnProperty.call(m,k);
  const spec=typeof m.type==='string' && Object.prototype.hasOwnProperty.call(RULES.schema,m.type) ? RULES.schema[m.type] : null;
  if (!spec) problems.push('Unknown type');
  if (m.mach !== RULES.version) problems.push('Unsupported mach version');
  if (spec) {
    spec.required.forEach(k=>{if(!has(k)) problems.push('Missing '+k);});
    Object.keys(m).forEach(k=>{if(!spec.required.concat(spec.optional).includes(k)) problems.push('Unknown '+k);});
  }
  Object.keys(RULES.enums).forEach(k=>{if(has(k) && !RULES.enums[k].includes(m[k])) problems.push('Invalid '+k);});
  RULES.text_required.concat(RULES.text_optional).forEach(k=>{
    if (!has(k)) return;
    if (Array.isArray(m[k]) || typeof m[k]==='boolean') problems.push(k+': expected text');
    else if (RULES.text_required.includes(k) && String(m[k]).trim()==='') problems.push(k+': empty');
  });
  RULES.dates.forEach(k=>{if(has(k) && (k!=='due'||m[k]!=='') && !/^\d{4}-\d{2}-\d{2}$/.test(String(m[k]))) problems.push('Invalid '+k);});
  RULES.lists.forEach(k=>{if(has(k) && !Array.isArray(m[k])) problems.push(k+': expected list');});
  if (Array.isArray(m.sources)) m.sources.forEach(x=>{if(!RULES.sources.includes(x)) problems.push('Invalid source');});
  if (['task','research'].includes(m.type) && has('output') && typeof m.output==='string' && m.output.trim()==='') problems.push('Empty output');
  if (m.type==='flow' && has('input') && typeof m.input==='string' && m.input.trim()==='') warnings.push('input is empty: the flow starts with no input');
  return {m,problems,warnings};
}
