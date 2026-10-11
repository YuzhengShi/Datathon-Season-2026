/* DOM/interaction QA only: jsdom does not verify visual layout or native browser dialogs.
 * npm install --no-save --package-lock=false jsdom@30.1.2
 * node scripts/qa-ui.cjs
 */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'dist/index.html'),'utf8');
const dataset=JSON.parse(fs.readFileSync(path.join(root,'dist/data/demo-opportunities.json'),'utf8'));/* the four illustrative records the demo checks below are written for */
const liveDataset=JSON.parse(fs.readFileSync(path.join(root,'dist/data/opportunities.json'),'utf8'));/* what static hosting serves */
const geometry=JSON.parse(fs.readFileSync(path.join(root,'dist/data/canada-map.json'),'utf8'));
const clone=x=>JSON.parse(JSON.stringify(x)),tick=()=>new Promise(resolve=>setTimeout(resolve,5));
let passed=0;
async function check(name,fn){await fn();passed++;}
async function setup({ai=false,multiple=false,live=false,healthMode}={}){
  const data=live?liveDataset:dataset;
  const errors=[],requests=[],downloads=[];
  const vc=new VirtualConsole();vc.on('jsdomError',error=>errors.push(error.message));
  const dom=new JSDOM(html,{url:'https://funding.test/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window,d=w.document;
  w.scrollTo=()=>{};w.HTMLElement.prototype.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};w.matchMedia=()=>({matches:false});
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.HTMLAnchorElement.prototype.click=function(){downloads.push({name:this.download,url:this.href});};
  w.Blob=class{constructor(parts){this.text=parts.join('');}};
  w.URL.createObjectURL=blob=>{downloads.push({text:blob.text});return 'blob:qa';};w.URL.revokeObjectURL=()=>{};
  w.localStorage.setItem('funding-navigator-saved',JSON.stringify([data.records[0].id,data.records[0].id,'not-real']));
  w.fetch=async(url,options={})=>{
    if(url==='data/opportunities.json')return {ok:true,json:async()=>clone(data)};
    if(url==='data/canada-map.json')return {ok:true,json:async()=>clone(geometry)};
    if(url==='/api/health')return {ok:true,json:async()=>({data_mode:healthMode||(live?'live':'demo'),migration_ready:true,llm_ready:ai})};
    const body=JSON.parse(options.body);requests.push({url,body});
    if(url==='/api/statistics')return {ok:true,json:async()=>w.FundingModel.statistics(w.FundingModel.fromFilters(body.filters))};
    if(url==='/api/conversation'){
      const filters=w.FundingModel.toFilters({community:'Métis',location:multiple?['British Columbia','Ontario']:'British Columbia',goal:'training',includeUnknown:true});
      return {ok:true,json:async()=>({data_mode:'demo',mode:body.mode,intent:'Métis training support in BC',message:'2 records to explore. Confirm provider requirements.',question:null,filters,profile:{communities:['Métis'],institution_province:'British Columbia',goal:'training'},results:dataset.records.filter(x=>['nutrien','mnbc'].includes(x.id)).map(record=>({record:clone(record),match:{match_status:'needs_provider_confirmation'},reasons:['Provider confirmation needed']})),statistics:null,tools_used:[{name:body.mode==='search'?'search_opportunities':'find_matches',returned_records:2}]})};
    }
    throw new Error('Unexpected QA request: '+url);
  };
  for(const filename of ['fonts.css','styles.css','workspace.css','program.css','insights.css']){const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(root,'dist',filename),'utf8');d.head.append(style);}
  w.eval(fs.readFileSync(path.join(root,'dist/model.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(root,'dist/regions.js'),'utf8'));w.eval(fs.readFileSync(path.join(root,'dist/regionview.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(root,'dist/insights.js'),'utf8'));
  const source=fs.readFileSync(path.join(root,'dist/app.js'),'utf8').replace('renderHome();renderSavedCount();renderProfile();route();','globalThis.__qa={state,route,renderResults,clearFilters,resetResults,openDetail,moveProgram,toggleSave,insights};renderHome();renderSavedCount();renderProfile();route();');
  w.eval(source);await w.FundingModel.ready;await tick();
  assert.ok(w.__qa,'Application initialization failed: '+d.querySelector('#toast').textContent);
  return {dom,w,d,q:s=>d.querySelector(s),qa:w.__qa,requests,downloads,errors,click:s=>d.querySelector(s).click(),change:(s,value)=>{const el=d.querySelector(s);el.value=value;el.dispatchEvent(new w.Event('change',{bubbles:true}));},count:()=>Number(d.querySelector('#results-count').textContent.match(/\d+/)?.[0]||0)};
}
async function main(){
  const a=await setup();
  await check('Home remains intact and saved IDs validated',()=>{assert.equal(a.q('#home-view').hidden,false);assert.equal(a.q('#home-cards').children.length,3);assert.deepEqual(clone(a.qa.state.saved),['nutrien']);});
  await check('No questionnaire remains',()=>{assert.equal(a.q('#quiz-dialog'),null);assert.equal(a.q('[data-quiz]'),null);assert.ok(!a.q('#profile-content').textContent.includes('Three optional questions'));});
  await check('New Statistics route and sidebar',async()=>{a.w.location.hash='#statistics';a.qa.route();await tick();assert.equal(a.q('#statistics-view').hidden,false);assert.equal(a.q('#explore-view').hidden,true);assert.equal(a.q('[data-nav="statistics"]').getAttribute('aria-current'),'page');assert.equal(a.q('#statistics-title').textContent,'Statistics');});
  await check('All 13 provinces/territories present and labelled',()=>{assert.equal(a.d.querySelectorAll('#canada-map path').length,13);assert.equal(a.q('#region-table tbody').children.length,13);assert.ok(a.q('#canada-map [data-region="BC"]').getAttribute('aria-label').includes('1 regional, 3 nationwide'));});
  await check('KPI counts use unique examples and amount coverage',()=>{assert.deepEqual([...a.d.querySelectorAll('.kpi-value')].map(x=>x.textContent),['4','1 / 13','3','1','2 / 4']);assert.ok(a.q('#amount-table-body').textContent.includes('Not listed'));});
  await check('Map click cross-filters every chart and record table',async()=>{a.q('#canada-map [data-region="ON"]').dispatchEvent(new a.w.MouseEvent('click',{bubbles:true}));await tick();assert.equal(a.qa.state.location,'Ontario');assert.equal(a.q('.kpi-value').textContent,'3');assert.equal(a.q('#amount-table-body').children.length,3);});
  await check('Explore retains dashboard selection',()=>{a.w.location.hash='#explore';a.qa.route();assert.equal(a.count(),3);assert.equal(a.q('#quick-location').value,'Ontario');});
  await check('Map keyboard activation',async()=>{a.w.location.hash='#statistics';a.qa.route();a.q('#canada-map [data-region="BC"]').dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await tick();assert.equal(a.qa.state.location,'British Columbia');});
  await check('Chart selection combines with community and amount filters',async()=>{a.click('#community-chart [data-value="Métis"]');await tick();assert.equal(a.q('.kpi-value').textContent,'2');a.click('#amount-chart [data-value="unknown"]');await tick();assert.equal(a.q('.kpi-value').textContent,'1');assert.ok(a.q('#amount-table-body').textContent.includes('MNBC'));});
  await check('Reset returns all charts to the full denominator',async()=>{a.click('#stats-clear-filters');await tick();assert.equal(a.q('.kpi-value').textContent,'4');assert.equal(a.q('#quick-community').value,'all');});
  await check('Map reach toggle does not change unique dataset count',()=>{a.click('[data-map-mode="reach"]');assert.equal(a.q('.kpi-value').textContent,'4');assert.equal(a.q('[data-map-mode="reach"]').getAttribute('aria-pressed'),'true');});
  await check('Expanded filters generated and all regions available',()=>{assert.equal(a.d.querySelectorAll('#advanced-filter-grid select').length,9);assert.equal(a.q('#quick-location').options.length,14);assert.equal(a.q('#quick-community').labels[0].className,'');});
  await check('Unknown facets are retained by default',()=>{a.qa.clearFilters();a.change('#filter-level','undergraduate');assert.equal(a.count(),4);assert.equal(a.qa.state.level,'undergraduate');});
  await check('Strict unknown switch yields a truthful empty state',()=>{const el=a.q('#include-unknown');el.checked=false;el.dispatchEvent(new a.w.Event('change',{bubbles:true}));assert.equal(a.count(),0);assert.equal(a.q('#empty-state').hidden,false);});
  await check('Zero statistics stay finite',async()=>{a.w.location.hash='#statistics';a.qa.route();await tick();assert.equal(a.q('.kpi-value').textContent,'0');assert.ok(!a.q('#type-chart').innerHTML.includes('NaN'));assert.equal(a.q('#stats-empty-note').hidden,false);a.click('#stats-clear-filters');await tick();});
  await check('Explicit keyword mode is accent insensitive',()=>{a.w.location.hash='#explore';a.qa.route();a.q('#funding-search').value='metis';a.change('#search-mode','keyword');assert.equal(a.count(),2);a.qa.resetResults();});
  await check('Missing AI is explicit, not fabricated matching',async()=>{a.change('#search-mode','ai');a.q('#funding-search').value='I need support for training';a.q('#search-form').dispatchEvent(new a.w.Event('submit',{bubbles:true,cancelable:true}));await tick();assert.ok(a.q('#ai-search-summary').textContent.includes('not connected'));assert.equal(a.requests.filter(x=>x.url==='/api/conversation').length,0);});
  await check('Matching opens natural conversation, not a form',()=>{a.click('#explore-view [data-assistant="match"]');assert.equal(a.q('#assistant-dialog').open,true);assert.ok(a.q('#conversation-thread').textContent.includes('own words'));assert.equal(a.d.querySelectorAll('#assistant-dialog [data-filter]').length,0);});
  await check('Assistant error releases controls',async()=>{a.q('#conversation-input').value='I am starting university';a.q('#conversation-form').dispatchEvent(new a.w.Event('submit',{bubbles:true,cancelable:true}));await tick();assert.ok(a.q('#conversation-thread').textContent.includes('not connected'));assert.equal(a.q('#conversation-submit').disabled,false);a.q('#assistant-dialog').close();});
  await check('Program sheet and navigation still work',()=>{a.qa.resetResults();a.qa.openDetail('nutrien');assert.ok(a.q('#detail-content').textContent.includes('Check the current award cycle'));a.qa.moveProgram(1);assert.ok(a.q('#detail-content').textContent.includes('Talk to the STEPS team'));a.q('#detail-dialog').close();});
  await check('Save controls remain synchronized',()=>{a.qa.openDetail('psssp');a.qa.toggleSave('psssp');assert.ok([...a.d.querySelectorAll('#detail-dialog [data-save]')].every(x=>x.getAttribute('aria-pressed')==='true'));a.q('#detail-dialog').close();});
  await check('CSV exports demo/unknown metadata and blocks formula injection',async()=>{a.qa.clearFilters();a.w.location.hash='#statistics';a.qa.route();await tick();a.w.FundingModel.opportunities[0].title=' =UNTRUSTED()';a.click('#export-statistics');const csv=a.downloads.find(x=>x.text).text;assert.ok(csv.includes('data_mode'));assert.ok(csv.includes('demo'));assert.ok(csv.includes("' =UNTRUSTED()"));assert.ok(!csv.includes('undefined'));a.w.FundingModel.opportunities[0].title=dataset.records[0].title;});
  await check('Model contracts retain multiple provinces and community OR',()=>{const f=a.w.FundingModel.toFilters({location:['British Columbia','Ontario'],community:['Métis','Inuit']});assert.deepEqual(clone(f.provinces),['British Columbia','Ontario']);assert.deepEqual(clone(a.w.FundingModel.fromFilters(f).location),f.provinces);assert.equal(a.w.FundingModel.getResults(a.w.FundingModel.fromFilters(f)).length,3);});
  await check('Markup has unique IDs and local assets exist',()=>{const ids=[...a.d.querySelectorAll('[id]')].map(x=>x.id);assert.equal(new Set(ids).size,ids.length);for(const el of a.d.querySelectorAll('[src],link[href]')){const value=el.getAttribute('src')||el.getAttribute('href');if(value&&!/^(https?:|#)/.test(value))assert.ok(fs.existsSync(path.join(root,'dist',value.split('?')[0])),value);}});
  assert.deepEqual(a.errors,[],'Unexpected DOM exceptions');a.dom.window.close();
  const b=await setup({ai:true,multiple:true});
  await check('Shared LLM endpoint powers natural search',async()=>{b.w.location.hash='#explore';b.qa.route();b.q('#funding-search').value='Métis training support in BC or Ontario';await b.qa.insights.search();assert.equal(b.count(),2);assert.equal(b.requests.find(x=>x.url==='/api/conversation').body.mode,'search');assert.equal(b.q('#quick-location').value,'multiple');assert.ok(b.q('#active-filters').textContent.includes('Ontario'));});
  await check('Natural conversation uses the same endpoint and source cards',async()=>{b.click('#explore-view [data-assistant="match"]');b.q('#conversation-input').value='I am looking for training support';b.q('#conversation-form').dispatchEvent(new b.w.Event('submit',{bubbles:true,cancelable:true}));await tick();assert.ok(b.requests.some(x=>x.url==='/api/conversation'&&x.body.mode==='match'));assert.equal(b.d.querySelectorAll('#assistant-evidence-content .assistant-record').length,2);assert.ok(b.q('#conversation-thread').textContent.includes('Confirm provider'));});
  await check('Profile derives from conversation and resets without persistence',()=>{assert.equal(b.qa.state.profile.community,'Métis');b.click('#conversation-reset');assert.equal(b.qa.state.profile,null);assert.equal(b.q('#conversation-input').value,'');assert.equal(b.w.localStorage.length,1);});
  assert.deepEqual(b.errors,[],'Unexpected DOM exceptions');b.dom.window.close();
  const c=await setup({live:true});
  const nationwide=liveDataset.records.filter(x=>x.province==='all').length,regional=liveDataset.records.filter(x=>x.province&&x.province!=='all').length,unstated=liveDataset.records.filter(x=>!x.province).length;
  await check('Live data drops the demo wording',()=>{
    assert.equal(c.d.body.dataset.dataMode,'live');
    assert.equal(c.q('.site-header .button').textContent.trim(),'Open the app');
    assert.ok(!c.q('.hero-reassurance').textContent.toLowerCase().includes('demo'));
    assert.equal(c.q('.footer-demo').textContent,'Published records');
    assert.equal(c.q('.sidebar-demo').textContent,'Funding Navigator');
    assert.ok(!/Example data|Demo/.test(c.q('main').textContent+c.q('.site-footer').textContent),'demo wording left on the page');
  });
  await check('Cards say what a figure is, and never call a fixed amount "up to"',()=>{
    c.w.location.hash='#explore';c.qa.route();
    const cards=[...c.d.querySelectorAll('#results-grid .opportunity-card')];
    const noteOf=id=>cards.find(x=>x.querySelector(`[data-detail="${id}"]`)).querySelector('.card-amount small').textContent;
    assert.equal(cards.length,liveDataset.records.length);
    assert.equal(noteOf(liveDataset.records.find(x=>x.amount_details.kind==='fixed').id),'Listed amount');
    assert.equal(noteOf(liveDataset.records.find(x=>x.amount_details.kind==='maximum').id),'Up to');
    assert.ok(cards.every(x=>!/example/i.test(x.textContent)));
  });
  await check('A stated range is shown as a range, never as one figure and never as "varies"',()=>{
    c.w.location.hash='#explore';c.qa.route();
    const rec=liveDataset.records.find(x=>x.amount_details.kind==='range');
    const card=[...c.d.querySelectorAll('#results-grid .opportunity-card')].find(x=>x.querySelector(`[data-detail="${rec.id}"]`));
    const money=v=>new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD',maximumFractionDigits:0}).format(v);
    assert.equal(rec.amount,null);
    assert.equal(card.querySelector('.card-amount').firstChild.textContent.trim(),`${money(rec.amount_details.minimum)}\u2013${money(rec.amount_details.maximum)}`);
    assert.equal(card.querySelector('.card-amount small').textContent,'Listed range');
    assert.ok(!card.querySelector('.card-amount').classList.contains('is-unknown'));
  });
  await check('Statistics counts three region buckets that add up',async()=>{
    c.w.location.hash='#statistics';c.qa.route();await tick();
    const kpi=label=>[...c.d.querySelectorAll('.kpi')].find(x=>x.querySelector('p').textContent===label).querySelector('.kpi-value').textContent;
    assert.deepEqual(['Opportunities','Regions covered','National coverage','Regional support'].map(kpi),[String(liveDataset.records.length),'13 / 13',String(nationwide),String(regional)]);
    const buckets=[...c.d.querySelectorAll('#national-summary button')].map(x=>[x.querySelector('span').textContent,Number(x.querySelector('strong').textContent)]);
    assert.deepEqual(buckets,[['Across Canada',nationwide],['Region-specific',regional],['Region not stated',unstated]]);
    assert.equal(nationwide+regional+unstated,liveDataset.records.length);
    assert.ok(c.q('#statistics-methods-content').textContent.includes('never as national'));
    const ranges=liveDataset.records.filter(x=>x.amount_details.kind==='range').length;
    assert.ok(ranges>0,'the dataset has stated ranges');
    assert.equal(c.q('#amount-chart-note').textContent,`Listed figures, including caps. Not allocated funding. ${ranges} state a range instead (shown on their cards, counted here as not listed).`);
  });
  await check('"Region not stated" is a selectable bucket',async()=>{
    c.click('#national-summary [data-value="unspecified"]');await tick();
    assert.equal(c.qa.state.scope,'unspecified');
    assert.equal(c.q('.kpi-value').textContent,String(unstated));
    assert.equal(c.q('#amount-table-body').children.length,Math.min(40,unstated));
    c.click('#stats-clear-filters');await tick();
    assert.equal(c.q('.kpi-value').textContent,String(liveDataset.records.length));
  });
  await check('The timing chart covers every record',()=>{
    const total=[...c.d.querySelectorAll('#deadline-chart .chart-bar-label b')].reduce((sum,x)=>sum+Number(x.textContent),0);
    assert.equal(total,liveDataset.records.length);
  });
  const regionsByCode=c.w.FundingModel.regions;
  const countOf=name=>liveDataset.records.filter(x=>x.province===name).length;
  await check('Every province and territory has records: the map, its labels and the ranking all say so',async()=>{
    c.w.location.hash='#statistics';c.qa.route();await tick();
    assert.equal(Object.keys(regionsByCode).length,13);
    assert.equal(c.d.querySelectorAll('#canada-map path[data-region]').length,13);
    for(const [code,name] of Object.entries(regionsByCode)){
      assert.ok(countOf(name)>0,`${name} has no record`);
      const label=c.q(`#canada-map path[data-region="${code}"]`).getAttribute('aria-label');
      assert.ok(label.startsWith(`${name}: ${countOf(name)} regional, ${nationwide} nationwide`),label);
    }
    const labels=Object.fromEntries([...c.d.querySelectorAll('#canada-map .map-label')].map(x=>[x.querySelector('tspan').textContent,Number(x.querySelector('.map-count').textContent)]));
    for(const [code,name] of Object.entries(regionsByCode)){
      if(['NB','NS','PE'].includes(code))assert.equal(c.q(`#canada-map .map-chip[data-region="${code}"] text`).textContent,`${code} ${countOf(name)}`,code);
      else assert.equal(labels[code],countOf(name),code);
    }
    assert.ok(c.q('#map-coverage').textContent.includes('13 of 13'));
    assert.equal(c.d.querySelectorAll('#region-ranking .ranking-list li').length,13);
    assert.equal(c.d.querySelectorAll('#region-ranking button.is-empty').length,0);
    const ranked=[...c.d.querySelectorAll('#region-ranking button')].map(x=>[x.querySelector('.rank-name').textContent,Number(x.querySelector('b').textContent)]);
    assert.deepEqual(ranked,Object.values(regionsByCode).map(name=>[name,countOf(name)]).sort((a,b)=>b[1]-a[1]||(a[0]<b[0]?-1:1)));
  });
  await check('The colour scale starts at 0 and its top class is open-ended',()=>{
    const items=[...c.d.querySelectorAll('#map-legend li')].map(x=>x.textContent);
    assert.equal(items[0],'0');assert.ok(items.length>=3&&items.length<=6,items.join(' | '));assert.ok(/\+$/.test(items.at(-1)));
  });
  await check('The tile view shows the same numbers and hides the map while it is on',async()=>{
    c.click('[data-map-view="tiles"]');await tick();
    assert.equal(c.q('#tile-map').hidden,false);assert.equal(c.q('#canada-map').hidden,true);
    assert.equal(c.q('[data-map-view="tiles"]').getAttribute('aria-pressed'),'true');
    for(const [code,name] of Object.entries(regionsByCode))assert.equal(c.q(`#tile-map [data-region="${code}"] span`).textContent,String(countOf(name)),code);
    c.click('[data-map-view="map"]');await tick();assert.equal(c.q('#tile-map').hidden,true);assert.equal(c.q('#canada-map').hidden,false);
  });
  await check('Hovering a region shows its numbers and leaving hides them',()=>{
    c.q('#canada-map path[data-region="MB"]').dispatchEvent(new c.w.Event('pointerover',{bubbles:true}));
    const tip=c.q('#map-tooltip');assert.equal(tip.hidden,false);
    assert.ok(tip.textContent.includes('Manitoba')&&tip.textContent.includes(`${countOf('Manitoba')} region-specific`),tip.textContent);
    c.q('#canada-map').dispatchEvent(new c.w.Event('pointerleave'));assert.equal(tip.hidden,true);
  });
  await check('Choosing a region from the ranking filters every chart and shows that region\u2019s card',async()=>{
    c.click('#region-ranking [data-region="MB"]');await tick();
    assert.equal(c.qa.state.location,'Manitoba');
    assert.equal(c.q('.kpi-value').textContent,String(countOf('Manitoba')+nationwide+unstated)); // its own, the nationwide ones, and the ones that state no region
    assert.equal(c.q('#map-region-summary .region-insight-label').textContent,'Selected region');
    assert.equal(c.q('#map-region-summary .region-insight-name').textContent,'Manitoba');
    assert.equal(c.q('#map-region-summary .region-insight-value').textContent,String(countOf('Manitoba')));
    assert.ok(c.q('#map-coverage').textContent.includes('1 of 13'));
    c.click('#stats-clear-filters');await tick();
    assert.equal(c.q('.kpi-value').textContent,String(liveDataset.records.length));
  });
  await check('The source and currency panels add up to every record',()=>{
    const sum=sel=>[...c.d.querySelectorAll(`${sel} .chart-bar-label b`)].reduce((s,x)=>s+Number(x.textContent.split(' ')[0]),0);
    assert.equal(sum('#source-chart'),liveDataset.records.length);
    assert.equal(sum('#currency-chart'),liveDataset.records.length);
    const directory=liveDataset.records.filter(x=>x.source_kind==='directory_listing').length;
    assert.equal(Number(c.q('#source-chart .chart-bar-label b').textContent.split(' ')[0]),liveDataset.records.length-directory);
  });
  await check('The provider chart lists the biggest providers and choosing one filters',async()=>{
    assert.equal(c.d.querySelectorAll('#provider-chart .chart-bar').length,8);
    const name=c.q('#provider-chart .chart-bar').dataset.value;
    const expected=liveDataset.records.filter(x=>x.provider===name).length;
    assert.equal(Number(c.q('#provider-chart .chart-bar-label b').textContent.split(' ')[0]),expected);
    c.click('#provider-chart .chart-bar');await tick();
    assert.equal(c.qa.state.provider,name);assert.equal(c.q('.kpi-value').textContent,String(expected));
    c.click('#stats-clear-filters');await tick();
  });
  await check('The record table shows 40 rows and can show all of them',async()=>{
    assert.equal(c.q('#amount-table-body').children.length,40);
    assert.ok(c.q('#stats-rows-note').textContent.includes(`of ${liveDataset.records.length}`));
    c.click('[data-rows-toggle]');await tick();assert.equal(c.q('#amount-table-body').children.length,liveDataset.records.length);
    c.click('[data-rows-toggle]');await tick();assert.equal(c.q('#amount-table-body').children.length,40);
  });  await check('A federal directory entry carries the Government of Canada statement, the source sentences and its region basis',()=>{
    const entry=liveDataset.records.find(x=>x.source_kind==='directory_listing'&&x.province==='British Columbia');
    c.qa.openDetail(entry.id);
    const text=c.q('#detail-content').textContent;
    assert.ok(text.includes('published by Indigenous Services Canada'));
    assert.ok(text.includes('not produced in affiliation with, or with the endorsement of, the Government of Canada'));
    assert.ok(text.includes('What the source says'));
    assert.ok(text.includes('As listed in the federal directory'));
    assert.ok(text.includes('Published data')&&!/Example (data|criteria)/.test(text));
    c.q('#detail-dialog').close();
    c.qa.openDetail(liveDataset.records.find(x=>x.provider==='Simon Fraser University').id);
    assert.ok(!c.q('#detail-content').textContent.includes('Government of Canada'));
    c.q('#detail-dialog').close();
  });
  await check('The live CSV says it is published data',async()=>{
    c.w.location.hash='#statistics';c.qa.route();await tick();c.click('#export-statistics');
    const csv=c.downloads.find(x=>x.text).text;
    assert.ok(csv.includes('live')&&csv.includes('Quote-checked; unknown is not zero'));assert.ok(!csv.includes('Illustrative'));assert.ok(csv.includes('region_basis')&&csv.includes('source_page_last_changed')&&csv.includes('range_minimum'));
    const ranged=liveDataset.records.find(x=>x.amount_details.kind==='range'),row=csv.split('\r\n').find(l=>l.includes(`"${ranged.id}"`));
    assert.ok(row.includes(`"${ranged.amount_details.minimum}"`)&&row.includes(`"${ranged.amount_details.maximum}"`),'the CSV carries both ends of a range');assert.equal(csv.split('\r\n').length,liveDataset.records.length+1,'one CSV row per record');
  });
  assert.deepEqual(c.errors,[],'Unexpected DOM exceptions');c.dom.window.close();
  const m=await setup({live:true,healthMode:'demo'});
  await check('A backend running in another mode is named, not silently ignored',async()=>{
    m.w.location.hash='#statistics';m.qa.route();await tick();
    assert.ok(m.q('#ai-connection-status').textContent.includes('restart with --mode live'));
    assert.equal(m.q('#stats-backend-status').textContent,'HTML preview · mode mismatch');
  });
  assert.deepEqual(m.errors,[],'Unexpected DOM exceptions');m.dom.window.close();  console.log(JSON.stringify({passed,verification:'DOM emulation, mocked transport; not browser layout or a real LLM call'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
