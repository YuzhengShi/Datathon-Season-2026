/* What the Statistics page says about each province and territory. Pure functions: records in, numbers out, so the same
   numbers can be checked without a browser (tests/js/regions.test.mjs). The page draws them (insights.js). */
(function(root){
  'use strict';
  const PALETTE=['#e6ecdd','#d3e2c0','#b1cc92','#88b169','#5b8f45','#356b34'];
  /* Equal-size tiles in roughly the shape of the country, so Prince Edward Island is as readable as Nunavut: [column,row]. */
  const TILES={YT:[2,1],NT:[3,1],NU:[4,1],BC:[1,2],AB:[2,2],SK:[3,2],MB:[4,2],ON:[5,2],QC:[6,2],NL:[7,2],NB:[6,3],PE:[7,3],NS:[7,4]};

  function tally(rows,pick){
    return rows.reduce((out,row)=>{for(const key of pick(row))out[key]=(out[key]||0)+1;return out;},{});
  }
  /* The numbers for one group of records (a region, "across Canada" or "not stated"). */
  function describe(rows){
    const figures=rows.filter(x=>x.amount!==null&&x.amount!==undefined).map(x=>Number(x.amount));
    const years=rows.map(x=>x.source_modified_at).filter(Boolean).map(x=>Number(String(x).slice(0,4))).filter(Number.isFinite);
    const providers=Object.entries(tally(rows,x=>[x.provider])).sort((a,b)=>b[1]-a[1]||(a[0]<b[0]?-1:1));
    return {
      count:rows.length,
      directory:rows.filter(x=>x.source_kind==='directory_listing').length,
      verified:rows.filter(x=>x.source_kind!=='directory_listing').length,
      community:tally(rows,x=>x.community||[]),
      types:tally(rows,x=>[x.type]),
      deadlines:tally(rows,x=>[x.deadline_kind||'unspecified']),
      listed:figures.length,
      lowest:figures.length?Math.min(...figures):null,
      highest:figures.length?Math.max(...figures):null,
      providers:providers.slice(0,3).map(([name,count])=>({name,count})),
      providerCount:providers.length,
      oldest:years.length?Math.min(...years):null,
      newest:years.length?Math.max(...years):null,
    };
  }
  /* regions: {BC:'British Columbia',...}. Every record lands in exactly one place: its region, across Canada, or not stated. */
  function summarize(rows,regions){
    const places=new Map(Object.entries(regions).map(([code,name])=>[name,{code,name,rows:[]}]));
    const national=[],unstated=[];
    for(const row of rows){
      if(row.province==='all')national.push(row);
      else if(row.province&&places.has(row.province))places.get(row.province).rows.push(row);
      else unstated.push(row);
    }
    const list=[...places.values()].map(place=>({code:place.code,name:place.name,...describe(place.rows),regional:place.rows.length,nationwide:national.length,reach:place.rows.length+national.length}));
    return {total:rows.length,regions:list,nationwide:describe(national),unstated:describe(unstated),covered:list.filter(r=>r.regional>0).length};
  }
  /* Up to five classes cut from the data itself (quantiles of the non-zero counts), so one large region does not wash out
     the rest; 0 is always its own class. The top class is never empty. */
  function scale(values){
    const positive=values.filter(v=>v>0).sort((a,b)=>a-b);
    const edges=[];
    for(let i=1;i<=4&&positive.length;i++){
      const q=positive[Math.min(positive.length-1,Math.ceil(positive.length*i/5)-1)];
      if(q<positive[positive.length-1]&&(!edges.length||q>edges[edges.length-1]))edges.push(q);
    }
    const classes=edges.length+1;
    const classOf=v=>{
      if(!(v>0))return 0;
      const at=edges.findIndex(edge=>v<=edge);
      return at<0?edges.length+1:at+1;
    };
    const color=cls=>cls===0?PALETTE[0]:PALETTE[classes===1?4:1+Math.round((cls-1)*4/(classes-1))];
    const legend=[{cls:0,min:0,max:0,color:PALETTE[0],label:'0'}];
    if(positive.length){
      for(let cls=1;cls<=classes;cls++){
        const min=cls===1?1:edges[cls-2]+1,max=cls<=edges.length?edges[cls-1]:Infinity;
        legend.push({cls,min,max,color:color(cls),label:max===Infinity?`${min}+`:min===max?String(min):`${min}–${max}`});
      }
    }
    return {classOf,color,legend,edges};
  }
  /* Provider pages (read and quote-checked) against federal directory entries. */
  function sourceMix(rows){
    const directory=rows.filter(x=>x.source_kind==='directory_listing').length;
    return {directory,verified:rows.length-directory};
  }
  /* The year each source page says it was last changed: directory entries state it, many provider pages do not. */
  function currency(rows){
    const groups=[{label:'2015 or earlier',from:0,to:2015,count:0},{label:'2016–2019',from:2016,to:2019,count:0},{label:'2020–2022',from:2020,to:2022,count:0},{label:'2023 or later',from:2023,to:9999,count:0}];
    let unknown=0;
    for(const row of rows){
      const year=row.source_modified_at?Number(String(row.source_modified_at).slice(0,4)):NaN;
      const group=Number.isFinite(year)?groups.find(g=>year>=g.from&&year<=g.to):null;
      if(group)group.count++;else unknown++;
    }
    return {groups,unknown};
  }
  function topProviders(rows,limit){
    return Object.entries(tally(rows,x=>[x.provider])).sort((a,b)=>b[1]-a[1]||(a[0]<b[0]?-1:1)).slice(0,limit).map(([name,count])=>({name,count}));
  }
  root.FundingRegions={summarize,describe,scale,sourceMix,currency,topProviders,TILES,PALETTE};
})(globalThis);
