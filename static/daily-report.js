let dailyReportData = null;
let dailySelectedDate = null;
let dailyRequestId = 0;
function dailyEscape(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function dailyHighlighted(review){
  // Python offsets count Unicode code points, not UTF-16 code units.
  const chars=Array.from(review.excerpt||'');let out='',at=0;
  for(const h of review.highlights||[]){
    if(h.start<at||h.end>chars.length||h.end<=h.start)continue;
    out+=dailyEscape(chars.slice(at,h.start).join(''))+`<mark class="${h.kind==='negative'?'negative':'positive'}">`+dailyEscape(chars.slice(h.start,h.end).join(''))+'</mark>';at=h.end;
  }
  return out+dailyEscape(chars.slice(at).join(''));
}
function dailyPaper(r){
  const gen=new Date(r.generated_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false});
  return `<div class="daily-head"><div><div class="daily-eyebrow">DAILY REVIEW BRIEF</div><div class="daily-title">전일 종합</div><div class="daily-date">${dailyEscape(r.date)} · 자사와 경쟁사</div></div><div class="daily-gen">매일 오전 9시 갱신 · 한국시간<br>생성 ${dailyEscape(gen)}</div></div>
  <div class="daily-kpis"><div class="daily-kpi"><strong>${r.total.toLocaleString()}</strong>수집된 전일 후기</div><div class="daily-kpi"><strong>${r.low_count.toLocaleString()}</strong>3점 이하 후기</div><div class="daily-kpi"><strong>${r.brands.filter(b=>b.available).length}</strong>자료 보유 브랜드 / 4</div></div>
  <div class="daily-notice">${dailyEscape(r.notice)}</div><div class="daily-grid">${r.brands.map(b=>`<section class="daily-card ${b.role==='자사'?'own':''}"><div class="daily-card-head"><div class="daily-brand">${dailyEscape(b.name)}<span class="daily-role">${dailyEscape(b.role)}</span></div><div class="daily-stats"><span>후기 <b>${b.count??'—'}</b></span><span>평점 <b>${b.average===null?'—':b.average.toFixed(2)}</b></span><span>3점 이하 <b>${b.low_count??'—'}</b></span></div></div><div class="daily-coverage">${dailyEscape(b.coverage)}<br>최신 보유 후기: ${dailyEscape(b.latest_review_date||'미확인')}</div>${b.reviews.length?b.reviews.map(v=>`<div class="daily-review"><div class="daily-review-top"><span class="daily-score ${v.score!==null&&v.score<=3?'low':''}">${v.score===null?'평점 미제공':v.score+' / 5'}</span><span>${dailyEscape(({naver:'네이버',direct:'자사몰',kakao:'카카오'})[v.platform]||v.platform)}</span></div><div class="daily-product">${dailyEscape(v.product)}</div><p class="daily-quote">${dailyHighlighted(v)}</p></div>`).join(''):`<div class="daily-empty">${b.available?'이 날짜에 보유한 후기 본문이 없습니다.<br>수집 상태를 함께 확인해 주세요.':'아직 수집되지 않는 브랜드입니다.<br>후기 0건으로 집계하지 않습니다.'}</div>`}</section>`).join('')}</div><div class="daily-foot">${dailyEscape(r.selection_rule)}<br>${dailyEscape(r.highlight_rule)}<br>백년화편 후기 대시보드 · 본 보고서는 수집 시점의 자료를 보존합니다.</div>`;
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
    mc.innerHTML='<div class="daily-tools"><div><h2>전일 종합</h2><p>매일 오전 9시 누적 저장 · 날짜는 후기가 작성된 날입니다.</p></div><div class="daily-actions"><label for="dailyDate">후기 날짜</label><select id="dailyDate" onchange="renderDailyReport(this.value)">'+options+'</select><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서</button><button class="refresh-btn" id="dailyDownload" onclick="downloadDailyReport()">한 장 이미지 저장</button></div></div><p class="daily-archive-note">'+(r.historical?'보관된 과거 보고서입니다. 생성 당시 내용을 그대로 보여줍니다.':'현재 전일 보고서입니다. 매일 보고서가 날짜별로 쌓입니다.')+' 저장된 날짜 '+dates.length+'개 · 저장을 시작하기 전 날짜는 목록에 표시되지 않습니다.</p><div id="dailyPaper" class="daily-paper">'+dailyPaper(r)+'</div>';
  }catch(e){if(currentShop==='daily'&&requestId===dailyRequestId){dailyReportData=null;mc.innerHTML='<div class="card">'+dailyEscape(e.message)+'<br><button class="refresh-btn" onclick="dailySelectedDate=null;renderDailyReport()">최신 보고서 보기</button></div>';}}
}
async function downloadDailyReport(){
  if(!dailyReportData)return;const exportReport=dailyReportData;const button=document.getElementById('dailyDownload');button.disabled=true;button.textContent='이미지 만드는 중…';
  const stage=document.createElement('div');stage.className='daily-paper daily-export';stage.style.cssText='position:absolute;left:-12000px;top:0;';stage.innerHTML=dailyPaper(exportReport);document.body.appendChild(stage);
  try{await document.fonts.ready;if(typeof html2canvas!=='function')throw new Error('이미지 저장 모듈을 불러오지 못했습니다. 페이지를 새로고침해 주세요.');
    const canvas=await html2canvas(stage,{scale:2,backgroundColor:'#f6f4ed',logging:false,windowWidth:1200});
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error('이미지 생성에 실패했습니다.');
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='전일종합_'+exportReport.date+'.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }catch(e){alert(e.message);}finally{stage.remove();button.disabled=false;button.textContent='한 장 이미지 저장';}
}

window.addEventListener('DOMContentLoaded',()=>{if(location.hash==='#daily'){const tab=document.getElementById('dailyReportTab');if(tab)switchShop('daily',tab);}});
