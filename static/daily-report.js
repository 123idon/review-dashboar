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
function dailyStatistics(s){
  if(!s?.types)return '';
  const t=s.types,num=v=>v===null||v===undefined?'—':Number(v).toLocaleString('ko-KR');
  return `<section class="daily-analysis daily-statistics"><h3>후기 내용 유형별 통계</h3><p>전체 수집 후기 <b>${num(t.total)}건</b> 기준 · 선정에서 제외된 후기도 포함</p><div class="daily-table-wrap"><table><thead><tr><th>내용 유형</th><th>전체</th><th>비율</th>${t.brands.map(b=>`<th>${dailyEscape(b.name)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(r=>`<tr><th>${dailyEscape(r.name)}</th><td>${num(r.count)}건</td><td>${r.percent===null?'—':num(r.percent)+'%'}</td>${t.brands.map(b=>`<td>${num(r.brands[b.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><small>${dailyEscape(t.note)}<br>일반 칭찬·만족은 다른 내용 유형이 없는 후기입니다. 쫄깃하다·고소하다·달지 않다도 유형 통계에는 집계하지만 선정 후기 목록의 기준은 유지합니다. AI API를 호출하지 않습니다.</small><details class="daily-type-evidence"><summary>유형별 분류 근거 보기 (각 유형 최대 3건)</summary>${t.rows.filter(r=>r.count).map(r=>`<article><h4>${dailyEscape(r.name)} · ${num(r.count)}건</h4>${r.examples.map(e=>`<p><b>${dailyEscape(e.brand)}</b>${e.phrase?' · 분류 문구: '+dailyEscape(e.phrase):''}</p><blockquote>${dailyEscape(e.text||'본문 없음')}</blockquote>`).join('')}</article>`).join('')}</details></section>`;
}
function dailyPaper(r){
  r={...r,brands:r.brands.map(b=>({...b,reviews:[...b.reviews].sort((a,b)=>Array.from(b.excerpt||'').length-Array.from(a.excerpt||'').length)}))};
  const gen=new Date(r.generated_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false});
  return `<div class="daily-head"><div><div class="daily-eyebrow">DAILY REVIEW BRIEF</div><div class="daily-title">전일 종합</div><div class="daily-date">${dailyEscape(r.date)} · 자사와 경쟁사</div></div><div class="daily-gen">매일 오전 9시 갱신 · 한국시간<br>생성 ${dailyEscape(gen)}</div></div>
  <div class="daily-kpis"><div class="daily-kpi"><strong>${r.total.toLocaleString()}</strong>수집된 전일 후기</div><div class="daily-kpi"><strong>${r.low_count.toLocaleString()}</strong>3점 이하 후기</div><div class="daily-kpi"><strong>${r.selected_count.toLocaleString()}</strong>선정 표시 후기</div></div>
  <div class="daily-notice">${dailyEscape(r.notice)}</div>${dailyStatistics(r.statistics)}<div class="daily-grid">${r.brands.map(b=>`<section class="daily-card ${b.role==='자사'?'own':''}"><div class="daily-card-head"><div class="daily-brand">${dailyEscape(b.name)}<span class="daily-role">${dailyEscape(b.role)}</span></div><div class="daily-stats"><span>전체 수집 <b>${b.count??'—'}</b></span><span>선정 <b>${b.selected_count}</b></span><span>평점 <b>${b.average===null?'—':b.average.toFixed(2)}</b></span><span>3점 이하 <b>${b.low_count??'—'}</b></span></div></div><div class="daily-coverage">${dailyEscape(b.coverage)}<br>최신 보유 후기: ${dailyEscape(b.latest_review_date||'미확인')}</div>${b.reviews.length?b.reviews.map(v=>`<div class="daily-review"><div class="daily-review-top"><span class="daily-score ${v.score!==null&&v.score<=3?'low':''}">${v.score===null?'평점 미제공':v.score+' / 5'}</span><span>${dailyEscape(({smartstore:'네이버',naver:'네이버',direct:'자사몰',kakao:'카카오'})[v.platform]||v.platform)}</span></div><div class="daily-product">${dailyEscape(v.product)}</div><p class="daily-quote">${v.excerpt?dailyHighlighted(v):'본문이 없는 후기입니다.'}</p></div>`).join(''):`<div class="daily-empty">${b.available?'이 날짜에 구체적인 평가 이유가 있는 선정 후기가 없습니다.<br>전체 수집 건수와 수집 상태를 함께 확인해 주세요.':'아직 수집되지 않는 브랜드입니다.<br>후기 0건으로 집계하지 않습니다.'}</div>`}</section>`).join('')}</div><div class="daily-foot">${dailyEscape(r.selection_rule)}<br>${dailyEscape(r.highlight_rule)}<br>백년화편 후기 대시보드 · 본 보고서는 수집 시점의 자료를 보존합니다.</div>`;
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
    mc.innerHTML='<div class="daily-tools"><div><h2>전일 종합</h2><p>백년화편·명가삼대떡집 이유 있는 후기 선정 · 글자 수 많은 순 · 본문 전체 표시</p></div><div class="daily-actions"><label for="dailyDate">후기 날짜</label><select id="dailyDate" onchange="renderDailyReport(this.value)">'+options+'</select><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서</button><button class="refresh-btn" id="dailyDownload" onclick="downloadDailyReport()">전체 이미지 저장</button></div></div><p class="daily-archive-note">'+(r.reconstructed?'이전 보고서는 현재 보유한 해당 날짜 원문에서 같은 선정 기준으로 표시합니다.':r.historical?'보관된 과거 원문에 현재와 같은 선정·강조 기준을 적용합니다.':'현재 전일 보고서입니다. 원본 후기는 보존하고 이유 있는 후기만 표시합니다.')+' 저장된 날짜 '+dates.length+'개 · 선정 후기 전체를 긴 PNG 이미지 한 장으로 저장합니다.</p><div id="dailyPaper" class="daily-paper">'+dailyPaper(r)+'</div>';
  }catch(e){if(currentShop==='daily'&&requestId===dailyRequestId){dailyReportData=null;mc.innerHTML='<div class="card">'+dailyEscape(e.message)+'<br><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서 보기</button></div>';}}
}
// Keep one full image within conservative browser canvas dimensions/area.
function dailyImageScale(height){
  return Math.min(1,16000/height,Math.sqrt(16000000/(1040*height)));
}
async function downloadDailyReport(){
  if(!dailyReportData)return;const exportReport=dailyReportData,button=document.getElementById('dailyDownload');
  if(button.disabled)return;button.disabled=true;button.textContent='전체 이미지 만드는 중…';
  const stage=document.createElement('div');stage.className='daily-paper daily-export';stage.style.cssText='position:absolute;left:-12000px;top:0;';
  let url;
  try{
    stage.innerHTML=dailyPaper(exportReport);document.body.appendChild(stage);await document.fonts.ready;
    if(typeof html2canvas!=='function')throw new Error('이미지 저장 모듈을 불러오지 못했습니다. 페이지를 새로고침해 주세요.');
    const height=Math.ceil(stage.getBoundingClientRect().height);
    const canvas=await html2canvas(stage,{scale:dailyImageScale(height),backgroundColor:'#f6f4ed',logging:false,windowWidth:1200,width:1040,height});
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    canvas.width=canvas.height=0;
    if(!blob)throw new Error('이미지 생성에 실패했습니다. 다시 시도해 주세요.');
    url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`전일종합_${exportReport.date}_전체.png`;
    document.body.appendChild(a);a.click();a.remove();
  }catch(e){alert(e.message);}finally{if(url)setTimeout(()=>URL.revokeObjectURL(url),60000);stage.remove();button.disabled=false;button.textContent='전체 이미지 저장';}
}

window.addEventListener('DOMContentLoaded',()=>{if(location.hash==='#daily'){const tab=document.getElementById('dailyReportTab');if(tab)switchShop('daily',tab);}});
