'use strict';

FundingModel.ready.then(()=>{
const {opportunities,getResults,amountText}=FundingModel;
const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const icon=name=>`<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={query:'',type:'all',location:'all',community:'all',amount:'all',goal:'all',sort:'recommended',savedOnly:false,layout:'grid',profile:null,saved:[]};
FundingModel.filterKeys.forEach(key=>{if(!(key in state))state[key]='all';});
state.includeUnknown=true;state.aiIds=null;
let insights;
const providers={
  nutrien:{badge:'AFOA',tone:'peach'},
  mnbc:{badge:'MNBC',tone:'sage'},
  psssp:{badge:'ISC',tone:'blue'},
  inuit:{badge:'ISC',tone:'blue'}
};
const tones=['peach','sage','blue'];
const providerTone=name=>tones[[...name].reduce((sum,ch)=>sum+ch.charCodeAt(0),0)%3];
const providerBadge=name=>name.split(/[^A-Za-z0-9]+/).filter(Boolean).map(w=>w[0]).join('').slice(0,4).toUpperCase();
const programArt={
  nutrien:{asset:'study-kit',tone:'peach'},
  mnbc:{asset:'skills-path',tone:'sage'},
  psssp:{asset:'paper-portfolio',tone:'blue'},
  inuit:{asset:'paper-portfolio',tone:'sage'}
};
const artFor=item=>programArt[item.id]||{asset:item.type==='Scholarship'?'study-kit':'paper-portfolio',tone:providerTone(item.provider)};
function programNextSteps(item){
  const first={
    nutrien:['Check the current award cycle','Open the current youth awards page.'],
    mnbc:['Talk to the STEPS team','Ask which education or skills support is available.'],
    psssp:['Contact your local organization','Start with your First Nation or designated organization.'],
    inuit:['Contact your regional organization','Ask the relevant Inuit organization about support.']
  }[item.id]||['Confirm the application window','Ask the provider about current dates, documents and steps.'];
  return [first,['Confirm requirements','Check eligibility, documents and application dates.'],['Follow the provider’s process','Use their current instructions to take the next step.']];
}
function programActions(item){
  const saved=state.saved.includes(item.id);
  return `<a class="button button-light" href="${item.url}" target="_blank" rel="noopener noreferrer">Visit provider ${icon('arrow-up')}</a><button class="button button-outline" data-save="${item.id}" aria-pressed="${saved}" aria-label="${saved?'Remove':'Save'} ${escapeHTML(item.title)}${saved?' from':' to'} My saved">${icon('bookmark')}${saved?'Saved':'Save'}</button>`;
}
try{
  const values=JSON.parse(localStorage.getItem('funding-navigator-saved')||'[]');
  if(Array.isArray(values))state.saved=[...new Set(values.filter(id=>opportunities.some(item=>item.id===id)))];
}catch{}
let toastTimer;
let previousRoute='';
let detailOrigin=null;
let detailRecordIds=[];
let detailRecordId=null;

function badge(item){
  const p=providers[item.id]||{badge:providerBadge(item.provider),tone:providerTone(item.provider)};
  return `<span class="provider-badge ${p.tone}" aria-hidden="true">${p.badge}</span>`;
}
function saveButton(item,extraClass=''){
  const saved=state.saved.includes(item.id);
  return `<button class="save-button ${saved?'is-saved':''} ${extraClass}" data-save="${item.id}" aria-label="${saved?'Remove':'Save'} ${escapeHTML(item.title)}${saved?' from':' to'} My saved" aria-pressed="${saved}">${icon('bookmark')}</button>`;
}
function previewCard(item){
  return `<article class="preview-card"><div class="preview-card-top">${badge(item)}${saveButton(item)}</div><h3><button data-detail="${item.id}">${escapeHTML(item.title)}</button></h3><p class="preview-amount ${item.amount===null?'is-unknown':''}">${item.amount===null?'Varies':amountText(item)}</p><p class="preview-amount-note">${item.amount===null?'Ask the provider':'Up to · example amount'}</p><p class="preview-card-location">${escapeHTML(item.location)}</p><button class="preview-detail" data-detail="${item.id}">View details ${icon('arrow')}</button></article>`;
}
function card(item){
  return `<article class="opportunity-card"><div class="card-top">${badge(item)}<p class="card-provider">${escapeHTML(item.provider)}<span>${item.type==='Scholarship'?'Scholarship & award':'Funding program'}</span></p>${saveButton(item)}</div><div class="card-content"><h2 class="card-title"><button data-detail="${item.id}">${escapeHTML(item.title)}</button></h2><div class="card-amount ${item.amount===null?'is-unknown':''}">${item.amount===null?'Varies':amountText(item)}<small>${item.amount===null?'Confirm amount':'Up to · example'}</small></div></div><div class="card-meta"><span>${icon('pin')}${escapeHTML(item.location)}</span><span class="community-tag">${escapeHTML(item.community.join(' · '))}</span></div><div class="card-bottom"><span class="card-timing">${icon('compass')}${escapeHTML(item.timing)}</span><button class="card-link" data-detail="${item.id}">View details ${icon('arrow')}</button></div></article>`;
}
function renderHome(){ $('#home-cards').innerHTML=opportunities.slice(0,3).map(previewCard).join(''); }
function renderSavedCount(){
  $$('.save-count').forEach(el=>{el.textContent=state.saved.length;el.hidden=state.saved.length===0;});
}
function profileApplied(){
  return state.profile&&['community','location','goal'].every(key=>state[key]===state.profile[key])&&['community','location','goal'].some(key=>state[key]!=='all');
}
function renderFilters(){
  $$('[data-filter]').forEach(el=>{
    const value=state[el.dataset.filter];
    el.querySelector('[data-multiple]')?.remove();
    if(Array.isArray(value)){const option=document.createElement('option');option.value='multiple';option.textContent=value.join(' · ');option.dataset.multiple='true';option.disabled=true;el.append(option);el.value='multiple';}else el.value=value;
    el.closest('.select-field')?.classList.toggle('is-active',value!=='all');
  });
  $('#funding-sort').value=state.sort;
  const filters=FundingModel.filterKeys.filter(key=>state[key]!=='all');
  const personal=profileApplied();
  const filterText=key=>insights?.filterLabel(key,state[key])||preferenceText(key,state[key]);
  $('#active-filters').hidden=filters.length===0;
  $('#active-filters').innerHTML=(personal&&filters.length?'<span>Your preferences</span>':'')+filters.map(key=>`<button data-remove-filter="${key}" aria-label="Remove ${key} filter">${escapeHTML(filterText(key))} ${icon('close')}</button>`).join('');
  $('.clear-filters').hidden=FundingModel.filterKeys.every(key=>state[key]==='all')&&state.includeUnknown;
  $('#include-unknown').checked=state.includeUnknown;
  const extras=filters.filter(key=>!['community','location','type','amount'].includes(key));
  $('#more-filter-count').textContent=extras.length||'';
  $$('[data-layout]').forEach(button=>{const selected=button.dataset.layout===state.layout;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});
}
function renderResults(){
  const rows=getResults(state);
  $('#results-grid').innerHTML=rows.map(card).join('');
  $('#results-grid').classList.toggle('list-layout',state.layout==='list');
  $('#results-grid').hidden=rows.length===0;
  $('#empty-state').hidden=rows.length!==0;
  $('#results-count').innerHTML=`${state.savedOnly?'Saved opportunities':'Opportunities'} <strong>${rows.length}</strong>`;
  const noSaved=state.savedOnly&&state.saved.length===0;
  $('#empty-title').textContent=noSaved?'Your next steps belong here.':'No opportunities found.';
  $('#empty-description').textContent=noSaved?'Save an opportunity to find it here later.':'Try another search or adjust your filters.';
  $('#reset-results').innerHTML=noSaved?`Explore funding ${icon('arrow')}`:`Reset filters ${icon('arrow')}`;
  $('#explorer-title').textContent=state.savedOnly?'My saved':'Explore funding';
  $('#explorer-description').textContent=state.savedOnly?'Your next steps, in one place.':'Find support for your next chapter.';
  renderFilters();renderSavedCount();
}
function preferenceText(key,value){
  if(Array.isArray(value))return value.join(' · ');
  if(!value)return 'Not set';
  if(key==='community')return value==='all'?'All communities':value;
  if(key==='location')return value==='Other'?'Elsewhere in Canada':value==='all'?'Across Canada':value;
  return value==='training'?'Skills & training':value==='postsecondary'?'University or college':'Still exploring';
}
function renderProfile(){
  const p=state.profile;
  $('#profile-content').innerHTML=`<div class="profile-heading"><span>${icon('user')}</span><div><h2>Your conversation context</h2><p>Built from what you choose to share.</p></div></div><dl class="profile-list">${[['community','Community'],['location','Study location'],['goal','Study plans']].map(([key,label])=>`<div><dt>${label}</dt><dd class="${p?'':'unset'}">${escapeHTML(preferenceText(key,p?.[key]))}</dd></div>`).join('')}</dl><div class="profile-actions"><button class="button ${p?'button-outline':''}" data-assistant="match">${p?'Continue the conversation':'Tell me about your plans'} ${icon('spark')}</button>${p?`<button class="button" data-use-profile>Explore this context ${icon('arrow')}</button>`:''}</div>${p?'<button class="profile-clear text-link" data-clear-profile>Clear conversation context</button>':''}`;
}
function route(){
  const hash=location.hash.slice(1);
  const workspace=['explore','saved','profile','statistics'].includes(hash);
  const profile=hash==='profile';
  const statistics=hash==='statistics';
  const current=workspace?hash:'home';
  state.savedOnly=hash==='saved';
  $('#home-view').hidden=workspace;
  $('#workspace-view').hidden=!workspace;
  $('#explore-view').hidden=!workspace||profile||statistics;
  $('#profile-view').hidden=!profile;
  $('#statistics-view').hidden=!statistics;
  document.body.classList.toggle('workspace-mode',workspace);
  $('#workspace-location').textContent=statistics?'Statistics':profile?'My profile':state.savedOnly?'My saved':'Explore funding';
  $$('[data-nav]').forEach(link=>{if(workspace&&link.dataset.nav===hash)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  if(statistics)insights?.renderStatistics();else if(profile)renderProfile();else if(workspace)renderResults();
  document.title=workspace?`${statistics?'Statistics':profile?'My profile':state.savedOnly?'My saved':'Explore funding'} — Funding Navigator`:'Funding Navigator — Find your next chapter';
  if(hash==='how-it-works'){
    requestAnimationFrame(()=>$('#how-it-works').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
  }else if(previousRoute!==current){
    window.scrollTo({top:0,behavior:'instant'});
    if(previousRoute)(statistics?$('#statistics-title'):profile?$('#profile-title'):workspace?$('#explorer-title'):$('#hero-title')).focus({preventScroll:true});
  }
  previousRoute=current;
}
function toast(message){
  clearTimeout(toastTimer);
  $('#toast').textContent=message;$('#toast').classList.add('visible');
  toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),2600);
}
function toggleSave(id){
  const item=opportunities.find(row=>row.id===id);if(!item)return;
  const scope=document.activeElement?.closest('#home-view, #explore-view')?.id;
  const wasSaved=state.saved.includes(id);
  state.saved=wasSaved?state.saved.filter(value=>value!==id):[...state.saved,id];
  let persisted=true;
  try{localStorage.setItem('funding-navigator-saved',JSON.stringify(state.saved));}catch{persisted=false;}
  renderHome();renderResults();renderSavedCount();
  if(scope){
    const target=document.querySelector(`#${scope} [data-save="${id}"]`)||document.querySelector(`#${scope} [data-save]`)||$('#reset-results');
    target?.focus({preventScroll:true});
  }
  $$('#detail-dialog [data-save]').forEach(button=>{
    if(button.dataset.save!==id)return;
    button.innerHTML=icon('bookmark')+(wasSaved?'Save':'Saved');
    button.setAttribute('aria-pressed',String(!wasSaved));
    button.setAttribute('aria-label',`${wasSaved?'Save':'Remove'} ${item.title}${wasSaved?' to':' from'} My saved`);
  });
  toast(wasSaved?'Removed from My saved.':persisted?'Saved on this device.':'Saved for this visit. Device storage is unavailable.');
}
function setProgramTab(value,focus=false){
  if(!['overview','eligibility','steps'].includes(value))return;
  $$('[data-program-tab]').forEach(button=>{
    const selected=button.dataset.programTab===value;
    button.setAttribute('aria-selected',String(selected));
    button.setAttribute('tabindex',selected?'0':'-1');
    if(selected&&focus)button.focus({preventScroll:true});
  });
  $$('[data-program-panel]').forEach(panel=>{panel.hidden=panel.dataset.programPanel!==value;});
}
function openDetail(id,navigate=false){
  const item=opportunities.find(row=>row.id===id);if(!item)return;
  const art=artFor(item);
  const plans=item.goals.map(goal=>goal==='training'?'Skills & training':'University or college');
  const sourceHost=new URL(item.url).hostname.replace(/^www\./,'');
  if(!navigate){
    const activeScope=document.activeElement?.closest('#home-view, #explore-view, #statistics-view, #assistant-dialog')?.id;
    detailOrigin={scope:activeScope||($('#workspace-view').hidden?'home-view':'explore-view'),id};
    detailRecordIds=(detailOrigin.scope==='home-view'?opportunities:detailOrigin.scope==='statistics-view'?getResults({...state,savedOnly:false,query:'',aiIds:null}):getResults(state)).map(row=>row.id);
    if(!detailRecordIds.includes(id))detailRecordIds=[id];
  }
  detailRecordId=id;
  const recordIndex=detailRecordIds.indexOf(id);
  const nextStep=programNextSteps(item)[0];
  const tab=(value,label,selected)=>`<button id="program-tab-${value}" type="button" role="tab" data-program-tab="${value}" aria-controls="program-panel-${value}" aria-selected="${selected}" tabindex="${selected?'0':'-1'}">${label}</button>`;
  $('#detail-content').innerHTML=`
    <header class="program-toolbar">
      <button class="program-back" data-close>${icon('arrow')}${detailOrigin.scope==='home-view'?'Back to preview':'Back to funding'}</button>
      <div class="program-toolbar-right"><nav class="program-record-nav" aria-label="Browse current opportunities"><button class="icon-button record-previous" data-program-move="-1" aria-label="Previous program" ${recordIndex===0?'disabled':''}>${icon('arrow')}</button><span>${recordIndex+1} <span aria-hidden="true">/</span> ${detailRecordIds.length}</span><button class="icon-button" data-program-move="1" aria-label="Next program" ${recordIndex===detailRecordIds.length-1?'disabled':''}>${icon('arrow')}</button></nav><span class="demo-tag">Example data</span><button class="icon-button" data-close aria-label="Close program details">${icon('close')}</button></div>
    </header>
    <div class="program-scroll">
      <div class="program-heading"><div class="program-provider">${badge(item)}<span>${escapeHTML(item.provider)}<small>${item.type==='Scholarship'?'Scholarship & award':'Education support program'}</small></span></div><h2 id="detail-title" tabindex="-1">${escapeHTML(item.title)}</h2></div>
      <dl class="program-highlights"><div class="funding-highlight"><dt>Funding</dt><dd class="program-amount ${item.amount===null?'varies':''}">${item.amount===null?'Funding varies':amountText(item)}<small>${item.amount===null?'Confirm available support':'Up to · example amount'}</small></dd></div><div><dt>${icon('compass')}When to apply</dt><dd>${escapeHTML(item.timing)}<small>Confirm the current cycle</small></dd></div><div><dt>${icon('pin')}Study location</dt><dd>${escapeHTML(item.location)}</dd></div></dl>
      <div class="program-layout">
      <section class="program-main">
        <div class="program-tabs" role="tablist" aria-label="Program information">${tab('overview','Overview',true)}${tab('eligibility','Who it’s for',false)}${tab('steps','Next steps',false)}</div>
        <section class="program-panel" id="program-panel-overview" data-program-panel="overview" role="tabpanel" aria-labelledby="program-tab-overview" tabindex="0">
          <h3>About this support</h3><p>${escapeHTML(item.summary)}</p>
          <div class="program-study-tags">${item.goals.map((goal,index)=>`<span>${icon(goal==='training'?'spark':'book')}${plans[index]}</span>`).join('')}</div>
        </section>
        <section class="program-panel" id="program-panel-eligibility" data-program-panel="eligibility" role="tabpanel" aria-labelledby="program-tab-eligibility" tabindex="0" hidden>
          <h3>A starting point for you</h3>
          <div class="program-criteria">${[
            ['user','Community',item.community.join(' · ')],
            ['pin','Study location',item.location],
            ['book','Study plans',plans.join(' · ')]
          ].map(([symbol,label,value])=>`<div class="program-criterion"><span>${icon(symbol)}</span><div><small>${label}</small><p>${escapeHTML(value)}</p></div></div>`).join('')}</div>
          <p class="program-criteria-note">Example criteria. Confirm all requirements with the provider.</p>
        </section>
        <section class="program-panel" id="program-panel-steps" data-program-panel="steps" role="tabpanel" aria-labelledby="program-tab-steps" tabindex="0" hidden>
          <h3>Your next steps</h3><ol class="program-next-steps">${programNextSteps(item).map(([title,description],index)=>`<li><span aria-hidden="true">0${index+1}</span><div><h4>${escapeHTML(title)}</h4><p>${escapeHTML(description)}</p></div></li>`).join('')}</ol>
        </section>
        <details class="detail-source"><summary>Source & current details ${icon('chevron')}</summary><p class="official-name"><strong>Official name</strong><br>${escapeHTML(item.fullTitle)}</p><p>${escapeHTML(item.note)}</p><p>Filters show a starting point. Confirm eligibility, available funding and dates with the provider.</p></details>
      </section>
      <aside class="program-aside" aria-label="Application and program attributes">
        <div class="program-summary"><div class="program-action-heading"><p class="support-label">Your next step</p><figure class="program-illustration ${art.tone}"><img src="assets/illustrations/${art.asset}.png" width="1254" height="1254" alt="" decoding="async"></figure></div><h3>${escapeHTML(nextStep[0])}</h3><p class="program-action-note">${escapeHTML(nextStep[1])}</p>
          <div class="program-desktop-actions">${programActions(item)}</div>
          <p class="program-source-link">${icon('shield')}Source <a href="${item.url}" target="_blank" rel="noopener noreferrer">${escapeHTML(sourceHost)}</a></p>
        </div>
        <dl class="program-attributes"><div><dt>Community</dt><dd>${escapeHTML(item.community.join(' · '))}</dd></div><div><dt>Study plans</dt><dd>${escapeHTML(plans.join(' · '))}</dd></div><div><dt>Program type</dt><dd>${item.type==='Scholarship'?'Scholarship & award':'Funding program'}</dd></div></dl>
      </aside>
    </div></div>
    <footer class="program-mobile-actions">${programActions(item)}</footer>`;
  const dialog=$('#detail-dialog');
  if(!dialog.open)dialog.showModal();
  if(navigate){$('.program-scroll')?.scrollTo({top:0});$('#detail-title').focus({preventScroll:true});}
}
function moveProgram(direction){
  if(![-1,1].includes(direction))return;
  const index=detailRecordIds.indexOf(detailRecordId)+direction;
  if(index<0||index>=detailRecordIds.length)return;
  openDetail(detailRecordIds[index],true);
}
function applyProfile(){
  if(!state.profile)return;
  ['community','location','goal'].forEach(key=>{state[key]=state.profile[key]||'all';});
  state.query='';state.type='all';state.amount='all';$('#funding-search').value='';
  location.hash='explore';route();
}
const infoContent={
  privacy:{title:'Only what helps you explore.',body:`<p><strong>No names, ID numbers or documents.</strong> Sharing community and study preferences is optional.</p><p>When AI is connected, messages and broad preferences are sent to the configured backend and LLM provider to answer your question. This demo does not save conversations or profiles to its database, and requests use store: false. Provider retention policies may still apply.</p><p>Conversation context stays in memory for this visit. My saved stores only opportunity IDs on this device. Apply directly with providers.</p><button class="text-link" id="privacy-clear-conversation">Clear this conversation ${icon('arrow')}</button><button class="text-link" data-clear-saved>Clear My saved on this device ${icon('arrow')}</button>`},
  sources:{title:'A clear starting point.',body:FundingModel.mode==='demo'
    ?'<p>This demo contains <strong>four example opportunities</strong> from the supplied pages. Each links to an official provider or program.</p><p>Amounts and award cycles are illustrative. Check the provider for current eligibility, available support and deadlines. Filters do not confirm eligibility.</p>'
    :`<p>This app contains <strong>${opportunities.length} published opportunities</strong> for First Nations, Inuit and Métis students. Each fact was quote-checked against a saved snapshot of the provider or directory page.</p><p>Records last verified ${opportunities.filter(x=>x.last_verified_at).length} of ${opportunities.length}; the rest of each record is shown as unknown, never guessed. Confirm current eligibility, amounts and dates with the provider.</p>`},
  about:{title:'A little support.<br>A world of possibility.',body:'<p>Funding Navigator helps First Nations, Inuit and Métis students in Canada explore scholarships and education support.</p><p>Explore larger filters and regional Statistics. Natural-language search and matching share one LLM backend when connected. This demo does not estimate approval chances.</p>'},
  help:{title:'A helping hand.',body:'<p>Bring an opportunity link to your <strong>school financial aid advisor, Indigenous student centre or community education office</strong>. Ask which documents and dates you need to confirm.</p><p>For PSSSP, contact your First Nation or designated organization. For Inuit support, contact your regional Inuit organization. For MNBC support, contact STEPS.</p>'}
};
function openInfo(key){
  const info=infoContent[key]||infoContent.about;
  $('#info-content').innerHTML=`<h2 id="info-title">${info.title}</h2>${info.body}`;
  $('#info-dialog').showModal();
}
function clearFilters(){
  FundingModel.filterKeys.forEach(key=>{state[key]='all';});
  state.includeUnknown=true;state.aiIds=null;
  insights?.clearManualFilters();
  $('#ai-search-summary').hidden=true;
  renderResults();
}
function resetResults(){
  if(state.savedOnly&&state.saved.length===0){location.hash='explore';route();return;}
  state.query='';$('#funding-search').value='';clearFilters();
}
document.addEventListener('click',event=>{
  const close=event.target.closest('[data-close]');if(close){close.closest('dialog').close();return;}
  const save=event.target.closest('[data-save]');if(save){toggleSave(save.dataset.save);return;}
  const detail=event.target.closest('[data-detail]');if(detail){openDetail(detail.dataset.detail);return;}
  const info=event.target.closest('[data-info]');if(info){openInfo(info.dataset.info);return;}
  const previewFilter=event.target.closest('[data-preview-filter]');
  if(previewFilter){location.hash='explore';route();requestAnimationFrame(()=>$(`#quick-${previewFilter.dataset.previewFilter}`).focus());return;}
  const programTab=event.target.closest('[data-program-tab]');if(programTab){setProgramTab(programTab.dataset.programTab);return;}
  const programMove=event.target.closest('[data-program-move]');if(programMove){moveProgram(Number(programMove.dataset.programMove));return;}
  const layout=event.target.closest('[data-layout]');if(layout){state.layout=layout.dataset.layout;renderResults();return;}
  const remove=event.target.closest('[data-remove-filter]');if(remove){state[remove.dataset.removeFilter]='all';state.aiIds=null;$('#ai-search-summary').hidden=true;renderResults();return;}
  if(event.target.closest('[data-clear-filters]')){clearFilters();return;}
  if(event.target.closest('[data-use-profile]')){applyProfile();return;}
  if(event.target.closest('[data-clear-profile]')){
    insights.clearConversation();state.community='all';state.location='all';state.goal='all';renderProfile();renderResults();toast('Conversation context cleared.');return;
  }
  if(event.target.closest('[data-clear-saved]')){
    state.saved=[];try{localStorage.removeItem('funding-navigator-saved');}catch{}
    renderSavedCount();renderHome();renderResults();$('#info-dialog').close();toast('My saved has been cleared.');
  }
});
document.addEventListener('keydown',event=>{
  const tab=event.target.closest('[data-program-tab]');if(!tab)return;
  const values=['overview','eligibility','steps'];
  let index=values.indexOf(tab.dataset.programTab);
  if(event.key==='ArrowRight')index=(index+1)%values.length;
  else if(event.key==='ArrowLeft')index=(index+values.length-1)%values.length;
  else if(event.key==='Home')index=0;
  else if(event.key==='End')index=values.length-1;
  else return;
  event.preventDefault();setProgramTab(values[index],true);
});
$('#funding-search').addEventListener('input',event=>{if($('#search-mode').value==='keyword'){state.query=event.target.value;state.aiIds=null;renderResults();}});
$('#search-form').addEventListener('submit',event=>{event.preventDefault();insights.search();});
$('#funding-sort').addEventListener('change',event=>{state.sort=event.target.value;renderResults();});
document.addEventListener('change',event=>{const el=event.target.closest('[data-filter]');if(el){state[el.dataset.filter]=el.value;state.aiIds=null;$('#ai-search-summary').hidden=true;renderResults();}});
$('#reset-results').addEventListener('click',resetResults);
$$('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{
  if(event.target!==dialog)return;
  const rect=dialog.getBoundingClientRect();
  if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();
}));
$('#detail-dialog').addEventListener('close',()=>{
  if(!detailOrigin)return;
  const {scope,id}=detailOrigin;
  if($('#'+scope)?.hidden)return;
  const target=document.querySelector(`#${scope} [data-detail="${id}"]`)||$('#empty-state:not([hidden]) #reset-results')||$('#explorer-title');
  target?.focus({preventScroll:true});detailOrigin=null;detailRecordIds=[];detailRecordId=null;
});
window.addEventListener('hashchange',route);
insights=FundingInsights.init({state,$,$$,icon,escapeHTML,toast,renderResults,renderProfile,clearFilters,route});
renderHome();renderSavedCount();renderProfile();route();
}).catch(()=>{
  const toast=document.querySelector('#toast');
  toast.textContent='The example dataset could not be loaded. Please reload this page.';toast.classList.add('visible');
});
