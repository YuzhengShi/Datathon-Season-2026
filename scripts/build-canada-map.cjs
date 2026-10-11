/* Mechanical derivation of a small, self-hosted map asset from Natural Earth.
 * Usage: node scripts/build-canada-map.cjs /absolute/path/to/ne_50m_admin_1_states_provinces.geojson
 * Natural Earth geographic data is public domain. Lambert conformal conic: 49°,77°; origin 96°W.
 */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const features=input.features.filter(f=>f.properties.admin==='Canada');
if(features.length!==13)throw new Error('Expected 13 Canadian provinces and territories');
const rad=x=>x*Math.PI/180;
const p1=rad(49),p2=rad(77),n=Math.log(Math.cos(p1)/Math.cos(p2))/Math.log(Math.tan(Math.PI/4+p2/2)/Math.tan(Math.PI/4+p1/2));
const F=Math.cos(p1)*Math.pow(Math.tan(Math.PI/4+p1/2),n)/n;
function project([lon,lat]){const rho=F/Math.pow(Math.tan(Math.PI/4+rad(lat)/2),n),theta=n*rad(lon+96);return [rho*Math.sin(theta),-rho*Math.cos(theta)];}
const polygons=features.map(f=>({code:f.properties.postal,name:f.properties.name,rings:(f.geometry.type==='MultiPolygon'?f.geometry.coordinates:f.geometry.coordinates.map(x=>[x])).flat().map(r=>r.map(project)),label:project([f.properties.longitude,f.properties.latitude])}));
const all=polygons.flatMap(p=>p.rings.flat()),xs=all.map(p=>p[0]),ys=all.map(p=>p[1]);
const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
const scale=Math.min(592/(xmax-xmin),492/(ymax-ymin));
const fit=p=>[14+(p[0]-xmin)*scale,14+(p[1]-ymin)*scale].map(x=>Math.round(x*10)/10);
const out={viewBox:'0 0 620 520',source:'Natural Earth 1:50m admin-1, public domain',projection:'Lambert conformal conic',regions:polygons.map(p=>({code:p.code,name:p.name,label:fit(p.label),path:p.rings.map(r=>'M'+r.map(fit).map(x=>x.join(',')).join('L')+'Z').join('')}))};
fs.mkdirSync(path.join(__dirname,'../dist/data'),{recursive:true});
fs.writeFileSync(path.join(__dirname,'../dist/data/canada-map.json'),JSON.stringify(out));
console.log(JSON.stringify({regions:out.regions.length,bytes:Buffer.byteLength(JSON.stringify(out)),source:out.source}));
