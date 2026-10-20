const $ = id => document.getElementById(id);
let papers = [], selected = new Set(), draftVersion = 0;
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
    check.onchange=()=>{check.checked?selected.add(p.id):selected.delete(p.id);render();draft(true);};
    const content=document.createElement('div'),title=document.createElement('h3'),link=document.createElement('a');
    link.textContent=p.title;link.href='https://intranet.dfki.de/research/publications/showPublication?pubid='+encodeURIComponent(p.id);link.target='_blank';link.rel='noopener noreferrer';title.append(link);
    const authors=document.createElement('p');authors.textContent=p.author;
    const meta=document.createElement('p');meta.textContent='Added '+(p.creationdate||'date unknown');
    if(p.invited||p.new){const tag=document.createElement('span');tag.className='badge';tag.textContent=p.invited?'Invited':'New';meta.append(tag);}
    content.append(title,authors,meta);row.append(check,content);$('papers').append(row);
  }
  if(!visible.length){const empty=document.createElement('p');empty.className='empty';empty.textContent=papers.length?'No publications match these filters.':'Import your publication CSV to get started.';$('papers').append(empty);}
  $('selection').textContent=selected.size?`${selected.size} publication${selected.size===1?'':'s'} selected`:'Select a publication';
  document.querySelectorAll('[data-copy],#mark,#undo').forEach(b=>b.disabled=!selected.size);
}
async function draft(autoName=false) {
  const version=++draftVersion;
  try {const d=await api('draft',{ids:[...selected],...(autoName?{}:{name:$('name').value})});if(version!==draftVersion)return;
    if(autoName)$('name').value=d.name;
    for(const key of ['body','subject','recipients'])$(key).value=selected.size?d[key]:'';
    $('unmatched').textContent=d.unmatched?`${d.unmatched} selected paper(s) have no matched eligible author. Add recipients manually.`:'';
  }catch(e){notice(e.message,true);}
}
$('search').oninput=render;$('recent').onchange=render;$('name').oninput=()=>draft();
$('clear').onclick=()=>{selected.clear();render();draft(true);};
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
async function mark(invited){try{await api('mark',{ids:[...selected],invited});await load();notice(invited?'Selected publications marked invited.':'Invited markers removed.');}catch(e){notice(e.message,true);}}
$('mark').onclick=()=>mark(true);$('undo').onclick=()=>mark(false);
load().then(data=>{if(!data.warnings.length)notice('Publications loaded from local history. Select papers to prepare an invitation.');}).catch(e=>notice(e.message,true));
