let dailyReportData = null;
let dailySelectedDate = null;
let dailyRequestId = 0;
function dailyEscape(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function dailyHighlighted(v){
  const chars=Array.from(v.excerpt||'');let end=0,html='';
  for(const h of v.highlights||[]){
    if(!Number.isInteger(h.start)||!Number.isInteger(h.end)||h.start<end||h.end<=h.start||h.end>chars.length)continue;
    // Separate glyph boxes prevent html2canvas from stretching wrapped inline marks.
    html+=dailyEscape(chars.slice(end,h.start).join(''))+chars.slice(h.start,h.end).map(c=>'<mark title="'+dailyEscape(h.reason)+'">'+dailyEscape(c)+'</mark>').join('');end=h.end;
  }
  return html+dailyEscape(chars.slice(end).join(''));
}
function dailyPaper(r){
  r={...r,brands:r.brands.map(b=>({...b,reviews:[...b.reviews].sort((a,b)=>Array.from(b.excerpt||'').length-Array.from(a.excerpt||'').length)}))};
  const gen=new Date(r.generated_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false});
  return `<div class="daily-head"><div><div class="daily-eyebrow">DAILY REVIEW BRIEF</div><div class="daily-title">전일 종합</div><div class="daily-date">${dailyEscape(r.date)} · 자사와 경쟁사</div></div><div class="daily-gen">매일 오전 9시 갱신 · 한국시간<br>생성 ${dailyEscape(gen)}</div></div>
  <div class="daily-kpis"><div class="daily-kpi"><strong>${r.total.toLocaleString()}</strong>수집된 전일 후기</div><div class="daily-kpi"><strong>${r.low_count.toLocaleString()}</strong>3점 이하 후기</div><div class="daily-kpi"><strong>${r.selected_count.toLocaleString()}</strong>선정 표시 후기</div></div>
  <div class="daily-notice">${dailyEscape(r.notice)}</div><div class="daily-grid">${r.brands.map(b=>`<section class="daily-card ${b.role==='자사'?'own':''}"><div class="daily-card-head"><div class="daily-brand">${dailyEscape(b.name)}<span class="daily-role">${dailyEscape(b.role)}</span></div><div class="daily-stats"><span>전체 수집 <b>${b.count??'—'}</b></span><span>선정 <b>${b.selected_count}</b></span><span>평점 <b>${b.average===null?'—':b.average.toFixed(2)}</b></span><span>3점 이하 <b>${b.low_count??'—'}</b></span></div></div><div class="daily-coverage">${dailyEscape(b.coverage)}<br>최신 보유 후기: ${dailyEscape(b.latest_review_date||'미확인')}</div>${b.reviews.length?b.reviews.map(v=>`<div class="daily-review"><div class="daily-review-top"><span class="daily-score ${v.score!==null&&v.score<=3?'low':''}">${v.score===null?'평점 미제공':v.score+' / 5'}</span><span>${dailyEscape(({naver:'네이버',direct:'자사몰',kakao:'카카오'})[v.platform]||v.platform)}</span></div><div class="daily-product">${dailyEscape(v.product)}</div><p class="daily-quote">${v.excerpt?dailyHighlighted(v):'본문이 없는 후기입니다.'}</p></div>`).join(''):`<div class="daily-empty">${b.available?'이 날짜에 구체적인 평가 이유가 있는 선정 후기가 없습니다.<br>전체 수집 건수와 수집 상태를 함께 확인해 주세요.':'아직 수집되지 않는 브랜드입니다.<br>후기 0건으로 집계하지 않습니다.'}</div>`}</section>`).join('')}</div><div class="daily-foot">${dailyEscape(r.selection_rule)}<br>${dailyEscape(r.highlight_rule)}<br>백년화편 후기 대시보드 · 본 보고서는 수집 시점의 자료를 보존합니다.</div>`;
}
async function renderDailyReport(selectedDate){
  if(typeof selectedDate==='string')dailySelectedDate=selectedDate;
  const requestId=++dailyRequestId;
  document.title='전일 종합 | 후기 대시보드';
  const mc=document.getElementById('mainContent');
  mc.innerHTML='<div class="daily-tools"><div><h2>전일 종합</h2><p>저장된 보고서를 불러오고 있습니다.</p></div></div>';
  try{
    const query=dailySelectedDate?'?date='+encodeURIComponent(dailySelectedDate):'';
    const response=await fetch('/api/daily-report'+query);
    if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.detail||'보고서를 불러오지 못했습니다.');}
    const r=await response.json();if(currentShop!=='daily'||requestId!==dailyRequestId)return;
    dailyReportData=r;dailySelectedDate=r.date;
    const dates=r.available_dates||[r.date];
    const options=dates.map(d=>`<option value="${dailyEscape(d)}" ${d===r.date?'selected':''}>${dailyEscape(d)}</option>`).join('');
    mc.innerHTML='<div class="daily-tools"><div><h2>전일 종합</h2><p>백년화편·명가삼대떡집 이유 있는 후기 선정 · 글자 수 많은 순 · 본문 전체 표시</p></div><div class="daily-actions"><label for="dailyDate">후기 날짜</label><select id="dailyDate" onchange="renderDailyReport(this.value)">'+options+'</select><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서</button><button class="refresh-btn" id="dailyDownload" onclick="downloadDailyReport()">전체 이미지 저장</button></div></div><p class="daily-archive-note">'+(r.reconstructed?'이전 보고서는 현재 보유한 해당 날짜 원문에서 같은 선정 기준으로 표시합니다.':r.historical?'보관된 과거 원문에 현재와 같은 선정·강조 기준을 적용합니다.':'현재 전일 보고서입니다. 원본 후기는 보존하고 이유 있는 후기만 표시합니다.')+' 저장된 날짜 '+dates.length+'개 · 전체 이미지가 여러 장이면 ZIP 파일로 저장됩니다.</p><div id="dailyPaper" class="daily-paper">'+dailyPaper(r)+'</div>';
  }catch(e){if(currentShop==='daily'&&requestId===dailyRequestId){dailyReportData=null;mc.innerHTML='<div class="card">'+dailyEscape(e.message)+'<br><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서 보기</button></div>';}}
}
// Store PNGs in one ZIP so browsers do not block multiple automatic downloads.
function dailyZip(files){
  const encoder=new TextEncoder(),parts=[],directory=[];let offset=0;
  function crc32(bytes){let crc=0xffffffff;for(const byte of bytes){crc^=byte;for(let j=0;j<8;j++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^0xffffffff)>>>0;}
  for(const file of files){
    const name=encoder.encode(file.name),data=file.data,crc=crc32(data);
    const local=new Uint8Array(30+name.length),lv=new DataView(local.buffer);
    lv.setUint32(0,0x04034b50,true);lv.setUint16(4,20,true);lv.setUint16(6,0x800,true);
    lv.setUint32(14,crc,true);lv.setUint32(18,data.length,true);lv.setUint32(22,data.length,true);lv.setUint16(26,name.length,true);local.set(name,30);
    const central=new Uint8Array(46+name.length),cv=new DataView(central.buffer);
    cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);
    cv.setUint32(16,crc,true);cv.setUint32(20,data.length,true);cv.setUint32(24,data.length,true);cv.setUint16(28,name.length,true);cv.setUint32(42,offset,true);central.set(name,46);
    parts.push(local,data);directory.push(central);offset+=local.length+data.length;
  }
  const size=directory.reduce((n,p)=>n+p.length,0),end=new Uint8Array(22),ev=new DataView(end.buffer);
  ev.setUint32(0,0x06054b50,true);ev.setUint16(8,files.length,true);ev.setUint16(10,files.length,true);ev.setUint32(12,size,true);ev.setUint32(16,offset,true);
  return new Blob([...parts,...directory,end],{type:'application/zip'});
}
function dailyImageSlices(height){
  const result=[];for(let y=0;y<height;y+=4000)result.push({y,height:Math.min(4000,height-y)});return result;
}
async function downloadDailyReport(){
  if(!dailyReportData)return;const exportReport=dailyReportData,button=document.getElementById('dailyDownload');
  if(button.disabled)return;button.disabled=true;button.textContent='전체 이미지 만드는 중…';
  const stage=document.createElement('div');stage.className='daily-paper daily-export';stage.style.cssText='position:absolute;left:-12000px;top:0;';
  let url;
  try{
    stage.innerHTML=dailyPaper(exportReport);document.body.appendChild(stage);await document.fonts.ready;
    if(typeof html2canvas!=='function')throw new Error('이미지 저장 모듈을 불러오지 못했습니다. 페이지를 새로고침해 주세요.');
    const slices=dailyImageSlices(Math.ceil(stage.getBoundingClientRect().height)),files=[];
    for(let i=0;i<slices.length;i++){
      button.textContent=`전체 이미지 ${i+1}/${slices.length}장 생성 중…`;
      const canvas=await html2canvas(stage,{scale:1,backgroundColor:'#f6f4ed',logging:false,windowWidth:1200,width:1040,height:slices[i].height,y:slices[i].y});
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      canvas.width=canvas.height=0;
      if(!blob)throw new Error('이미지 생성에 실패했습니다. 다시 시도해 주세요.');
      files.push({name:`daily_${exportReport.date}_${String(i+1).padStart(3,'0')}.png`,data:new Uint8Array(await blob.arrayBuffer())});
    }
    const multiple=files.length>1,blob=multiple?dailyZip(files):new Blob([files[0].data],{type:'image/png'});
    url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`전일종합_${exportReport.date}_전체.${multiple?'zip':'png'}`;
    document.body.appendChild(a);a.click();a.remove();
  }catch(e){alert(e.message);}finally{if(url)setTimeout(()=>URL.revokeObjectURL(url),60000);stage.remove();button.disabled=false;button.textContent='전체 이미지 저장';}
}

window.addEventListener('DOMContentLoaded',()=>{if(location.hash==='#daily'){const tab=document.getElementById('dailyReportTab');if(tab)switchShop('daily',tab);}});
