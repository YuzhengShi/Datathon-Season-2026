(function(root){
  'use strict';
  function init(ctx){
    const {state,$,$$,icon,escapeHTML:e,toast,renderResults,renderProfile,clearFilters,route}=ctx;
    const {regions,filterKeys,opportunities,toFilters,fromFilters,amountText}=FundingModel;
    const labels={goal:{postsecondary:'University or college',training:'Skills & training'},amount:{listed:'Amount listed',high:'Above $5,000',under5000:'Up to $5,000',unknown:'Amount not listed'},level:{high_school:'High school',college:'College',undergraduate:'Undergraduate',graduate:'Graduate',vocational:'Vocational training'},field:{business:'Business & finance',stem:'STEM',health:'Health',arts:'Arts & humanities',trades:'Skilled trades'},studyMode:{full_time:'Full-time',part_time:'Part-time'},expense:{tuition:'Tuition',living:'Living costs',travel:'Travel',books:'Books & materials'},renewable:{yes:'Renewable',no:'Non-renewable',unknown:'Renewal unknown'},deadline:{date:'Date listed',annual_rule:'Annual deadline',rolling:'Rolling intake',local_administrator:'Set by administrator',unspecified:'Date unspecified'},scope:{national:'National coverage',regional:'Region-specific'},type:{Scholarship:'Scholarships & awards',Program:'Funding programs'}};
    const descriptors=[['goal','Study plans'],['level','Education level'],['field','Field of study'],['studyMode','Study mode'],['expense','Funding covers'],['renewable','Renewal'],['deadline','Deadline type'],['provider','Provider'],['scope','Coverage']];
    const filterLabel=(key,value)=>Array.isArray(value)?value.map(x=>labels[key]?.[x]||x).join(' · '):labels[key]?.[value]||value;
    const regionOptions='<option value="all">All of Canada</option>'+Object.values(regions).map(name=>`<option>${e(name)}</option>`).join('');
    $('#quick-location').innerHTML=regionOptions;$('#stats-location').innerHTML=regionOptions;
    $('#advanced-filter-grid').innerHTML=descriptors.map(([key,label])=>{
      const values=key==='provider'?Object.fromEntries([...new Set(opportunities.map(x=>x.provider))].map(x=>[x,x])):labels[key];
      return `<div class="select-field"><label for="filter-${key}">${label}</label><select id="filter-${key}" data-filter="${key}"><option value="all">Any ${label.toLowerCase()}</option>${Object.entries(values).map(([value,text])=>`<option value="${e(value)}">${e(text)}</option>`).join('')}</select>${icon('chevron')}</div>`;
    }).join('');
    const manualKeys=new Set();
    let connection={backend:false,ai:false,mode:'demo'},mapMode='regional',geometry=null,latestStats=null,statsRevision=0;
    let conversationMode='match',history=[],profile={},messages=[],lastAnswer=null,busy=false,conversationRevision=0,currentController=null;
    const geometryReady=fetch('data/canada-map.json').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(value=>{geometry=value;if(!$('#statistics-view').hidden&&latestStats)paintStatistics(latestStats);}).catch(()=>{if(!$('#statistics-view').hidden)$('#canada-map').innerHTML='<p class="chart-note">Map unavailable. Use the region table below.</p>';});
    function activeDescription(){const values=filterKeys.filter(k=>state[k]!=='all').map(k=>filterLabel(k,state[k]));if(!state.includeUnknown)values.push('Only specified source details');return values.length?values.join(' · '):'All records · select a chart or region to narrow the view';}
    function updateConnection(){
      const text=connection.ai?'AI connected · shared funding tools':connection.backend?'Backend connected · AI not configured':'HTML preview · AI not connected';
      $('#ai-connection-status').textContent=text;
      $('#assistant-status').textContent=connection.ai?'LLM connected · source-linked data tools':connection.backend?'Backend connected · AI not configured':'Preview · connect the LLM backend to chat';
      $('#stats-backend-status').textContent=connection.backend?'Backend analytics':'HTML preview';
    }
    async function post(endpoint,body,{signal}={}){
      const response=await fetch('/api/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
      let data;try{data=await response.json();}catch{throw new Error('The AI backend is not connected to this page. Filters and Statistics still work.');}
      if(!response.ok)throw new Error(data.error?.message||'The request could not be completed.');
      if(!['demo','live'].includes(data.data_mode)||data.data_mode!==FundingModel.mode)throw new Error('The backend dataset does not match the loaded dataset. Check the serve --mode.');
      return data;
    }
    fetch('/api/health').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{
      connection={backend:data.migration_ready&&data.data_mode===FundingModel.mode,ai:data.migration_ready&&data.llm_ready&&data.data_mode===FundingModel.mode,mode:data.data_mode};updateConnection();
      if(connection.backend&&!$('#statistics-view').hidden)renderStatistics();
    }).catch(updateConnection);
    updateConnection();
    function chooseFilter(key,value){
      state[key]=state[key]===value?'all':value;manualKeys.add(key);state.aiIds=null;$('#ai-search-summary').hidden=true;
      renderResults();renderStatistics();
    }
    function bars(entries,key,colors){
      const maximum=Math.max(1,...entries.map(x=>x[1]));
      return '<div class="chart-bars">'+entries.map(([label,count,value],i)=>`<button class="chart-bar" data-stats-selection="${key}" data-value="${e(value)}" aria-label="Filter by ${e(label)}: ${count} records"><span class="chart-bar-label"><span>${e(label)}</span><b>${count}</b></span><span class="chart-bar-track"><i style="--bar-width:${count/maximum*100}%;--chart-color:${colors?.[i]||'#8fa875'}"></i></span></button>`).join('')+'</div>';
    }
    function renderMap(data){
      if(!geometry){$('#canada-map').innerHTML='<p class="chart-note">Loading map… The region table is available below.</p>';}
      else{
        const byCode=Object.fromEntries(data.regions.map(x=>[x.code,x]));
        const max=Math.max(1,...data.regions.map(x=>x[mapMode==='regional'?'regional_count':'reach_count']));
        const selected=Array.isArray(state.location)?state.location:[state.location];
        const fill=count=>count===0?'#e7eddf':count/max>.7?'#759258':count/max>.35?'#a7bc8b':'#c8d6b2';
        $('#canada-map').innerHTML=`<svg viewBox="${geometry.viewBox}" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="Canadian provinces and territories. Press a region to filter the dataset.">${geometry.regions.map(region=>{
          const row=byCode[region.code],name=regions[region.code],count=row[mapMode==='regional'?'regional_count':'reach_count'];
          return `<path d="${region.path}" fill="${fill(count)}" class="${selected.includes(name)?'is-selected':''}" tabindex="0" role="button" aria-pressed="${selected.includes(name)}" data-region="${region.code}" aria-label="${e(name)}: ${row.regional_count} regional, ${row.national_count} national records"><title>${e(name)} · ${row.regional_count} regional + ${row.national_count} national</title></path>`;
        }).join('')}${geometry.regions.filter(x=>!['PE','NB','NS'].includes(x.code)).map(x=>`<text class="map-label" x="${x.label[0]}" y="${x.label[1]}" text-anchor="middle">${x.code}</text>`).join('')}</svg>`;
      }
      const chosen=data.regions.find(x=>x.name===state.location)||data.regions.slice().sort((a,b)=>b.regional_count-a.regional_count)[0];
      const count=chosen[mapMode==='regional'?'regional_count':'reach_count'];
      $('#map-region-summary').innerHTML=`<p class="region-insight-label">${state.location==='all'?'Leading regional coverage':'Selected region'}</p><h3 class="region-insight-name">${e(chosen.name)}</h3><div class="region-insight-value">${count}</div><p class="region-insight-small">${mapMode==='regional'?'region-specific records': 'national + regional records'}<br>${chosen.national_count} national records also shown in Explore</p><div class="region-picker">${data.regions.slice().sort((a,b)=>b.regional_count-a.regional_count).slice(0,5).map(row=>`<button data-region="${row.code}" class="${state.location===row.name?'is-selected':''}"><span>${e(row.name)}</span><b>${row[mapMode==='regional'?'regional_count':'reach_count']}</b></button>`).join('')}</div>`;
      $('#region-table').innerHTML=`<table><thead><tr><th scope="col">Region</th><th scope="col">Regional</th><th scope="col">National</th><th scope="col">Unique reach</th></tr></thead><tbody>${data.regions.map(row=>`<tr><td><button data-region="${row.code}">${e(row.name)}</button></td><td>${row.regional_count}</td><td>${row.national_count}</td><td>${row.reach_count}</td></tr>`).join('')}</tbody></table><p>National reach is repeated across regions. Do not sum the reach column.</p>`;
    }
    function paintStatistics(data){
      latestStats=data;
      const focusRegion=document.activeElement?.dataset?.region;
      const live=FundingModel.mode==='live';
      document.querySelector('.dataset-banner strong').textContent=live?'Live dataset':'Example dataset';
      $('#stats-dataset-note').textContent=live
        ?`${opportunities.length} published records · quote-checked · not a national market census`
        :`${opportunities.length} illustrative records · not national market data`;
      $('#stats-context').textContent=activeDescription();
      $$('[data-stats-filter]').forEach(el=>{
        const value=state[el.dataset.statsFilter];el.querySelector('[data-multiple]')?.remove();
        if(Array.isArray(value)){const option=document.createElement('option');option.value='multiple';option.textContent=value.join(' · ');option.disabled=true;option.dataset.multiple='true';el.append(option);el.value='multiple';}else el.value=value;
      });
      const figures=[['Opportunities',data.total,'Unique records in this selection','compass'],['National coverage',data.national_count,'Counted once, not per province','pin'],['Regional support',data.regional_count,'Restricted to a specific region','chart'],['Amounts listed',`${data.amounts.listed} / ${data.total}`,'Unknown ≠ $0 · figures are examples','book']];
      $('#statistics-kpis').innerHTML=figures.map(([label,value,note,symbol])=>`<div class="kpi"><p>${label}</p><span class="kpi-value">${value}</span><small>${note}</small><span class="kpi-decoration">${icon(symbol)}</span></div>`).join('');
      renderMap(data);
      const total=data.total||1,r=64,c=2*Math.PI*r,scholarships=data.by_type.Scholarship||0,programs=data.by_type.Program||0;
      $('#type-chart').innerHTML=`<div class="donut-wrap"><svg viewBox="0 0 165 165" role="img" aria-label="${scholarships} scholarships and ${programs} programs"><circle cx="82.5" cy="82.5" r="64" stroke="#eff3e8"/><circle cx="82.5" cy="82.5" r="64" stroke="#819e62" stroke-dasharray="${programs/total*c} ${c}"/><circle cx="82.5" cy="82.5" r="64" stroke="#d8af85" stroke-dasharray="${scholarships/total*c} ${c}" stroke-dashoffset="-${programs/total*c}"/></svg><div class="donut-center"><strong>${data.total}</strong><small>opportunities</small></div></div><div class="chart-legend"><button data-stats-selection="type" data-value="Program" style="--chart-color:#819e62"><i></i>Funding programs <b>${programs}</b></button><button data-stats-selection="type" data-value="Scholarship" style="--chart-color:#d8af85"><i></i>Scholarships & awards <b>${scholarships}</b></button></div>`;
      $('#national-summary').innerHTML=`<button data-stats-selection="scope" data-value="national"><span>Across Canada</span><strong>${data.national_count}</strong></button><button data-stats-selection="scope" data-value="regional"><span>Region-specific</span><strong>${data.regional_count}</strong></button>`;
      $('#community-chart').innerHTML=bars(Object.entries(data.by_community).map(([name,count])=>[name,count,name]),'community',['#819e62','#a8bd90','#cfb08a']);
      $('#amount-chart').innerHTML=bars([['Up to $5,000',data.amount_bands.up_to_5000,'under5000'],['Above $5,000',data.amount_bands.above_5000,'high'],['Not listed',data.amount_bands.unknown,'unknown']],'amount',['#a4b986','#83a365','#d4dcca']);
      const dl=data.by_deadline_kind;
      $('#deadline-chart').innerHTML=bars([['Set by administrator',dl.local_administrator||0,'local_administrator'],['Rolling intake',dl.rolling||0,'rolling'],['Date unspecified',dl.unspecified||0,'unspecified']],'deadline',['#9eb489','#c8b697','#d7dfce']);
      $('#amount-table-body').innerHTML=data.amount_rows.map(row=>`<tr><td><button data-detail="${e(row.id)}">${e(row.title)}</button><small>${e(row.provider)}</small></td><td>${e(row.location)}</td><td>${row.amount===null?'Not listed':amountText({amount:Number(row.amount)})}<small>Example · confirm provider</small></td><td><span class="amount-semantic">${({maximum:'Unverified up-to figure',fixed:'Fixed · stated unit',range:'Range · stated unit',variable:'Varies by program',pooled_total:'Pool, not per student',unspecified:'Unspecified'})[row.amount_details.kind]||'Unspecified'}</span></td></tr>`).join('');
      $('#stats-empty-note').hidden=data.total!==0;
      $('#statistics-methods-content').innerHTML=`<p>${data.quality.verified_records} of ${data.total} selected records have a verified current cycle. ${live?'Records come from the canonical, quote-checked dataset; directory-only entries are labelled in their source notes.':'These are carried-over source examples, not a census of Canadian scholarships.'}</p><p>Province counts describe program coverage, not headquarters. National records count once in the total; regional reach and community tags overlap. Listed caps, pooled totals and unknown figures are never summed as allocated funding.</p><p>Education level, field, study mode, covered costs and renewal are unknown unless a source states them. “Keep unspecified details” controls whether such records remain in a filtered view. <a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noopener noreferrer">Map: Natural Earth, public-domain geography.</a></p>`;
      if(focusRegion)$(`#canada-map [data-region="${focusRegion}"]`)?.focus({preventScroll:true});
    }
    async function renderStatistics(){
      const revision=++statsRevision;
      paintStatistics(FundingModel.statistics(state));
      if(!connection.backend)return;
      try{
        const data=await post('statistics',{filters:toFilters({...state,query:'',savedOnly:false})});
        if(revision===statsRevision)paintStatistics(data);
      }catch{if(revision===statsRevision)$('#stats-backend-status').textContent='HTML preview · backend unavailable';}
    }
    function exportStatistics(){
      if(!latestStats)return;
      const live=FundingModel.mode==='live';
      const safe=value=>{let text=String(value??'');if(/^[\t\r\n ]*[=+@-]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';};
      const rows=[['data_mode','opportunity_id','title','provider','coverage','listed_figure','amount_kind','currency','unit','note'],...latestStats.amount_rows.map(x=>[FundingModel.mode,x.id,x.title,x.provider,x.location,x.amount,x.amount_details.kind,x.amount_details.currency,x.amount_details.unit,live?'Quote-checked; unknown is not zero':'Illustrative, unverified; unknown is not zero'])];
      const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'});
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`funding-statistics-${FundingModel.mode}.csv`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(live?'Selected published records exported.':'Selected example records exported.');
    }
    function canonicalCards(answer){
      const live=FundingModel.mode==='live';
      return (answer?.results||[]).map(({record,match})=>`<article class="assistant-record"><button data-detail="${e(record.id)}">${e(record.title)}</button><strong>${amountText(record)}</strong><small>${record.amount===null?'Amount to confirm':live?'Listed figure · confirm with the provider':'Illustrative figure · not guaranteed'}<br>${e(record.location)}<br>${e(match?.match_status==='potential_fit'?'Recorded conditions met; approval not guaranteed':match?.match_status==='needs_information'?'More information needed':'Confirm current requirements with the provider')}</small><a href="${e(record.url)}" target="_blank" rel="noopener noreferrer">Provider source ↗</a></article>`).join('');
    }
    function renderConversation(){
      const analysis=conversationMode==='analysis';
      $('#assistant-title').textContent=analysis?'Ask about the data':conversationMode==='search'?'Smart search':'Find a match';
      $('#conversation-thread').innerHTML=(messages.length?'':`<div class="conversation-welcome"><span>${icon(analysis?'chart':'spark')}</span><h3>${analysis?'What would you like to understand?':'Your next chapter,<br>in your own words.'}</h3><p>${analysis?'Ask about regions, funding types or listed figures. Answers use the same Statistics backend.':'Tell me about your studies and the support you need. I’ll use the funding data and ask a useful follow-up when needed.'}</p></div>`)+messages.map(m=>`<div class="conversation-message ${m.role==='user'?'is-user':m.error?'is-error':''}">${e(m.content)}${m.answer?`<small>${e(m.answer.intent||'')} · ${m.answer.data_mode==='demo'?'Example data':''}</small><div class="conversation-result-cards">${canonicalCards(m.answer)}</div>`:''}</div>`).join('')+(busy?'<div class="conversation-message">Working with the funding tools…</div>':'');
      const suggestions=analysis?['Compare regional and national coverage','Which programs list an amount?','Show funding for Métis students in BC']:['I’m a Métis student in BC looking for training support','I’m starting university. Where should I begin?','I’m an Inuit student exploring education support'];
      $('#conversation-suggestions').hidden=messages.length>0;
      $('#conversation-suggestions').innerHTML=suggestions.map(text=>`<button data-conversation-suggestion="${e(text)}">${e(text)}</button>`).join('');
      $('#assistant-evidence-content').innerHTML=lastAnswer?canonicalCards(lastAnswer)+(lastAnswer.statistics?`<p>${lastAnswer.statistics.total} records · ${lastAnswer.statistics.national_count} national · ${lastAnswer.statistics.regional_count} regional.<br>${FundingModel.mode==='live'?'Published dataset, not a market total.':'Demo data, not a market total.'}</p>`:'')+`<span class="assistant-record-tool">Tools used: ${lastAnswer.tools_used.map(x=>e(x.name.replaceAll('_',' '))).join(' · ')}</span>`:'<p>Source-linked records and what still needs confirmation will appear here. AI needs the connected backend; this page does not simulate an LLM.</p>';
      $('#conversation-submit').disabled=busy;$('#conversation-input').disabled=busy;
      $('#conversation-thread').scrollTop=$('#conversation-thread').scrollHeight;
      updateConnection();
    }
    function openAssistant(mode='match'){
      if(mode!==conversationMode&&messages.length)clearConversation();
      conversationMode=mode;renderConversation();const dialog=$('#assistant-dialog');if(!dialog.open)dialog.showModal();$('#conversation-input').focus();
    }
    function clearConversation(){
      conversationRevision++;currentController?.abort();currentController=null;history=[];profile={};messages=[];lastAnswer=null;busy=false;state.profile=null;state.aiIds=null;$('#ai-search-summary').hidden=true;$('#conversation-input').value='';renderConversation();renderProfile();
    }
    function applyAnswer(answer){
      Object.assign(state,fromFilters(answer.filters));state.aiIds=answer.question||answer.mode==='analysis'?null:answer.results.map(x=>x.record.id);
      profile=answer.profile;
      state.profile=profile.communities?.length||profile.institution_province||profile.goal?{community:profile.communities?.length>1?profile.communities:profile.communities?.[0]||'all',location:profile.institution_province||'all',goal:profile.goal||'all'}:null;
      lastAnswer=answer;renderResults();renderProfile();
      if(!$('#statistics-view').hidden)renderStatistics();
    }
    function manualFilters(){
      const view={query:'',includeUnknown:true};filterKeys.forEach(key=>view[key]=manualKeys.has(key)?state[key]:'all');
      if(manualKeys.has('includeUnknown'))view.includeUnknown=state.includeUnknown;
      return toFilters(view);
    }
    async function requestAssistant(mode,message){
      if(!connection.ai)throw new Error('The LLM is not connected yet. This preview includes working filters and Statistics; real AI needs the configured backend.');
      currentController?.abort();const controller=new AbortController();currentController=controller;const timer=setTimeout(()=>controller.abort(),90000);
      try{return await post('conversation',{mode,message,history:mode==='search'?[]:history.slice(-10),filters:mode==='analysis'?toFilters({...state,query:''}):manualFilters(),profile},{signal:controller.signal});}
      catch(error){if(error.name==='AbortError')throw new Error('The request was cancelled or took too long. Please try again.');throw error;}
      finally{clearTimeout(timer);if(currentController===controller)currentController=null;}
    }
    async function sendConversation(){
      const input=$('#conversation-input'),message=input.value.trim();if(!message||busy)return;
      const revision=conversationRevision;messages.push({role:'user',content:message});input.value='';busy=true;renderConversation();
      try{
        const answer=await requestAssistant(conversationMode,message);if(revision!==conversationRevision)return;
        applyAnswer(answer);const content=answer.question||answer.message;
        history.push({role:'user',content:message},{role:'assistant',content});messages.push({role:'assistant',content,answer});
      }catch(error){if(revision===conversationRevision)messages.push({role:'assistant',content:error.message,error:true});}
      finally{if(revision===conversationRevision){busy=false;renderConversation();input.focus();}}
    }
    async function search(){
      const message=$('#funding-search').value.trim();
      if($('#search-mode').value==='keyword'){state.query=message;state.aiIds=null;$('#ai-search-summary').hidden=true;renderResults();return;}
      if(!message){state.query='';state.aiIds=null;renderResults();return;}
      const button=$('#search-submit');if(button.disabled)return;button.disabled=true;button.textContent='Thinking…';
      try{
        const answer=await requestAssistant('search',message);applyAnswer(answer);
        $('#ai-search-summary').hidden=false;$('#ai-search-summary').innerHTML=`${icon('spark')}<span>${e(answer.intent)} · ${answer.results.length} source-linked records. Filters are editable.</span><button id="clear-ai-search">Clear AI results</button>`;
        if(answer.question){openAssistant('search');messages.push({role:'user',content:message},{role:'assistant',content:answer.question,answer});history.push({role:'user',content:message},{role:'assistant',content:answer.question});renderConversation();}
      }catch(error){$('#ai-search-summary').hidden=false;$('#ai-search-summary').textContent=error.message;}
      finally{button.disabled=false;button.textContent='Search';}
    }
    document.addEventListener('click',event=>{
      const assistant=event.target.closest('[data-assistant]');if(assistant){openAssistant(assistant.dataset.assistant);return;}
      const region=event.target.closest('[data-region]');if(region){chooseFilter('location',regions[region.dataset.region]);$(`#canada-map [data-region="${region.dataset.region}"]`)?.focus({preventScroll:true});return;}
      const selection=event.target.closest('[data-stats-selection]');if(selection){chooseFilter(selection.dataset.statsSelection,selection.dataset.value);return;}
      const mode=event.target.closest('[data-map-mode]');if(mode){mapMode=mode.dataset.mapMode;$$('[data-map-mode]').forEach(x=>x.setAttribute('aria-pressed',String(x===mode)));if(latestStats)renderMap(latestStats);return;}
      const suggestion=event.target.closest('[data-conversation-suggestion]');if(suggestion){$('#conversation-input').value=suggestion.dataset.conversationSuggestion;$('#conversation-input').focus();return;}
      const remove=event.target.closest('[data-remove-filter]');if(remove)manualKeys.delete(remove.dataset.removeFilter);
      if(event.target.closest('#privacy-clear-conversation')){clearConversation();renderResults();toast('Conversation cleared.');}
      if(event.target.closest('#clear-ai-search')){state.aiIds=null;$('#ai-search-summary').hidden=true;renderResults();}
    });
    document.addEventListener('keydown',event=>{const region=event.target.closest('[data-region]');if(region&&region.tagName.toLowerCase()==='path'&&['Enter',' '].includes(event.key)){event.preventDefault();chooseFilter('location',regions[region.dataset.region]);}});
    document.addEventListener('change',event=>{
      const filter=event.target.closest('[data-filter]');if(filter)manualKeys.add(filter.dataset.filter);
      const statsFilter=event.target.closest('[data-stats-filter]');if(statsFilter){state[statsFilter.dataset.statsFilter]=statsFilter.value;manualKeys.add(statsFilter.dataset.statsFilter);state.aiIds=null;renderResults();renderStatistics();}
    });
    $('#include-unknown').addEventListener('change',event=>{state.includeUnknown=event.target.checked;manualKeys.add('includeUnknown');state.aiIds=null;renderResults();});
    $('#search-mode').addEventListener('change',()=>{state.query=$('#search-mode').value==='keyword'?$('#funding-search').value:'';state.aiIds=null;$('#ai-search-summary').hidden=true;renderResults();});
    $('#stats-more-filters').addEventListener('click',()=>{location.hash='explore';route();$('#advanced-filters').open=true;$('#filter-goal').focus();});
    $('#stats-clear-filters').addEventListener('click',()=>{clearFilters();manualKeys.clear();renderStatistics();});
    $('#export-statistics').addEventListener('click',exportStatistics);
    $('#conversation-form').addEventListener('submit',event=>{event.preventDefault();sendConversation();});
    $('#conversation-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendConversation();}});
    $('#conversation-reset').addEventListener('click',()=>{clearConversation();$('#conversation-input').focus();});
    renderConversation();
    return {renderStatistics,filterLabel,search,clearConversation,clearManualFilters:()=>manualKeys.clear(),geometryReady};
  }
  root.FundingInsights={init};
})(globalThis);
