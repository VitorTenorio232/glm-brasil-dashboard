// Flash View V8.3 — lógica temporal do Folium + câmera estável MapLibre.
// Uma camada GLM: clusters multicoloridos (não há círculos vermelhos cobrindo os demais).
// Em zoom maior: símbolos de raios individuais com a cor do intervalo temporal.
const INSTANCES = new WeakMap();
const ASSET_VERSION = '5.7.0';
let loadingPromise;

function loadLibrary() {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  if (loadingPromise) return loadingPromise;
  loadingPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-fv-maplibre-css]')) {
      const css = document.createElement('link');
      css.rel = 'stylesheet'; css.dataset.fvMaplibreCss = '1';
      css.href = `https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/${ASSET_VERSION}/maplibre-gl.css`;
      document.head.appendChild(css);
    }
    const script = document.createElement('script');
    script.src = `https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/${ASSET_VERSION}/maplibre-gl.min.js`;
    script.async = true;
    script.onload = () => window.maplibregl ? resolve(window.maplibregl) : reject(new Error('MapLibre não carregou'));
    script.onerror = () => reject(new Error('Não foi possível carregar MapLibre do CDN'));
    document.head.appendChild(script);
  }).catch(err => {loadingPromise = undefined;throw err;});
  return loadingPromise;
}

const emptyCollection = () => ({type:'FeatureCollection',features:[]});
const SATELLITE = {
  version:8,
  sources:{
    satellite:{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,attribution:'Imagery © Esri, Maxar, Earthstar Geographics'},
    labels:{type:'raster',tiles:['https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],tileSize:256,attribution:'Reference © Esri'}
  },
  layers:[{id:'satellite',type:'raster',source:'satellite'}, {id:'place-labels',type:'raster',source:'labels'}]
};
const STORAGE_KEY = 'fv_maplibre_camera_v8'; // mantém a câmera de V8.2.
const defaultCamera = {center:[-60,-15],zoom:3};
const safely = (fn,fallback) => {try {return fn();} catch {return fallback;}};
function cameraFromStorage(){
  const parsed=safely(()=>JSON.parse(sessionStorage.getItem(STORAGE_KEY)),null);
  if(!parsed||!Array.isArray(parsed.center)||parsed.center.length!==2)return defaultCamera;
  const [lng,lat]=parsed.center.map(Number),zoom=Number(parsed.zoom);
  if(![lng,lat,zoom].every(Number.isFinite)||Math.abs(lat)>85||Math.abs(lng)>180||zoom<0||zoom>19)return defaultCamera;
  return {center:[lng,lat],zoom};
}

export const AGE_BANDS = [
  {min:0,max:5,color:'#ff2d20',label:'0–5 min'},
  {min:5,max:10,color:'#f4b942',label:'5–10 min'},
  {min:10,max:20,color:'#24c96b',label:'10–20 min'},
  {min:20,max:30,color:'#1787ff',label:'20–30 min'}
];

// 13 pontos = 12 intervalos de 5 minutos = uma hora EXATA.
// Quadro 0: horário de referência -60 min. Quadro 12: horário mais recente.
export function frameEndMs(anchor, live, frame){
  if(live)return Number(anchor);
  const idx=Math.max(0,Math.min(12,Math.trunc(Number(frame)||0)));
  return Number(anchor)-(12-idx)*5*60000;
}

// Sempre uma janela de 30 min RELATIVA ao instante selecionado na barra.
// Exemplo: em -60 min, vermelho significa flashes de -65 a -60 min,
// amarelo de -70 a -65; verde -80 a -70; azul -90 a -80.
export function timelineFeatureCollection(points,anchor,live,frame){
  const end=frameEndMs(anchor,live,frame);
  const features=[];
  if(!Number.isFinite(end))return {type:'FeatureCollection',features};
  for(const p of points||[]){
    if(!Array.isArray(p)||p.length<3)continue;
    const lon=Number(p[0]),lat=Number(p[1]),t=Number(p[2]);
    if(![lon,lat,t].every(Number.isFinite)||Math.abs(lat)>85||Math.abs(lon)>180)continue;
    const age=(end-t)/60000;
    if(age<0||age>=30)continue;
    const band=age<5?0:age<10?1:age<20?2:3;
    features.push({type:'Feature',geometry:{type:'Point',coordinates:[lon,lat]},
      properties:{band,color:AGE_BANDS[band].color,age:Math.round(age*10)/10,time:new Date(t).toISOString()}});
  }
  return {type:'FeatureCollection',features};
}

// Facilita testes de regressão da classificação temporal.
export function bandCounts(fc){
  const counts=[0,0,0,0];
  for(const f of fc.features||[])if(Number.isInteger(f.properties.band)&&f.properties.band>=0&&f.properties.band<=3)counts[f.properties.band]++;
  return counts;
}

// Cada flash é representado por um pequeno raio colorido, gerado localmente.
// Sem imagens externas ou glyphs de servidores de fonte.
function boltImage(color){
  const canvas=document.createElement('canvas');canvas.width=38;canvas.height=52;
  const ctx=canvas.getContext('2d');
  ctx.beginPath();
  ctx.moveTo(22,2);ctx.lineTo(7,29);ctx.lineTo(17,29);
  ctx.lineTo(12,50);ctx.lineTo(32,19);ctx.lineTo(22,19);
  ctx.lineTo(30,2);ctx.closePath();
  ctx.lineJoin='round';ctx.lineWidth=3;
  ctx.strokeStyle='#071522';ctx.stroke();
  ctx.fillStyle=color;ctx.fill();
  return ctx.getImageData(0,0,canvas.width,canvas.height);
}

// Donut com 4 fatias: evita o antigo problema de quatro clusters
// exatamente sobrepostos, com a camada vermelha escondendo as demais.
export function clusterStops(counts){
  const n=counts.reduce((sum,x)=>sum+(Number(x)||0),0);
  if(!n)return 'conic-gradient(#64748b 0% 100%)';
  let cursor=0;const parts=[];
  for(let idx=0;idx<4;idx++){
    const next=cursor+(Number(counts[idx])||0)/n*100;
    if(next>cursor)parts.push(`${AGE_BANDS[idx].color} ${cursor.toFixed(4)}% ${next.toFixed(4)}%`);
    cursor=next;
  }
  return `conic-gradient(${parts.join(',')})`;
}
function clusterElement(props, selectionActive, onExpand){
  const counts=[0,1,2,3].map(i=>Math.max(0,Number(props[`age${i}`])||0));
  const total=counts.reduce((a,b)=>a+b,0);
  const size=total>=1000?62:total>=100?53:total>=20?46:38;
  const el=document.createElement('div');
  el.className='fv-cluster-donut';el.style.width=`${size}px`;el.style.height=`${size}px`;
  el.style.background=clusterStops(counts);
  el.title=`${total.toLocaleString('pt-BR')} flashes: `+counts.map((n,i)=>`${AGE_BANDS[i].label} ${n}`).join(' · ');
  const inner=document.createElement('span');inner.className='fv-cluster-donut-inner';
  inner.style.width=`${Math.round(size*.58)}px`;inner.style.height=inner.style.width;
  inner.style.fontSize=total>=10000?'10px':'12px';inner.textContent=total>=1000?(total/1000).toFixed(1).replace('.0','')+'k':String(total);
  el.appendChild(inner);
  // Não interferir na seleção retangular enquanto estiver ativa.
  el.addEventListener('click',e=>{if(selectionActive())return;e.stopPropagation();onExpand();});
  return el;
}

function setGeoJSON(map,id,geojson){
  if(!map||!map.isStyleLoaded())return;
  const source=map.getSource(id);
  if(source)source.setData(geojson||emptyCollection());
}

function initInstance(component){
  const root=component.parentElement.querySelector('.fv-map-shell');
  const canvas=root.querySelector('.fv-map-canvas');
  const loading=root.querySelector('.fv-map-loading');
  const label=root.querySelector('.fv-map-frame-label');
  const range=root.querySelector('[data-role="frame"]');
  const speed=root.querySelector('[data-role="speed"]');
  const controls=root.querySelector('.fv-map-controls');
  const hud=root.querySelector('.fv-map-hud');
  range.max='12';range.value='12';
  const i={root,canvas,loading,label,range,speed,controls,hud,map:null,ready:false,disposed:false,
    points:[],anchor:0,selection:null,overlay:null,selecting:false,corner:null,
    frame:12,live:true,playing:false,timer:null,resizeObserver:null,raf:null,
    clusterMarkers:new Map(),lastCount:0};

  function stopTimer(){if(i.timer!==null){clearInterval(i.timer);i.timer=null;}}
  function notifyStatus(){
    range.value=String(i.frame);
    const end=frameEndMs(i.anchor,i.live,i.frame);
    const utc=(ms)=>Number.isFinite(ms)?new Date(ms).toISOString().slice(11,16):'--:--';
    label.textContent=i.live?`● AO VIVO · ${utc(end)} UTC`:`${i.frame+1}/13 · ${utc(end-30*60000)}–${utc(end)} UTC`;
    hud.textContent=`GLM · NOAA · ${i.lastCount.toLocaleString('pt-BR')} flashes exibidos · janela 30 min`;
    const btn=root.querySelector('[data-act="play"]');
    if(btn)btn.textContent=i.playing?'⏸ Pausar':'▶ Reproduzir';
  }
  function scheduleClusters(){
    if(i.raf!==null||!i.ready||i.disposed)return;
    i.raf=requestAnimationFrame(()=>{i.raf=null;updateClusters();});
  }
  function clearClusterMarkers(){
    for(const entry of i.clusterMarkers.values())entry.marker.remove();
    i.clusterMarkers.clear();
  }
  function updateClusters(){
    if(!i.ready||i.disposed)return;
    const map=i.map;
    if(map.getZoom()>=8||!map.getSource('fv-flashes')){clearClusterMarkers();return;}
    const points=safely(()=>map.querySourceFeatures('fv-flashes'),[]);
    const next=new Set();
    const w=canvas.clientWidth,h=canvas.clientHeight;
    let placed=0;
    for(const f of points){
      if(!f.properties?.cluster||!Array.isArray(f.geometry?.coordinates))continue;
      const id=String(f.properties.cluster_id);
      if(next.has(id))continue; // tiles podem repetir o mesmo cluster
      const xy=map.project(f.geometry.coordinates);
      if(xy.x < -60||xy.x>w+60||xy.y < -60||xy.y>h+60)continue;
      if(placed++>=400)break; // limite DOM; não limita os flashes da fonte
      next.add(id);
      const props=f.properties;
      const signature=[props.point_count,props.age0,props.age1,props.age2,props.age3].join('/');
      let entry=i.clusterMarkers.get(id);
      if(entry&&entry.signature!==signature){entry.marker.remove();i.clusterMarkers.delete(id);entry=null;}
      if(!entry){
        const coords=f.geometry.coordinates;
        const el=clusterElement(props,()=>i.selecting,()=>{
          const source=map.getSource('fv-flashes');
          Promise.resolve(source.getClusterExpansionZoom(Number(props.cluster_id))).then(z=>{
            if(!i.disposed&&Number.isFinite(z))map.easeTo({center:coords,zoom:z});
          }).catch(()=>{});
        });
        const marker=new i.lib.Marker({element:el,anchor:'center'}).setLngLat(coords).addTo(map);
        entry={marker,signature};i.clusterMarkers.set(id,entry);
      }
    }
    for(const [id,entry] of i.clusterMarkers.entries()){
      if(!next.has(id)){entry.marker.remove();i.clusterMarkers.delete(id);}
    }
  }
  function draw(){
    const fc=timelineFeatureCollection(i.points,i.anchor,i.live,i.frame);
    i.lastCount=fc.features.length;
    if(i.ready){
      // Alterar apenas os dados, sem map.remove(), setStyle(), flyTo() nem jumpTo().
      clearClusterMarkers();
      setGeoJSON(i.map,'fv-flashes',fc);
    }
    notifyStatus();
  }
  function doTick(){i.live=false;i.frame=(i.frame+1)%13;draw();}
  function start(){stopTimer();i.live=false;i.playing=true;draw();i.timer=setInterval(doTick,Number(speed.value)||2000);}
  function activate(action){
    if(action==='play'){if(i.playing){i.playing=false;stopTimer();draw();}else start();}
    else if(action==='live'){i.playing=false;stopTimer();i.live=true;i.frame=12;draw();}
    else if(action==='prev'||action==='next'){
      i.playing=false;stopTimer();i.live=false;i.frame=(i.frame+(action==='prev'?12:1))%13;draw();
    }
  }
  const onControlClick=e=>{const b=e.target.closest('button[data-act]');if(b)activate(b.dataset.act);};
  const onRangeInput=()=>{i.playing=false;stopTimer();i.live=false;i.frame=Number(range.value);draw();};
  const onSpeedChange=()=>{if(i.playing)start();};
  controls.addEventListener('click',onControlClick);
  range.addEventListener('input',onRangeInput);
  speed.addEventListener('change',onSpeedChange);

  i.update=(data,setter)=>{
    i.rectangleCallback=setter;
    i.points=Array.isArray(data?.points)?data.points:[];
    i.anchor=Number(data?.observation_end_ms)||Date.now();
    i.selection=data?.selection||null;i.overlay=data?.overlay||null;i.selecting=!!data?.selecting;
    root.classList.toggle('fv-map-drawing',i.selecting);
    if(!i.selecting)i.corner=null;
    draw();
    if(i.ready){setGeoJSON(i.map,'fv-selected',i.selection);setGeoJSON(i.map,'fv-imported',i.overlay);}
  };
  i.dispose=()=>{
    i.disposed=true;stopTimer();
    if(i.raf!==null)cancelAnimationFrame(i.raf);
    clearClusterMarkers();
    controls.removeEventListener('click',onControlClick);
    range.removeEventListener('input',onRangeInput);
    speed.removeEventListener('change',onSpeedChange);
    if(i.resizeObserver)i.resizeObserver.disconnect();
    if(i.map){i.map.remove();i.map=null;}
  };

  loadLibrary().then(lib=>{
    if(i.disposed)return;
    i.lib=lib;
    const camera=cameraFromStorage();
    if(typeof lib.supported==='function'&&!lib.supported()){
      loading.textContent='WebGL indisponível neste navegador. Ative a aceleração gráfica.';return;
    }
    const map=new lib.Map({container:canvas,style:SATELLITE,center:camera.center,zoom:camera.zoom,maxZoom:19,minZoom:1,attributionControl:false});
    i.map=map;
    map.addControl(new lib.NavigationControl({visualizePitch:false}),'top-right');
    map.addControl(new lib.AttributionControl({compact:true}),'bottom-right');
    map.on('moveend',()=>{
      const c=map.getCenter();
      safely(()=>sessionStorage.setItem(STORAGE_KEY,JSON.stringify({center:[c.lng,c.lat],zoom:map.getZoom()})),null);
      scheduleClusters();
      // Não enviar centro/zoom ao Python. Assim o zoom não some ao atualizar GLM.
    });
    map.on('move',scheduleClusters);
    map.on('click',e=>{
      if(!i.selecting)return;
      const {lng,lat}=e.lngLat;
      if(!i.corner){i.corner={lng,lat};hud.textContent='Seleção: clique no canto oposto do retângulo';return;}
      const west=Math.min(i.corner.lng,lng),east=Math.max(i.corner.lng,lng),south=Math.min(i.corner.lat,lat),north=Math.max(i.corner.lat,lat);
      i.corner=null;
      if(east-west<.0001||north-south<.0001)return;
      if(i.rectangleCallback)i.rectangleCallback('rectangle',{west,south,east,north});
    });
    map.on('load',()=>{
      if(i.disposed)return;
      // Uma única fonte para TODOS os intervalos. A composição dos clusters
      // respeita os quatro totais e não destaca artificialmente o vermelho.
      const props={};
      for(let n=0;n<4;n++)props[`age${n}`]=['+',['case',['==',['get','band'],n],1,0]];
      map.addSource('fv-flashes',{type:'geojson',data:emptyCollection(),cluster:true,clusterMaxZoom:7,clusterRadius:45,clusterProperties:props});
      for(let n=0;n<4;n++)map.addImage(`fv-bolt-${n}`,boltImage(AGE_BANDS[n].color),{pixelRatio:2});
      map.addLayer({id:'fv-bolts',type:'symbol',source:'fv-flashes',filter:['!', ['has','point_count']],
        layout:{'icon-image':['concat','fv-bolt-',['to-string',['get','band']]],
          'icon-size':['interpolate',['linear'],['zoom'],2,0.8,8,1.05,12,1.35],
          'icon-allow-overlap':true,'icon-ignore-placement':true},
        paint:{'icon-opacity':0.96}});
      map.on('click','fv-bolts',e=>{
        if(i.selecting||!e.features?.length)return;
        const f=e.features[0],p=f.properties;
        const band=AGE_BANDS[Number(p.band)]||AGE_BANDS[0];
        new lib.Popup({closeButton:false,offset:12}).setLngLat(e.lngLat).setText(
          `Flash GLM · ${band.label} · ${new Date(p.time).toISOString().slice(0,19).replace('T',' ')} UTC`).addTo(map);
      });
      map.on('mouseenter','fv-bolts',()=>{if(!i.selecting)map.getCanvas().style.cursor='pointer';});
      map.on('mouseleave','fv-bolts',()=>{map.getCanvas().style.cursor='';});
      map.addSource('fv-selected',{type:'geojson',data:emptyCollection()});
      map.addLayer({id:'fv-selected-fill',type:'fill',source:'fv-selected',paint:{'fill-color':'#ffdc4a','fill-opacity':.11}});
      map.addLayer({id:'fv-selected-line',type:'line',source:'fv-selected',paint:{'line-color':'#ffe359','line-width':2.5}});
      map.addSource('fv-imported',{type:'geojson',data:emptyCollection()});
      map.addLayer({id:'fv-imported-fill',type:'fill',source:'fv-imported',paint:{'fill-color':'#15dbf0','fill-opacity':.1}});
      map.addLayer({id:'fv-imported-line',type:'line',source:'fv-imported',paint:{'line-color':'#15dbf0','line-width':2}});
      map.on('sourcedata',e=>{if(e.sourceId==='fv-flashes'&&e.isSourceLoaded)scheduleClusters();});
      i.ready=true;loading.dataset.hidden='true';
      i.update({points:i.points,observation_end_ms:i.anchor,selection:i.selection,overlay:i.overlay,selecting:i.selecting},i.rectangleCallback);
    });
    map.on('error',()=>{
      if(!i.ready&&!i.disposed)loading.textContent='O mapa de satélite não carregou. Verifique conexão e acesso ao serviço de mapas.';
    });
    i.resizeObserver=new ResizeObserver(()=>{if(i.map&&!i.disposed)i.map.resize();});
    i.resizeObserver.observe(canvas);
  }).catch(err=>{if(!i.disposed)loading.textContent=`Erro MapLibre: ${err.message}`;});
  return i;
}

export default function(component){
  const parent=component.parentElement;
  let instance=INSTANCES.get(parent);
  if(!instance){instance=initInstance(component);INSTANCES.set(parent,instance);}
  instance.update(component.data,(name,value)=>component.setTriggerValue(name,value));
  return ()=>{instance.dispose();INSTANCES.delete(parent);};
}
