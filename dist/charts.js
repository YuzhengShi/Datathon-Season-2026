/* Buildless SVG report charts. Every mark comes from selected records. */
(function(root){
  'use strict';
  const communities=['First Nations','Inuit','Métis'];
  const palette=['#456c4c','#719365','#adc397','#d2b48c','#839ba0','#c8d4b7','#a3937d','#dedcca'];
  const timingLabels={date:'Date listed',annual_rule:'Every year',due_every_year:'Every year',recurring:'Every year',rolling:'Rolling intake',local_administrator:'Set locally',unspecified:'Date unspecified'};
  const timingColors={date:'#456c4c',annual_rule:'#719365',due_every_year:'#719365',recurring:'#719365',rolling:'#9cb888',local_administrator:'#c6aa85',unspecified:'#dce3d4',other:'#879da2'};
  const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=value=>new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD',maximumFractionDigits:0}).format(value);
  const pct=(n,d)=>d?Math.round(n/d*100):0;
  const finite=value=>(typeof value==='number'||typeof value==='string'&&value.trim()!=='')&&Number.isFinite(Number(value))&&Number(value)>=0;
  const selected=(value,target)=>Array.isArray(value)?value.includes(target):value===target;
  function amountObservations(rows){
    return rows.filter(row=>finite(row.amount)&&row.amount_details?.kind!=='pooled_total'&&(!row.amount_details?.currency||row.amount_details.currency==='CAD')).map(row=>({...row,value:Number(row.amount)})).sort((a,b)=>a.value-b.value||String(a.id).localeCompare(String(b.id)));
  }
  function quantile(sorted,q){
    if(!sorted.length)return null;
    const position=(sorted.length-1)*q,index=Math.floor(position),fraction=position-index;
    return sorted[index]+(sorted[Math.min(index+1,sorted.length-1)]-sorted[index])*fraction;
  }
  function cumulative(observations){
    const groups=[];
    for(const row of observations){const last=groups.at(-1);if(last?.value===row.value)last.count++;else groups.push({value:row.value,count:1});}
    let running=0;
    return groups.map(group=>({...group,cumulative:running+=group.count,share:running/observations.length}));
  }
  // Gaussian KDE of log1p amounts, with a robust normal-reference bandwidth.
  // This is an estimated distribution, never a historical or forecast series.
  function density(observations,domain,steps=96){
    if(observations.length<2)return null;
    const values=observations.map(row=>Math.log1p(row.value)),n=values.length,mean=values.reduce((a,b)=>a+b,0)/n;
    const sd=Math.sqrt(values.reduce((sum,value)=>sum+(value-mean)**2,0)/(n-1)),iqr=(quantile(values,.75)-quantile(values,.25))/1.34;
    const spreads=[sd,iqr].filter(value=>value>0),reference=spreads.length?Math.min(...spreads):.35;
    const bandwidth=Math.max(.12,.9*reference*n**(-.2)),limit=Math.log1p(domain),normalizer=n*bandwidth*Math.sqrt(2*Math.PI);
    return {bandwidth,points:Array.from({length:steps+1},(_,index)=>{const logValue=index/steps*limit,concentration=values.reduce((sum,value)=>sum+Math.exp(-.5*((logValue-value)/bandwidth)**2),0)/normalizer;return {value:Math.expm1(logValue),concentration};})};
  }
  function coverage(rows,regions){
    return Object.entries(regions).map(([code,name])=>({code,name,counts:communities.map(community=>rows.filter(row=>(row.province==='all'||row.province===name)&&row.community?.includes(community)).length)}));
  }
  function providers(rows){
    const counts=new Map();
    for(const row of rows){const name=row.provider||'Provider not stated';counts.set(name,(counts.get(name)||0)+1);}
    return [...counts].map(([name,count])=>({name,count,value:name==='Provider not stated'?null:name})).sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name));
  }
  // Squarified treemap. Areas are proportional before the visual gutters.
  function treemap(entries,width,height){
    const total=entries.reduce((sum,x)=>sum+x.count,0);if(!total)return [];
    let rest=entries.map(item=>({...item,area:item.count/total*width*height})),box={x:0,y:0,w:width,h:height};const output=[];
    function worst(row,side){if(!row.length)return Infinity;const sum=row.reduce((s,x)=>s+x.area,0),max=Math.max(...row.map(x=>x.area)),min=Math.min(...row.map(x=>x.area));return Math.max(side*side*max/(sum*sum),sum*sum/(side*side*min));}
    while(rest.length){
      const side=Math.min(box.w,box.h);let row=[rest.shift()];
      while(rest.length&&worst([...row,rest[0]],side)<=worst(row,side))row.push(rest.shift());
      const area=row.reduce((sum,x)=>sum+x.area,0),vertical=box.w>=box.h,thickness=area/(vertical?box.h:box.w);let offset=0;
      for(const item of row){const length=item.area/thickness;output.push({...item,x:box.x+(vertical?0:offset),y:box.y+(vertical?offset:0),w:vertical?thickness:length,h:vertical?length:thickness});offset+=length;}
      if(vertical){box.x+=thickness;box.w=Math.max(0,box.w-thickness);}else{box.y+=thickness;box.h=Math.max(0,box.h-thickness);}
    }
    return output;
  }
  function waffle(entries){
    const total=entries.reduce((sum,x)=>sum+x.count,0),tiles=Math.min(total,100);if(!total)return {total:0,tiles:0,entries:[]};
    const allocated=entries.map((entry,index)=>{const exact=entry.count/total*tiles;return {...entry,index,tiles:Math.floor(exact),remainder:exact-Math.floor(exact)};});
    let remaining=tiles-allocated.reduce((sum,x)=>sum+x.tiles,0);
    for(const entry of [...allocated].sort((a,b)=>b.remainder-a.remainder||a.index-b.index)){if(!remaining)break;entry.tiles++;remaining--;}
    return {total,tiles,entries:allocated};
  }
  function empty(message,detail){return `<div class="chart-empty"><span class="empty-chart-mark" aria-hidden="true">∿</span><strong>${e(message)}</strong><small>${e(detail)}</small></div>`;}
  function amountChart(rows,view){
    const observations=amountObservations(rows),values=observations.map(x=>x.value),median=quantile(values,.5);
    const metric=median===null?'<strong>—</strong><span>No comparable CAD figures</span>':`<strong>${money(median)}</strong><span>Median listed figure <b>${observations.length} of ${rows.length} records</b></span>`;
    if(!observations.length)return {metric,html:empty('No listed CAD figures','Unknown amounts remain in the selection.'),note:'Listed figures include caps. Pool totals and other currencies are excluded.'};
    const W=520,H=252,L=43,R=18,T=17,B=43,bottom=H-B,right=W-R,domain=Math.max(5000,...values)*1.12;
    const x=value=>L+Math.log1p(value)/Math.log1p(domain)*(right-L),y=share=>bottom-share*(bottom-T);
    const ticks=[0,100,1000,5000,10000,50000,100000,500000,1000000].filter(v=>v<=domain);
    let visibleTicks=[];for(const tick of ticks){if(!visibleTicks.length||x(tick)-x(visibleTicks.at(-1))>43)visibleTicks.push(tick);}
    const tickText=value=>value>=1000?'$'+value/1000+'k':'$'+value;
    const xAxis=visibleTicks.map(value=>`<line x1="${x(value)}" y1="${bottom}" x2="${x(value)}" y2="${bottom+5}" class="chart-axis-line"/><text x="${x(value)}" y="${bottom+20}" text-anchor="middle" class="chart-axis-label">${tickText(value)}</text>`).join('');
    let content,description;
    if(view==='curve'&&observations.length>=2){
      const estimate=density(observations,domain),maximum=Math.max(...estimate.points.map(point=>point.concentration));
      const points=estimate.points.map(point=>[x(point.value),y(point.concentration/maximum*.92)]),path=points.map((point,index)=>`${index?'L':'M'} ${point[0]} ${point[1]}`).join(' ');
      const grid=[0,.5,1].map(share=>`<line x1="${L}" y1="${y(share)}" x2="${right}" y2="${y(share)}" class="chart-grid-line"/>`).join('');
      const rug=observations.map(row=>{const tip=`${row.title} · ${money(row.value)} · observed listed figure`;return `<g class="chart-record" role="button" tabindex="0" data-detail="${e(row.id)}" data-chart-tip="${e(tip)}" aria-label="Open ${e(tip)}"><rect x="${x(row.value)-5}" y="${bottom-8}" width="10" height="15" fill="transparent"/><line x1="${x(row.value)}" x2="${x(row.value)}" y1="${bottom-5}" y2="${bottom+5}" stroke="#597b4f" stroke-width="2"/></g>`;}).join('');
      content=`<defs><linearGradient id="amount-density-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#9dbc83" stop-opacity=".5"/><stop offset="100%" stop-color="#d9e6c9" stop-opacity=".13"/></linearGradient></defs>${grid}<text x="${L}" y="${T-6}" class="chart-lane-label">ESTIMATED CONCENTRATION</text><path d="${path} L ${right} ${bottom} L ${L} ${bottom} Z" fill="url(#amount-density-fill)"/><path d="${path}" class="cumulative-line"/>${rug}`;
      description=`Smoothed distribution of ${observations.length} listed figures. Baseline marks are actual records; click to inspect. Small samples give a coarse estimate.`;
    }else if(view==='dots'){
      const lanes={Scholarship:78,Program:165},seen=new Map();
      const dots=observations.map(row=>{const base=lanes[row.type]||122,key=row.type+':'+row.value,rank=seen.get(key)||0;seen.set(key,rank+1);const py=base+((rank%9)-4)*6,px=x(row.value),color=row.type==='Scholarship'?'#be9568':'#557b54',max=row.amount_details?.kind==='maximum',tip=`${row.title} · ${money(row.value)} · ${max?'listed cap':'listed figure'}`;return `<g class="chart-record" role="button" tabindex="0" data-detail="${e(row.id)}" data-chart-tip="${e(tip)}" aria-label="Open ${e(tip)}">${max?`<path d="M ${px} ${py-6} L ${px+6} ${py+5} L ${px-6} ${py+5} Z" fill="${color}"/>`:`<circle cx="${px}" cy="${py}" r="5" fill="${color}"/>`}</g>`;}).join('');
      content=`<line x1="${L}" y1="78" x2="${right}" y2="78" class="chart-grid-line"/><line x1="${L}" y1="165" x2="${right}" y2="165" class="chart-grid-line"/><text x="${L}" y="47" class="chart-lane-label">SCHOLARSHIPS &amp; AWARDS</text><text x="${L}" y="134" class="chart-lane-label">FUNDING PROGRAMS</text>${dots}`;
      description='Each mark is one selected record. Triangle: listed cap. Click a mark to open its record.';
    }else{
      const groups=cumulative(observations);let path=`M ${L} ${bottom}`;
      for(const group of groups)path+=` H ${x(group.value)} V ${y(group.share)}`;
      path+=` H ${right}`;
      const grid=[0,.25,.5,.75,1].map(share=>`<line x1="${L}" y1="${y(share)}" x2="${right}" y2="${y(share)}" class="chart-grid-line"/><text x="${L-10}" y="${y(share)+4}" text-anchor="end" class="chart-axis-label">${share*100}%</text>`).join('');
      const marks=groups.map(group=>{const tip=`At or below ${money(group.value)} · ${group.cumulative} of ${observations.length} listed figures (${pct(group.cumulative,observations.length)}%)`;return `<g class="curve-observation" role="img" tabindex="0" aria-label="${e(tip)}" data-chart-tip="${e(tip)}"><circle cx="${x(group.value)}" cy="${y(group.share)}" r="10" fill="transparent"/><circle cx="${x(group.value)}" cy="${y(group.share)}" r="4" fill="#476e4c" stroke="#fff" stroke-width="2"/></g>`;}).join('');
      content=`<defs><linearGradient id="amount-area-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#85a86d" stop-opacity=".35"/><stop offset="100%" stop-color="#b7cfa0" stop-opacity=".03"/></linearGradient></defs>${grid}<path d="${path} L ${right} ${bottom} Z" fill="url(#amount-area-fill)"/><path d="${path}" class="cumulative-line"/>${marks}`;
      description='Cumulative share of listed figures at or below each amount. Steps show observed data.';
    }
    const html=`<svg class="report-svg amount-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="${e(description)}">${content}${xAxis}<text x="${(L+right)/2}" y="${H-4}" text-anchor="middle" class="chart-axis-title">Listed CAD figure · logarithmic spacing</text></svg>`;
    const note=view==='curve'&&observations.length>=2?`Smoothed estimate · ${observations.length} listed figures, including caps. Small samples are coarse.`:view==='dots'?'Each mark opens a record. Triangles indicate caps; figures aren’t awarded money.':'Cumulative share of listed CAD figures, including caps. Pool totals are excluded.';
    return {metric,html,note};
  }
  function heatmap(rows,regions,state){
    const matrix=coverage(rows,regions),max=Math.max(1,...matrix.flatMap(x=>x.counts)),colors=['#f0f3eb','#dee8d3','#bed1a7','#8fae76','#4e744d'];
    return `<table class="coverage-matrix"><caption class="visually-hidden">Unique records reaching each community and region, including national records</caption><thead><tr><th scope="col">Community</th>${matrix.map(row=>`<th scope="col"><abbr title="${e(row.name)}">${row.code}</abbr></th>`).join('')}</tr></thead><tbody>${communities.map((community,index)=>`<tr><th scope="row">${e(community)}</th>${matrix.map(row=>{const count=row.counts[index],shade=count?Math.max(1,Math.ceil(count/max*4)):0,active=selected(state.location,row.name)&&selected(state.community,community),tip=`${row.name} · ${community} · ${count} records (includes national coverage)`;return `<td><button data-heat-region="${row.code}" data-heat-community="${e(community)}" data-chart-tip="${e(tip)}" aria-label="Filter ${e(tip)}" aria-pressed="${active}" style="--cell-fill:${colors[shade]};--cell-text:${shade>=4?'#fff':'#476040'}">${count}</button></td>`;}).join('')}</tr>`).join('')}</tbody></table>`;
  }
  function providerChart(rows){
    const all=providers(rows);if(!all.length)return {html:empty('No providers in this selection','Reset a filter to explore the report.'),note:'Rectangle area shows each provider’s share of records.'};
    const top=all.slice(0,11),rest=all.slice(11);if(rest.length)top.push({name:`${rest.length} other providers`,value:null,count:rest.reduce((sum,x)=>sum+x.count,0)});
    const W=420,H=260,rects=treemap(top,W,H);
    function lines(name,width,height){const limit=Math.max(5,Math.floor(width/7)),words=name.split(/\s+/),output=[];let line='';for(const word of words){if((line+' '+word).trim().length>limit&&line){output.push(line);line=word;}else line=(line+' '+word).trim();}if(line)output.push(line);const count=Math.max(0,Math.min(3,Math.floor((height-50)/17)));return output.slice(0,count).map((line,i)=>e(line.length>limit?line.slice(0,limit-1)+'…':line)+(i===count-1&&output.length>count?'…':''));}
    const svg=`<svg class="report-svg treemap-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="Provider share of selected records">${rects.map((rect,index)=>{const x=rect.x+3,y=rect.y+3,w=Math.max(0,rect.w-6),h=Math.max(0,rect.h-6),dark=[0,1,4].includes(index%palette.length),text=dark?'#fff':'#344b36',tip=`${rect.name} · ${rect.count} of ${rows.length} records (${pct(rect.count,rows.length)}%)`,title=lines(rect.name,w-26,h),interactive=rect.value!==null;return `<g class="treemap-cell" ${interactive?`role="button" tabindex="0" data-stats-selection="provider" data-value="${e(rect.value)}"`:'role="img" tabindex="0"'} data-chart-tip="${e(tip)}" aria-label="${e(tip)}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${palette[index%palette.length]}"/>${w>70&&h>60?`<text x="${x+13}" y="${y+25}" fill="${text}" class="treemap-name">${title.map((line,i)=>`<tspan x="${x+13}" dy="${i?17:0}">${line}</tspan>`).join('')}</text><text x="${x+13}" y="${y+h-17}" fill="${text}" class="treemap-count">${rect.count}<tspan class="treemap-share"> / ${pct(rect.count,rows.length)}%</tspan></text>`:''}</g>`;}).join('')}</svg>`;
    const directory=`<details class="provider-directory"><summary>View ${all.length} providers</summary><div>${all.map(item=>item.value?`<button data-stats-selection="provider" data-value="${e(item.value)}"><span>${e(item.name)}</span><b>${item.count}</b></button>`:`<span>${e(item.name)} · ${item.count}</span>`).join('')}</div></details>`;
    const leaders=all.filter(item=>item.value).slice(0,5),topList=all.length>3&&leaders.length>1?`<ol class="provider-top" aria-label="Providers with the most records">${leaders.map(item=>`<li><button data-stats-selection="provider" data-value="${e(item.value)}"><span>${e(item.name)}</span><b>${item.count}</b></button></li>`).join('')}</ol>`:'';
    return {html:svg+topList+directory,note:'Area shows share of selected records. Click a provider to explore its support.'};
  }
  function communityChart(counts,total,state){
    const colors=['#648852','#92ac75','#c0a17b'];
    return `<div class="community-radials">${communities.map((name,index)=>{const count=counts[name]||0,share=pct(count,total),circumference=2*Math.PI*34,tip=`${name} · ${count} of ${total} selected records (${share}%)`;return `<button class="radial-card" data-stats-selection="community" data-value="${e(name)}" data-chart-tip="${e(tip)}" aria-label="Filter ${e(tip)}" aria-pressed="${selected(state.community,name)}"><span class="radial-graphic"><svg viewBox="0 0 84 84" aria-hidden="true"><circle cx="42" cy="42" r="34" fill="none" stroke="#edf1e7" stroke-width="7"/><circle cx="42" cy="42" r="34" fill="none" stroke="${colors[index]}" stroke-width="7" stroke-dasharray="${total?count/total*circumference:0} ${circumference}" transform="rotate(-90 42 42)"/></svg><strong>${share}<small>%</small></strong></span><span class="radial-name">${e(name)}</span><span class="radial-count">${count} records</span></button>`;}).join('')}</div>`;
  }
  function timingChart(counts){
    const entries=Object.entries(counts).filter(([,count])=>count>0).map(([value,count])=>({value,count,label:timingLabels[value]||'Other timing',color:timingColors[value]||timingColors.other}));
    const layout=waffle(entries);if(!layout.total)return empty('No application timing records','Try a broader selection.');
    const cells=layout.entries.flatMap(entry=>Array.from({length:entry.tiles},()=>`<button class="waffle-tile" tabindex="-1" data-stats-selection="deadline" data-value="${e(entry.value)}" data-chart-tip="${e(entry.label)} · ${entry.count} records (${pct(entry.count,layout.total)}%)" aria-label="Filter ${e(entry.label)}" style="--tile-fill:${entry.color}"></button>`)).join('');
    return `<div class="waffle-layout"><div><div class="waffle-grid ${layout.tiles<=16?'waffle-small':''}" aria-label="Application timing proportions">${cells}</div><span class="waffle-unit">${layout.total<=100?'1 tile = 1 record':'1 tile ≈ 1% of records'}</span></div><div class="waffle-legend">${layout.entries.map(entry=>`<button data-stats-selection="deadline" data-value="${e(entry.value)}" aria-label="Filter ${e(entry.label)}: ${entry.count} records"><i style="background:${entry.color}"></i><span>${e(entry.label)}<small>${pct(entry.count,layout.total)}%</small></span><b>${entry.count}</b></button>`).join('')}</div></div>`;
  }
  root.FundingCharts={amountObservations,quantile,cumulative,density,coverage,providers,treemap,waffle,amountChart,heatmap,providerChart,communityChart,timingChart};
})(globalThis);
