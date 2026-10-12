'use strict';
const assert=require('node:assert/strict');
require('../dist/charts.js');
const c=globalThis.FundingCharts;
let passed=0;
function check(name,fn){fn();passed++;}
const record=(id,amount,extra={})=>({id,title:id,amount,provider:'Provider '+id,type:'Scholarship',province:'all',community:['Métis'],amount_details:{currency:'CAD',kind:'fixed'},...extra});
check('Unknown, negative, pooled and foreign amounts are excluded',()=>{
  const rows=[record('zero',0),record('a','5000'),record('unknown',null),record('negative',-1),record('pool',20000,{amount_details:{kind:'pooled_total',currency:'CAD'}}),record('foreign',99,{amount_details:{kind:'fixed',currency:'USD'}}),record('bad','not a number')];
  assert.deepEqual(c.amountObservations(rows).map(x=>x.value),[0,5000]);
});
check('Median and empty quantiles remain well-defined',()=>{assert.equal(c.quantile([5000,53000],.5),29000);assert.equal(c.quantile([], .5),null);assert.equal(c.quantile([7], .5),7);});
check('Empirical distribution combines repeated figures',()=>{const result=c.cumulative(c.amountObservations([record('a',5000),record('b',5000),record('c',10000)]));assert.equal(result.length,2);assert.equal(result[0].cumulative,2);assert.equal(result[0].share,2/3);assert.equal(result[1].share,1);});
check('KDE handles repeated and zero figures with positive finite bandwidth',()=>{for(const values of [[0,0],[5000,5000,5000],[1,100000]]){const estimate=c.density(c.amountObservations(values.map((v,i)=>record(String(i),v))),150000);assert.ok(estimate.bandwidth>0&&Number.isFinite(estimate.bandwidth));assert.ok(estimate.points.every(x=>Number.isFinite(x.concentration)&&x.concentration>=0));}assert.equal(c.density([record('a',1)],5000),null);});
check('National coverage is counted once in each heatmap cell',()=>{const matrix=c.coverage([record('all',5000),record('bc',1000,{province:'British Columbia'})],{BC:'British Columbia',ON:'Ontario'});assert.deepEqual(matrix.map(x=>x.counts),[[0,0,2],[0,0,1]]);});
check('Treemap conserves area, proportions and bounds',()=>{const entries=[{name:'A',count:10},{name:'B',count:6},{name:'C',count:3},{name:'D',count:1}],rects=c.treemap(entries,420,260);assert.equal(rects.length,4);const area=420*260;for(const rect of rects){assert.ok(rect.w>0&&rect.h>0);assert.ok(rect.x>=0&&rect.y>=0&&rect.x+rect.w<=420+1e-8&&rect.y+rect.h<=260+1e-8);assert.ok(Math.abs(rect.w*rect.h/area-rect.count/20)<1e-10);}assert.ok(Math.abs(rects.reduce((s,x)=>s+x.w*x.h,0)-area)<1e-8);});
check('Waffle represents small selections exactly and rounds larger ones to 100',()=>{const small=c.waffle([{count:3},{count:1}]);assert.deepEqual(small.entries.map(x=>x.tiles),[3,1]);const large=c.waffle([{count:27},{count:1},{count:3},{count:1},{count:497}]);assert.equal(large.total,529);assert.equal(large.entries.reduce((s,x)=>s+x.tiles,0),100);assert.ok(large.entries.every(x=>Math.abs(x.tiles-x.count/529*100)<=1));assert.equal(c.waffle([]).tiles,0);});
check('User-controlled labels cannot inject SVG markup',()=>{const malicious=record('a',10,{title:'<script>alert(1)</script>',provider:'<img src=x onerror=alert(1)>'});const amount=c.amountChart([malicious],'dots').html,provider=c.providerChart([malicious]).html;assert.ok(!amount.includes('<script>'));assert.ok(!provider.includes('<img'));assert.ok(provider.includes('&lt;img'));});
check('Empty and single-value charts never emit NaN',()=>{for(const rows of [[],[record('a',0)],[record('b',1000)]])for(const view of ['curve','share','dots']){const chart=c.amountChart(rows,view);assert.ok(!/NaN|Infinity/.test(chart.html));}});
check('Every deadline kind the data can carry has its own label and colour',()=>{const known=c.timingChart({date:1,annual_rule:27,rolling:1,local_administrator:3,unspecified:497});assert.ok(known.includes('Every year')&&known.includes('Rolling intake')&&!known.includes('Other timing'));assert.ok(c.timingChart({mystery:2}).includes('Other timing'));});
console.log(JSON.stringify({passed,verification:'Chart computation and statistical invariants'}));
