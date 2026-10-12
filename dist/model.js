(function(root){
  'use strict';
  const opportunities=[];
  const regions={BC:'British Columbia',AB:'Alberta',SK:'Saskatchewan',MB:'Manitoba',ON:'Ontario',QC:'Quebec',NB:'New Brunswick',NS:'Nova Scotia',PE:'Prince Edward Island',NL:'Newfoundland and Labrador',YT:'Yukon',NT:'Northwest Territories',NU:'Nunavut'};
  const filterKeys=['community','location','type','amount','goal','level','field','studyMode','expense','renewable','deadline','provider','scope'];
  const normalize=value=>String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();
  const values=value=>Array.isArray(value)?value:value&&value!=='all'?[value]:[];
  function matches(item,f){
    const query=normalize(f.query||'').trim();
    if(query&&!normalize([item.title,item.fullTitle,item.provider,item.summary,item.location,item.type,...item.community].join(' ')).includes(query))return false;
    if(values(f.type).length&&!values(f.type).includes(item.type))return false;
    if(values(f.community).length&&!values(f.community).some(x=>item.community.includes(x)))return false;
    const includeUnknown=f.includeUnknown!==false;
    const province=item.province||null;/* null = the source states no region; the Python service reads it the same way */
    if(values(f.location).length&&province!=='all'&&!values(f.location).includes(province)&&(province||!includeUnknown))return false;
    if(values(f.goal).length&&!values(f.goal).some(x=>item.goals.includes(x)))return false;
    if(f.amount==='listed'&&item.amount===null)return false;
    if(f.amount==='high'&&!(item.amount>5000))return false;
    if(f.amount==='under5000'&&!(item.amount!==null&&item.amount<=5000))return false;
    if(f.amount==='unknown'&&item.amount!==null)return false;
    for(const [key,recordKey] of [['level','education_levels'],['field','fields_of_study'],['studyMode','study_modes'],['expense','expenses']]){
      if(f[key]&&f[key]!=='all'){
        const actual=item[recordKey];
        if(!actual?.length&&!includeUnknown||actual?.length&&!values(f[key]).some(x=>actual.includes(x)))return false;
      }
    }
    const renewable=item.amount_details?.renewable;
    if(f.renewable&&f.renewable!=='all'){
      const expected={yes:true,no:false,unknown:null}[f.renewable];
      if(expected===null&&renewable!==null||renewable!==expected&&!(renewable===null&&includeUnknown))return false;
    }
    if(f.deadline&&f.deadline!=='all'&&item.deadline_kind!==f.deadline&&!(item.deadline_kind==='unspecified'&&includeUnknown))return false;
    if(values(f.provider).length&&!values(f.provider).includes(item.provider))return false;
    if(f.scope==='national'&&province!=='all')return false;
    if(f.scope==='regional'&&(!province||province==='all'))return false;
    if(f.scope==='unspecified'&&province)return false;
    if(f.savedOnly&&!(f.saved||[]).includes(item.id))return false;
    if(f.aiIds&&!f.aiIds.includes(item.id))return false;
    return true;
  }
  function getResults(filters){
    const rows=opportunities.filter(item=>matches(item,filters));
    if(filters.aiIds)rows.sort((a,b)=>filters.aiIds.indexOf(a.id)-filters.aiIds.indexOf(b.id));
    /* Ties break by code point, exactly like the server's Python sort: localeCompare puts ':' '_' and '-' in another order, so the site and the API listed the same records differently once ids had suffixes. */
    const byText=(a,b)=>a<b?-1:a>b?1:0;
    if(filters.sort==='amount')rows.sort((a,b)=>(b.amount??-1)-(a.amount??-1)||byText(a.id,b.id));
    if(filters.sort==='alphabetical')rows.sort((a,b)=>byText(normalize(a.title),normalize(b.title))||byText(a.id,b.id));
    return rows;
  }
  function toFilters(f){
    const list=values;
    return {q:f.query||'',communities:list(f.community),provinces:list(f.location),types:list(f.type),goals:list(f.goal),scope:f.scope||'all',amount_band:f.amount||'all',amount_kind:'all',education_levels:list(f.level),fields_of_study:list(f.field),study_modes:list(f.studyMode),expenses:list(f.expense),renewable:f.renewable||'all',deadline_kind:f.deadline||'all',providers:list(f.provider),include_unknown:f.includeUnknown!==false,sort:f.sort||'recommended'};
  }
  function fromFilters(f){
    const first=values=>values?.length>1?values:values?.[0]||'all';
    return {query:f.q||'',community:first(f.communities),location:first(f.provinces),type:first(f.types),goal:first(f.goals),scope:f.scope,amount:f.amount_band,level:first(f.education_levels),field:first(f.fields_of_study),studyMode:first(f.study_modes),expense:first(f.expenses),renewable:f.renewable,deadline:f.deadline_kind,provider:first(f.providers),includeUnknown:f.include_unknown,sort:f.sort};
  }
  function statistics(filters){
    const rows=getResults({...filters,query:'',savedOnly:false,aiIds:null});
    const national=rows.filter(x=>x.province==='all').length;
    const regional=rows.filter(x=>x.province&&x.province!=='all').length;
    const known=rows.filter(x=>x.amount!==null);
    const count=key=>rows.reduce((out,x)=>{out[x[key]]=(out[x[key]]||0)+1;return out;},{});
    return {data_mode:root.FundingModel.mode,dataset_version:root.FundingModel.mode==='demo'?'frontend-examples-v5':'live-read-model',total:rows.length,national_count:national,regional_count:regional,unspecified_region_count:rows.length-national-regional,regions:Object.entries(regions).map(([code,name])=>({code,name,regional_count:rows.filter(x=>x.province===name).length,national_count:national,reach_count:national+rows.filter(x=>x.province===name).length})),by_type:count('type'),by_community:Object.fromEntries(['First Nations','Inuit','Métis'].map(c=>[c,rows.filter(x=>x.community.includes(c)).length])),amounts:{listed:known.length,unknown:rows.length-known.length,highest_example_figure:known.length?String(Math.max(...known.map(x=>Number(x.amount)))):null,sum:null},amount_bands:{up_to_5000:known.filter(x=>Number(x.amount)<=5000).length,above_5000:known.filter(x=>Number(x.amount)>5000).length,unknown:rows.length-known.length},by_deadline_kind:count('deadline_kind'),amount_rows:rows,quality:{verified_records:rows.filter(x=>x.last_verified_at).length,unknown_education_level:rows.filter(x=>!x.education_levels?.length).length}};
  }
  const money=value=>new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD',maximumFractionDigits:0}).format(Number(value));
  /* A stated range is shown as a range ("$2,000–$4,000"), never as one figure; no figure at all is "Funding varies". */
  const rangeOf=item=>{const d=item.amount_details;return d&&d.kind==='range'&&d.minimum!=null&&d.maximum!=null?d:null;};
  const hasAmount=item=>(item.amount!==null&&item.amount!==undefined)||Boolean(rangeOf(item));
  function amountText(item){
    if(item.amount===null||item.amount===undefined){const range=rangeOf(item);return range?`${money(range.minimum)}–${money(range.maximum)}`:'Funding varies';}
    return money(item.amount);
  }
  const isDemo=()=>root.FundingModel.mode==='demo';
  /* What a figure is: the kind of amount the source states. A fixed amount is never "up to"; "example" is for demo data only. */
  function amountNote(item){
    if(item.amount===null||item.amount===undefined){if(!rangeOf(item))return 'Confirm amount';return isDemo()?'Listed range · example':'Listed range';}
    const kind=item.amount_details?.kind;
    const base=kind==='maximum'?'Up to':kind==='fixed'?'Listed amount':'Listed figure';
    return isDemo()?`${base} · example`:base;
  }
  function regionNote(item){
    return ({rule:'From the eligibility rules',directory:'As listed in the federal directory',not_stated:'The source does not state a region'})[item.region_basis]||'';
  }
  function copy(){
    const demo=isDemo();
    return {demo,product:demo?'This demo':'This app',tag:demo?'Example data':'Published data',criteriaNote:demo?'Example criteria. Confirm all requirements with the provider.':'A starting point, not a confirmation. Confirm all requirements with the provider.'};
  }
  /* The Government of Canada asks that a non-commercial copy says it is a copy of an official work and is not endorsed. */
  function governmentAttribution(item){
    const fromCanada=(item.evidence_refs||[]).some(ref=>/^https?:\/\/(www\.)?sac-isc\.gc\.ca\//.test(ref.source_url||''));
    if(!fromCanada)return null;
    const material=item.source_kind==='directory_listing'?'Indigenous Bursaries Search Tool':item.title;
    return `Contains information from “${material}”, published by Indigenous Services Canada. This is a copy of an official work published by the Government of Canada; it was not produced in affiliation with, or with the endorsement of, the Government of Canada.`;
  }
  const evidenceKinds=[['amount','Amount'],['deadline','Deadline'],['eligib','Who can apply'],['application','How to apply']];
  /* The source's own sentences behind a record: one line per distinct quote, with where it was read. */
  function evidenceItems(item,limit=8){
    const seen=new Set(),out=[];
    for(const ref of item.evidence_refs||[]){
      const quote=String(ref.quote||'').trim();
      if(!quote||seen.has(quote))continue;
      seen.add(quote);
      const path=String(ref.field_path||'').toLowerCase();
      out.push({label:(evidenceKinds.find(([key])=>path.includes(key))||['','From the source'])[1],quote:quote.length>280?quote.slice(0,277)+'…':quote,url:/^https?:\/\//.test(ref.source_url||'')?ref.source_url:null});
      if(out.length>=limit)break;
    }
    return out;
  }
  const ready=fetch('data/opportunities.json').then(r=>{if(!r.ok)throw new Error('Dataset unavailable');return r.json();}).then(data=>{
    const demo=data.data_mode==='demo';
    if(!['demo','live'].includes(data.data_mode)||data.records.some(x=>Boolean(x.is_demo)!==demo))throw new Error('Unexpected dataset mode');
    opportunities.push(...data.records);
    root.FundingModel.mode=data.data_mode;
    return data;
  });
  root.FundingModel={mode:'demo',opportunities,regions,filterKeys,matches,getResults,amountText,amountNote,hasAmount,regionNote,copy,governmentAttribution,evidenceItems,toFilters,fromFilters,statistics,ready};
})(globalThis);
