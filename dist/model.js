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
    if(values(f.location).length&&item.province!=='all'&&!values(f.location).includes(item.province))return false;
    if(values(f.goal).length&&!values(f.goal).some(x=>item.goals.includes(x)))return false;
    if(f.amount==='listed'&&item.amount===null)return false;
    if(f.amount==='high'&&!(item.amount>5000))return false;
    if(f.amount==='under5000'&&!(item.amount!==null&&item.amount<=5000))return false;
    if(f.amount==='unknown'&&item.amount!==null)return false;
    const includeUnknown=f.includeUnknown!==false;
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
    if(f.scope==='national'&&item.province!=='all')return false;
    if(f.scope==='regional'&&item.province==='all')return false;
    if(f.savedOnly&&!(f.saved||[]).includes(item.id))return false;
    if(f.aiIds&&!f.aiIds.includes(item.id))return false;
    return true;
  }
  function getResults(filters){
    const rows=opportunities.filter(item=>matches(item,filters));
    if(filters.aiIds)rows.sort((a,b)=>filters.aiIds.indexOf(a.id)-filters.aiIds.indexOf(b.id));
    if(filters.sort==='amount')rows.sort((a,b)=>(b.amount??-1)-(a.amount??-1)||a.id.localeCompare(b.id));
    if(filters.sort==='alphabetical')rows.sort((a,b)=>normalize(a.title).localeCompare(normalize(b.title))||a.id.localeCompare(b.id));
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
    const known=rows.filter(x=>x.amount!==null);
    const count=key=>rows.reduce((out,x)=>{out[x[key]]=(out[x[key]]||0)+1;return out;},{});
    return {data_mode:root.FundingModel.mode,dataset_version:root.FundingModel.mode==='demo'?'frontend-examples-v5':'live-read-model',total:rows.length,national_count:national,regional_count:rows.length-national,regions:Object.entries(regions).map(([code,name])=>({code,name,regional_count:rows.filter(x=>x.province===name).length,national_count:national,reach_count:national+rows.filter(x=>x.province===name).length})),by_type:count('type'),by_community:Object.fromEntries(['First Nations','Inuit','Métis'].map(c=>[c,rows.filter(x=>x.community.includes(c)).length])),amounts:{listed:known.length,unknown:rows.length-known.length,highest_example_figure:known.length?String(Math.max(...known.map(x=>Number(x.amount)))):null,sum:null},amount_bands:{up_to_5000:known.filter(x=>Number(x.amount)<=5000).length,above_5000:known.filter(x=>Number(x.amount)>5000).length,unknown:rows.length-known.length},by_deadline_kind:count('deadline_kind'),amount_rows:rows,quality:{verified_records:rows.filter(x=>x.last_verified_at).length,unknown_education_level:rows.filter(x=>!x.education_levels).length}};
  }
  function amountText(item){return item.amount===null?'Funding varies':new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD',maximumFractionDigits:0}).format(Number(item.amount));}
  const ready=fetch('data/opportunities.json').then(r=>{if(!r.ok)throw new Error('Dataset unavailable');return r.json();}).then(data=>{
    const demo=data.data_mode==='demo';
    if(!['demo','live'].includes(data.data_mode)||data.records.some(x=>Boolean(x.is_demo)!==demo))throw new Error('Unexpected dataset mode');
    opportunities.push(...data.records);
    root.FundingModel.mode=data.data_mode;
    return data;
  });
  root.FundingModel={mode:'demo',opportunities,regions,filterKeys,matches,getResults,amountText,toFilters,fromFilters,statistics,ready};
})(globalThis);
