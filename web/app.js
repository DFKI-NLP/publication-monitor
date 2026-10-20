const $ = id => document.getElementById(id);
let papers = [], selected = new Set(), draftVersion = 0, drafts = [], activeDraft = 0, staff = [];
function notice(text, error=false) { $('notice').textContent=text; $('notice').classList.toggle('error',error); }
async function api(path, body) {
  const response=await fetch('/api/'+path, body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json(); if(!response.ok) throw Error(result.error); return result;
}
async function load() { const data=await api('publications'); papers=data.papers; $('download').href=data.export_url; render(); if(data.warnings.length)notice(data.warnings.join(' · '),true); return data; }
function render() {
  const query=$('search').value.toLocaleLowerCase(), cutoff=new Date(); cutoff.setDate(cutoff.getDate()-180);
  const date=[cutoff.getFullYear(),String(cutoff.getMonth()+1).padStart(2,'0'),String(cutoff.getDate()).padStart(2,'0')].join('-');
  const visible=papers.filter(p=>(!$('recent').checked||!p.date||p.date>=date)&&(`${p.title} ${p.author}`).toLocaleLowerCase().includes(query)).sort((a,b)=>b.date.localeCompare(a.date)||Number(b.id)-Number(a.id));
  $('count').textContent=`${visible.length} shown · ${papers.length} saved · ${selected.size} selected`;
  $('papers').replaceChildren();
  for(const p of visible) {
    const row=document.createElement('article');row.className='paper'+(selected.has(p.id)?' selected':'');
    const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(p.id);check.setAttribute('aria-label','Select '+p.title);
    check.onchange=()=>{check.checked?selected.add(p.id):selected.delete(p.id);render();draft();};
    const content=document.createElement('div'),title=document.createElement('h3'),link=document.createElement('a');
    link.textContent=p.title;link.href='https://intranet.dfki.de/research/publications/showPublication?pubid='+encodeURIComponent(p.id);link.target='_blank';link.rel='noopener noreferrer';title.append(link);
    const authors=document.createElement('p');authors.textContent=p.author;
    const meta=document.createElement('p');meta.textContent='Added '+(p.creationdate||'date unknown');
    if(p.invited||p.new){const tag=document.createElement('span');tag.className='badge';tag.textContent=p.invited?'Invited':'New';meta.append(tag);}
    content.append(title,authors,meta);row.append(check,content);$('papers').append(row);
  }
  if(!visible.length){const empty=document.createElement('p');empty.className='empty';empty.textContent=papers.length?'No publications match these filters.':'Import your publication CSV to get started.';$('papers').append(empty);}
  $('selection').textContent=selected.size?`${selected.size} publication${selected.size===1?'':'s'} selected`:'Select a publication';
  document.querySelectorAll('[data-copy],#mark,#undo').forEach(b=>b.disabled=!drafts.length);
}
function storeDraft() {
  const d=drafts[activeDraft]; if(!d)return;
  for(const key of ['name','body','subject','recipients'])d[key]=$(key).value;
}
function showDraft() {
  hideSuggestions();
  const d=drafts[activeDraft];
  for(const key of ['name','body','subject','recipients'])$(key).value=d?d[key]:'';
  $('draft-choice').disabled=!d;
  $('draft-choice').value=String(activeDraft);
  $('unmatched').textContent=d?.unmatched?'No matched eligible author for this paper. Enter the colleague’s name and address manually.':'';
  document.querySelectorAll('[data-copy],#mark,#undo').forEach(b=>b.disabled=!d);
}
async function draft() {
  const version=++draftVersion;
  drafts=[]; showDraft(); $('draft-choice').replaceChildren();
  try {
    const result=await api('drafts',{ids:[...selected]}); if(version!==draftVersion)return;
    drafts=result.drafts;activeDraft=0;
    drafts.forEach((d,i)=>{const option=document.createElement('option');option.value=i;option.textContent=`${d.name||'Unmatched paper '+d.ids[0]} · ${d.ids.length} paper(s)`;$('draft-choice').append(option);});
    showDraft();
  }catch(e){notice(e.message,true);}
}
$('draft-choice').onchange=()=>{storeDraft();++draftVersion;activeDraft=Number($('draft-choice').value);showDraft();};
async function updateGreeting(){
  storeDraft();const d=drafts[activeDraft];if(!d)return;
  const version=++draftVersion;
  try{const result=await api('draft',{ids:d.ids,name:d.name});if(version!==draftVersion)return;d.body=result.body;$('body').value=d.body;}
  catch(e){notice(e.message,true);}
};
function hideSuggestions(){
  $('name-suggestions').hidden=true;$('name').setAttribute('aria-expanded','false');
  $('name').removeAttribute('aria-activedescendant');
}
function normalizeName(text){return text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();}
function suggestNames(){
  const query=normalizeName($('name').value).trim();
  const matches=query?staff.filter(person=>query.split(/\s+/).every(word=>normalizeName(person.name+' '+person.email).includes(word))).slice(0,8):[];
  const list=$('name-suggestions');list.replaceChildren();
  matches.forEach((person,i)=>{
    const option=document.createElement('button');option.type='button';option.role='option';option.id='colleague-'+i;option.tabIndex=-1;
    option.textContent=person.name+' · '+person.email;
    option.onpointerdown=e=>e.preventDefault();
    option.onclick=()=>{
      $('name').value=person.name;$('recipients').value=person.email;
      const d=drafts[activeDraft];
      if(d){d.unmatched=false;storeDraft();}
      $('unmatched').textContent='';
      if(d)$('draft-choice').options[activeDraft].textContent=person.name+' · '+d.ids.length+' paper(s)';
      else notice('Colleague selected. Select a publication to prepare an invitation.');
      hideSuggestions();updateGreeting();$('name').focus();
    };
    list.append(option);
  });
  list.hidden=!matches.length;$('name').setAttribute('aria-expanded',String(!!matches.length));
  $('name').removeAttribute('aria-activedescendant');
}
$('name').oninput=()=>{suggestNames();updateGreeting();};
$('name').onfocus=suggestNames;
$('name').onblur=hideSuggestions;
$('name').onkeydown=e=>{
  const options=[...$('name-suggestions').children];if($('name-suggestions').hidden)return;
  let index=options.findIndex(option=>option.id===$('name').getAttribute('aria-activedescendant'));
  if(e.key==='Escape'){hideSuggestions();return;}
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();index=(index+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;
    options.forEach((option,i)=>option.setAttribute('aria-selected',String(i===index)));
    $('name').setAttribute('aria-activedescendant',options[index].id);
  }else if(e.key==='Enter'&&index>=0){e.preventDefault();options[index].click();}
};
api('staff').then(data=>{staff=data.staff;if(document.activeElement===$('name'))suggestNames();}).catch(e=>notice(e.message,true));
$('search').oninput=render;$('recent').onchange=render;
$('clear').onclick=()=>{selected.clear();render();draft();};
$('import').onclick=()=>$('file').click();
$('file').onchange=async()=>{
  const file=$('file').files[0];if(!file)return;
  $('import').disabled=true;notice('Processing '+file.name+'…');
  try{if(file.size>24*1024*1024)throw Error('Choose a CSV smaller than 24 MB.');
    const result=await api('import',{csv:await file.text()});await load();await draft();
    notice(`Imported ${result.imported} publications · ${result.new} newly added. Invitation history preserved.`);
  }catch(e){notice(e.message,true);}finally{$('import').disabled=false;$('file').value='';}
};
document.querySelectorAll('[data-copy]').forEach(button=>button.onclick=async()=>{
  const field=$(button.dataset.copy);
  try{await navigator.clipboard.writeText(field.value);notice('Copied. Paste into Outlook to send manually.');}
  catch(e){field.focus();field.select();notice('Select and copy the highlighted text with Ctrl+C (or ⌘C).');}
});
async function mark(invited){const d=drafts[activeDraft];if(!d)return;try{await api('mark',{ids:d.ids,invited});await load();notice(invited?'This draft’s publications marked invited.':'This draft’s invited markers removed.');}catch(e){notice(e.message,true);}}
$('mark').onclick=()=>mark(true);$('undo').onclick=()=>mark(false);
load().then(data=>{if(!data.warnings.length)notice('Publications loaded from local history. Select papers to prepare an invitation.');}).catch(e=>notice(e.message,true));
