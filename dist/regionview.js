/* Draws the province and territory part of the Statistics page: the map (north up), the equal-size tile map, the colour
   scale, the card of the selected region, the ranking of every region and the accessible table. The numbers come from
   regions.js; this file only turns them into markup. Clicks are handled by insights.js through data-region attributes. */
(function(root){
  'use strict';
  const SOURCE_COLORS={verified:'#5b8f45',directory:'#cdb892'};
  /* Prince Edward Island, Nova Scotia and New Brunswick are too small to carry a label: they get a chip in the Atlantic. */
  const CHIPS={NB:482,NS:534,PE:586},CHIP_Y=452;

  function init(ctx){
    const {$,icon,e,regions,amountText}=ctx;
    const money=value=>amountText({amount:value});
    const plural=(n,word)=>`${n} ${word}${n===1?'':'s'}`;
    let latest=null;

    function tipHTML(r){
      return `<strong>${e(r.name)}</strong><span>${plural(r.regional,'region-specific record')}</span><span>+ ${r.nationwide} nationwide</span><span>${r.verified} provider page${r.verified===1?'':'s'} · ${r.directory} federal directory</span>`;
    }
    function card(r,leading,mapMode){
      const metric=mapMode==='regional'?r.regional:r.reach;
      const community=Object.entries(r.community).sort((a,b)=>b[1]-a[1]||(a[0]<b[0]?-1:1)).map(([name,count])=>`${e(name)} ${count}`).join(' · ')||'None';
      const figures=r.listed?`${r.listed} of ${r.regional} · ${r.lowest===r.highest?money(r.highest):`${money(r.lowest)} to ${money(r.highest)}`}`:'None listed';
      const providers=r.providers.length?r.providers.map(p=>`${e(p.name)} (${p.count})`).join(', ')+(r.providerCount>r.providers.length?` and ${r.providerCount-r.providers.length} more`:''):'None';
      const years=r.oldest===null?'Not stated':r.oldest===r.newest?String(r.oldest):`${r.oldest}–${r.newest}`;
      const share=r.regional?Math.round(r.verified/r.regional*100):0;
      return `<p class="region-insight-label">${leading?'Largest regional coverage':'Selected region'}</p><h3 class="region-insight-name">${e(r.name)}</h3><div class="region-insight-value">${metric}</div><p class="region-insight-small">${mapMode==='regional'?'region-specific records':'records that reach it'}<br>${plural(r.nationwide,'nationwide record')} also apply</p>${
        r.regional?`<div class="source-split" role="img" aria-label="${r.verified} from provider pages, ${r.directory} from the federal directory"><i class="is-verified" style="width:${share}%"></i><i class="is-directory" style="width:${100-share}%"></i></div><p class="source-split-note">${r.verified} provider page${r.verified===1?'':'s'} · ${r.directory} federal directory</p>`:'<p class="region-empty">No region-specific records in this selection.</p>'
      }<dl class="region-facts"><div><dt>Communities</dt><dd>${community}</dd></div><div><dt>Listed figures</dt><dd>${figures}</dd></div><div><dt>Main providers</dt><dd>${providers}</dd></div><div><dt>Source pages last changed</dt><dd>${years}</dd></div></dl><button class="text-link region-explore" data-explore-region="${e(r.name)}">Explore these records ${icon('arrow')}</button>`;
    }
    function svgMap(summary,geometry,metric,scale,selected){
      const byCode=Object.fromEntries(summary.regions.map(r=>[r.code,r]));
      const light=r=>scale.classOf(r[metric])>=4;
      const named=geometry.regions.filter(x=>!(x.code in CHIPS));
      const chips=Object.keys(CHIPS).map(code=>geometry.regions.find(x=>x.code===code)).filter(Boolean);
      const leaders=chips.map(x=>`<line class="map-leader" x1="${x.label[0]}" y1="${x.label[1]}" x2="${CHIPS[x.code]}" y2="${CHIP_Y}"/>`).join('');
      const paths=geometry.regions.map(region=>{
        const r=byCode[region.code],name=regions[region.code],on=selected.includes(name);
        return `<path d="${region.path}" fill="${scale.color(scale.classOf(r[metric]))}" class="${on?'is-selected':''}" tabindex="0" role="button" aria-pressed="${on}" data-region="${region.code}" aria-label="${e(name)}: ${r.regional} regional, ${r.nationwide} nationwide records"></path>`;
      }).join('');
      const labels=named.map(x=>{const r=byCode[x.code];return `<text class="map-label${light(r)?' is-light':''}" x="${x.label[0]}" y="${x.label[1]-1}" text-anchor="middle"><tspan>${x.code}</tspan><tspan class="map-count" x="${x.label[0]}" dy="12">${r[metric]}</tspan></text>`;}).join('');
      const chipMarkup=chips.map(x=>{
        const r=byCode[x.code],cx=CHIPS[x.code],on=selected.includes(regions[x.code]);
        return `<g class="map-chip${on?' is-selected':''}" tabindex="0" role="button" aria-pressed="${on}" data-region="${x.code}" aria-label="${e(regions[x.code])}: ${r.regional} regional, ${r.nationwide} nationwide records"><rect x="${cx-23}" y="${CHIP_Y}" width="46" height="24" rx="6" fill="${scale.color(scale.classOf(r[metric]))}"/><text class="map-chip-text${light(r)?' is-light':''}" x="${cx}" y="${CHIP_Y+16}" text-anchor="middle">${x.code} ${r[metric]}</text></g>`;
      }).join('');
      return `<svg viewBox="${geometry.viewBox}" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="Canadian provinces and territories, north at the top. Press a region to filter the dataset.">${leaders}${paths}${labels}${chipMarkup}</svg>`;
    }
    function tiles(summary,metric,scale,selected){
      const cells=summary.regions.map(r=>{
        const [column,row]=root.FundingRegions.TILES[r.code],cls=scale.classOf(r[metric]),on=selected.includes(r.name);
        return `<button class="tile${cls>=4?' is-light':''}${on?' is-selected':''}" style="grid-column:${column};grid-row:${row};background:${scale.color(cls)}" data-region="${r.code}" aria-pressed="${on}" aria-label="${e(r.name)}: ${r.regional} regional, ${r.nationwide} nationwide records"><b>${r.code}</b><span>${r[metric]}</span><small>${e(r.name)}</small></button>`;
      }).join('');
      return `<div class="tile-grid" role="group" aria-label="Provinces and territories as equal-size tiles">${cells}</div>`;
    }
    function ranking(summary,selected){
      const max=Math.max(1,...summary.regions.map(r=>r.regional));
      const ordered=summary.regions.slice().sort((a,b)=>b.regional-a.regional||(a.name<b.name?-1:1));
      const rows=ordered.map(r=>{
        const share=r.regional?r.verified/r.regional*100:0,on=selected.includes(r.name);
        return `<li><button data-region="${r.code}" class="${on?'is-selected':''}${r.regional===0?' is-empty':''}" aria-label="${e(r.name)}: ${r.regional} region-specific records, ${r.nationwide} nationwide"><span class="rank-name">${e(r.name)}</span><span class="rank-bar"><span class="rank-fill" style="width:${r.regional/max*100}%"><i class="is-verified" style="width:${share}%"></i><i class="is-directory" style="width:${100-share}%"></i></span></span><b>${r.regional}</b></button></li>`;
      }).join('');
      return `<div class="ranking-key"><span><i style="background:${SOURCE_COLORS.verified}"></i>Provider page</span><span><i style="background:${SOURCE_COLORS.directory}"></i>Federal directory</span></div><ol class="ranking-list">${rows}</ol>`;
    }
    function table(summary){
      return `<table><thead><tr><th scope="col">Region</th><th scope="col">Regional</th><th scope="col">Nationwide</th><th scope="col">Unique reach</th><th scope="col">Provider pages</th><th scope="col">Federal directory</th></tr></thead><tbody>${summary.regions.map(r=>`<tr><td><button data-region="${r.code}">${e(r.name)}</button></td><td>${r.regional}</td><td>${r.nationwide}</td><td>${r.reach}</td><td>${r.verified}</td><td>${r.directory}</td></tr>`).join('')}</tbody></table><p>Nationwide records are repeated in every region's reach. Do not sum the reach column.</p>`;
    }
    /* summary: FundingRegions.summarize(...). state: the page's filters. geometry: data/canada-map.json (or null while it loads). */
    function paint({summary,state,geometry,mapMode,mapView}){
      latest=summary;
      const metric=mapMode==='regional'?'regional':'reach';
      const scale=root.FundingRegions.scale(summary.regions.map(r=>r[metric]));
      const selected=Array.isArray(state.location)?state.location:[state.location];
      const empty=summary.regions.filter(r=>r.regional===0).map(r=>r.name);
      $('#map-coverage').innerHTML=`<strong>${summary.covered} of ${summary.regions.length}</strong> provinces and territories have region-specific records in this selection${empty.length?` · none yet: ${e(empty.join(', '))}`:''}.`;
      $('#canada-map').innerHTML=geometry?svgMap(summary,geometry,metric,scale,selected):'<p class="chart-note">Loading the map… The tiles and the table work meanwhile.</p>';
      $('#tile-map').innerHTML=tiles(summary,metric,scale,selected);
      $('#canada-map').hidden=mapView!=='map';
      $('#tile-map').hidden=mapView!=='tiles';
      document.querySelectorAll('[data-map-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mapView===mapView)));
      $('#map-legend').innerHTML=`<span class="legend-title">${mapMode==='regional'?'Region-specific records':'Records that reach the region'}</span><ul>${scale.legend.map(item=>`<li><i style="background:${item.color}"></i>${item.label}</li>`).join('')}</ul>`;
      const chosen=typeof state.location==='string'?summary.regions.find(r=>r.name===state.location):null;
      const leading=summary.regions.slice().sort((a,b)=>b[metric]-a[metric]||(a.name<b.name?-1:1))[0];
      $('#map-region-summary').innerHTML=card(chosen||leading,!chosen,mapMode);
      $('#region-ranking').innerHTML=ranking(summary,selected);
      $('#region-table').innerHTML=table(summary);
    }
    /* A small card that follows the pointer (or the focused region) over the map and the tiles. */
    function wire(){
      const tip=$('#map-tooltip');
      const hide=()=>{tip.hidden=true;};
      const show=(target,event)=>{
        const code=target.closest('[data-region]')?.dataset.region,region=latest?.regions.find(r=>r.code===code);
        if(!region){hide();return;}
        tip.innerHTML=tipHTML(region);tip.hidden=false;
        const stage=tip.parentElement.getBoundingClientRect();
        const box=target.closest('[data-region]').getBoundingClientRect();
        const x=event&&Number.isFinite(event.clientX)?event.clientX:box.left+box.width/2,y=event&&Number.isFinite(event.clientY)?event.clientY:box.top+box.height/2;
        tip.style.left=Math.max(4,Math.min(stage.width-190,x-stage.left+14))+'px';
        tip.style.top=Math.max(4,y-stage.top-10)+'px';
      };
      for(const id of ['#canada-map','#tile-map']){
        const el=$(id);
        el.addEventListener('pointerover',event=>{if(event.target.closest('[data-region]'))show(event.target,event);});
        el.addEventListener('pointermove',event=>{if(!tip.hidden&&event.target.closest('[data-region]'))show(event.target,event);});
        el.addEventListener('pointerleave',hide);
        el.addEventListener('focusin',event=>{if(event.target.closest('[data-region]'))show(event.target,null);});
        el.addEventListener('focusout',hide);
      }
    }
    wire();
    return {paint,regionOf:code=>latest?.regions.find(r=>r.code===code)||null};
  }
  root.FundingRegionView={init,SOURCE_COLORS};
})(globalThis);
