/* Editable, source-phrase-only summary. State survives report and tab rerenders. */
(function () {
  'use strict';
  const DEFAULT_NOTICE = '수집된 후기만으로 만든 원문 표현 기반 초안입니다. 외부 AI를 호출하지 않습니다. 공유 전 내용과 기간을 확인해 주세요.';
  const BRAND_NAMES = {all: '백년 자사몰 + 명가', jasaol: '백년 자사몰', myeongga: '명가'};
  const state = {
    reportKey: null, selection: null, loadedSelection: null, mode: 'range', month: '',
    text: '', sourceText: '', totalCount: 0, hasResult: false,
    notice: DEFAULT_NOTICE, status: '', error: '', failed: false, loading: false, copying: false,
    requestId: 0, copyId: 0, controller: null, root: null
  };
  const field = id => state.root && state.root.querySelector('#' + id);
  const key = s => s ? [s.from, s.to, s.brand].join('|') : '';
  const dirty = () => state.text !== state.sourceText;
  const active = root => root && root === state.root && document.getElementById('reviewCopySummary') === root && (typeof currentShop === 'undefined' || currentShop === 'daily');
  const sameSelection = () => key(state.selection) === key(state.loadedSelection);
  const canCopy = () => state.hasResult && state.totalCount > 0 && !!state.text.trim() && sameSelection() && !state.loading && !state.copying && !state.error && !state.failed;

  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '') || value.slice(0, 4) === '0000') return false;
    const date = new Date(value + 'T00:00:00Z');
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }
  function kstToday() {
    return new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  }
  function monthRange(month) {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month || '')) return null;
    const first = month + '-01';
    if (!validDate(first)) return null;
    const end = new Date(first + 'T00:00:00Z');
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
    const last = end.toISOString().slice(0, 10), today = kstToday();
    return {from: first, to: last < today ? last : today};
  }
  function selectionLabel(selection) {
    if (!selection) return '아직 생성하지 않았습니다';
    return selection.from + (selection.from === selection.to ? '' : ' ~ ' + selection.to) + ' · ' + BRAND_NAMES[selection.brand];
  }
  function cancelRequest() {
    ++state.requestId;
    if (state.controller) state.controller.abort();
    state.controller = null;
    state.loading = false;
    ++state.copyId;
    state.copying = false;
  }
  function suspend() {
    cancelRequest();
    state.root = null;
  }
  function update() {
    if (!active(state.root)) return;
    field('reviewCopyLoad').disabled = state.loading;
    field('reviewCopyLoad').textContent = state.loading ? '요약 만드는 중…' : '요약 만들기';
    field('reviewCopyButton').disabled = !canCopy();
    field('reviewCopyButton').textContent = state.copying ? '복사 중…' : '카톡용 복사';
    field('reviewCopyStatus').textContent = state.error || state.status;
    field('reviewCopyStatus').className = 'review-copy-status' + (state.error ? ' is-error' : '');
    field('reviewCopyNotice').textContent = state.notice;
    field('reviewCopyScope').textContent = state.hasResult
      ? '미리보기 기준: ' + selectionLabel(state.loadedSelection) + ' · 수집 ' + state.totalCount.toLocaleString('ko-KR') + '건' + (dirty() ? ' · 직접 수정한 초안' : '') + (!sameSelection() ? ' · 현재 선택과 다름' : '')
      : '기간과 브랜드를 선택하면 공유용 요약을 만듭니다.';
    state.root.setAttribute('aria-busy', state.loading ? 'true' : 'false');
  }
  function syncControls() {
    field('reviewCopyMode').value = state.mode;
    field('reviewCopyFrom').value = state.selection.from;
    field('reviewCopyTo').value = state.selection.to;
    field('reviewCopyMonth').value = state.month;
    field('reviewCopyBrand').value = state.selection.brand;
    field('reviewCopyRangeFields').hidden = state.mode !== 'range';
    field('reviewCopyMonthField').hidden = state.mode !== 'month';
  }
  function selectionChanged() {
    cancelRequest();
    state.error = '';
    state.status = canCopy()
      ? '미리보기와 같은 기간·브랜드입니다. 내용을 확인한 뒤 복사할 수 있습니다.'
      : '선택이 바뀌었습니다. 요약 만들기를 눌러 주세요. 기존 초안은 그대로 보관했습니다.';
    update();
  }
  async function load() {
    if (!active(state.root) || state.loading) return;
    const selection = {...state.selection};
    if (!validDate(selection.from) || !validDate(selection.to) || selection.from > selection.to || selection.to > kstToday()) {
      state.error = '시작일과 종료일을 확인해 주세요. 시작일 ≤ 종료일 ≤ 오늘(한국시간)이어야 합니다.';
      update(); return;
    }
    if (dirty() && !window.confirm('수정한 초안을 새 요약으로 바꿀까요? 취소하면 현재 초안을 유지합니다.')) {
      state.status = '수정한 초안을 유지했습니다.';
      update(); return;
    }
    cancelRequest();
    const requestId = state.requestId, root = state.root;
    state.controller = typeof AbortController === 'function' ? new AbortController() : null;
    const controller = state.controller;
    const current = () => active(root) && requestId === state.requestId && key(selection) === key(state.selection);
    state.loading = true;
    state.error = '';
    state.status = '선택한 기간의 수집 후기로 요약을 만들고 있습니다. 기존 초안은 완료 전까지 유지됩니다.';
    update();
    try {
      const query = new URLSearchParams({date_from: selection.from, date_to: selection.to, brand: selection.brand});
      const response = await fetch('/api/review-copy-summary?' + query, controller ? {signal: controller.signal} : {});
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : '요약을 불러오지 못했습니다. 다시 시도해 주세요.');
      }
      const data = await response.json();
      if (!current()) return;
      if (!data || typeof data.text !== 'string' || data.date_from !== selection.from || data.date_to !== selection.to || data.brand !== selection.brand) {
        throw new Error('선택한 기간·브랜드와 요약 응답이 일치하지 않습니다. 다시 시도해 주세요.');
      }
      const total = Number(data.total_count ?? (Array.isArray(data.brands) ? data.brands.reduce((sum, brand) => sum + (Number(brand.count) || 0), 0) : 0));
      if (!Number.isFinite(total) || total < 0) throw new Error('수집 건수를 확인하지 못했습니다. 다시 시도해 주세요.');
      state.failed = false;
      state.text = state.sourceText = data.text;
      state.totalCount = total;
      state.loadedSelection = selection;
      state.hasResult = true;
      state.notice = DEFAULT_NOTICE + (typeof data.notice === 'string' && data.notice ? ' ' + data.notice : '');
      state.status = total > 0 ? '요약을 만들었습니다. 미리보기를 수정한 뒤 복사할 수 있습니다.' : '선택한 기간에 수집된 후기가 없어 복사할 수 없습니다. 다른 기간이나 브랜드를 선택해 주세요.';
      field('reviewCopyText').value = state.text;
    } catch (error) {
      if (!current()) return;
      state.failed = true;
      state.error = (error && error.message ? error.message : '요약을 불러오지 못했습니다.') + (state.hasResult ? ' 기존 미리보기는 보관했으며 복사는 잠시 꺼두었습니다.' : '');
    } finally {
      if (current()) {
        state.loading = false;
        state.controller = null;
        update();
      }
    }
  }
  function selectPreview(textarea) {
    try { textarea.focus(); } catch (_) {}
    try { textarea.select(); } catch (_) {}
    try { textarea.setSelectionRange(0, textarea.value.length); } catch (_) {}
  }
  async function copy() {
    if (!active(state.root) || !canCopy()) return false;
    const root = state.root, text = state.text, scope = key(state.selection), copyId = ++state.copyId;
    const current = () => active(root) && copyId === state.copyId && text === state.text && scope === key(state.selection);
    state.copying = true;
    state.status = '복사하고 있습니다…';
    update();
    let copied = false;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        try { await navigator.clipboard.writeText(text); copied = true; } catch (_) {}
      }
      if (!current()) return false;
      if (!copied) {
        selectPreview(field('reviewCopyText'));
        try { copied = typeof document.execCommand === 'function' && document.execCommand('copy') === true; } catch (_) {}
      }
      if (!current()) return false;
      state.status = copied ? '복사했습니다. 카카오톡에 붙여넣어 주세요.' : '자동 복사에 실패했습니다. 미리보기에서 Ctrl+C / ⌘C를 누르거나 모바일에서 길게 눌러 직접 복사해 주세요.';
      return copied;
    } finally {
      if (current()) { state.copying = false; update(); }
    }
  }
  function mount(root, report) {
    if (!root) return;
    suspend();
    state.root = root;
    const from = report.date_from || report.date, to = report.date_to || report.date;
    const reportKey = from + '|' + to;
    const reportChanged = state.reportKey !== reportKey;
    if (reportChanged || !state.selection) {
      state.reportKey = reportKey;
      state.selection = {from, to, brand: state.selection ? state.selection.brand : 'all'};
      state.mode = 'range'; state.month = (to || '').slice(0, 7);
    }
    root.innerHTML = '<section class="review-copy-panel" aria-labelledby="reviewCopyHeading">' +
      '<div class="review-copy-heading"><div><h3 id="reviewCopyHeading">카톡용 후기 요약</h3><p>백년 자사몰과 명가의 수집 후기를 짧게 정리해 공유하세요.</p></div><span class="review-copy-badge">원문 표현 기반</span></div>' +
      '<div class="review-copy-filters"><div class="review-copy-field"><label for="reviewCopyMode">기간 선택</label><select id="reviewCopyMode"><option value="range">날짜 범위</option><option value="month">월별</option></select></div>' +
      '<div id="reviewCopyRangeFields" class="review-copy-range"><div class="review-copy-field"><label for="reviewCopyFrom">시작일</label><input id="reviewCopyFrom" type="date"></div><div class="review-copy-field"><label for="reviewCopyTo">종료일</label><input id="reviewCopyTo" type="date"></div></div>' +
      '<div id="reviewCopyMonthField" class="review-copy-field" hidden><label for="reviewCopyMonth">후기 월</label><input id="reviewCopyMonth" type="month"></div>' +
      '<div class="review-copy-field"><label for="reviewCopyBrand">요약 브랜드</label><select id="reviewCopyBrand"><option value="all">전체 (백년 자사몰 + 명가)</option><option value="jasaol">백년 자사몰</option><option value="myeongga">명가</option></select></div>' +
      '<button type="button" id="reviewCopyLoad" class="refresh-btn">요약 만들기</button></div>' +
      '<p id="reviewCopyNotice" class="review-copy-notice"></p><label class="review-copy-preview-label" for="reviewCopyText">공유할 요약 미리보기 · 직접 수정 가능</label>' +
      '<p id="reviewCopyScope" class="review-copy-scope"></p><textarea id="reviewCopyText" rows="13" spellcheck="false" aria-describedby="reviewCopyNotice reviewCopyScope" placeholder="수집 후기를 확인하고 요약을 만드는 중입니다."></textarea>' +
      '<div class="review-copy-footer"><button type="button" id="reviewCopyButton" disabled>카톡용 복사</button><p id="reviewCopyStatus" class="review-copy-status" role="status" aria-live="polite" aria-atomic="true"></p></div></section>';
    syncControls();
    field('reviewCopyFrom').max = field('reviewCopyTo').max = kstToday();
    field('reviewCopyMonth').max = kstToday().slice(0, 7);
    field('reviewCopyText').value = state.text;
    field('reviewCopyFrom').addEventListener('input', event => { state.selection.from = event.target.value; selectionChanged(); });
    field('reviewCopyTo').addEventListener('input', event => { state.selection.to = event.target.value; selectionChanged(); });
    field('reviewCopyBrand').addEventListener('change', event => {
      state.selection.brand = Object.hasOwn(BRAND_NAMES, event.target.value) ? event.target.value : 'all'; selectionChanged();
    });
    field('reviewCopyMode').addEventListener('change', event => {
      state.mode = event.target.value === 'month' ? 'month' : 'range';
      if (state.mode === 'month') {
        const range = monthRange(state.month);
        state.selection.from = range ? range.from : ''; state.selection.to = range ? range.to : '';
      }
      syncControls(); selectionChanged();
    });
    field('reviewCopyMonth').addEventListener('input', event => {
      state.month = event.target.value;
      const range = monthRange(state.month);
      state.selection.from = range ? range.from : ''; state.selection.to = range ? range.to : '';
      syncControls(); selectionChanged();
    });
    field('reviewCopyText').addEventListener('input', event => {
      const wasLoading = state.loading;
      cancelRequest();
      state.text = event.target.value;
      state.status = wasLoading ? '입력한 초안을 보관하고 진행 중인 조회를 중단했습니다.' : '초안을 수정했습니다.';
      if (canCopy()) state.status += ' 바뀐 내용으로 복사할 수 있습니다.';
      else if (!state.text.trim()) state.status += ' 복사할 내용을 입력해 주세요.';
      else if (state.hasResult && state.totalCount === 0) state.status += ' 수집된 후기가 없어 복사할 수 없습니다.';
      if (!sameSelection()) state.status += ' 현재 선택과 다른 기간의 초안이므로 새 요약을 만든 뒤 복사해 주세요.';
      update();
    });
    field('reviewCopyLoad').addEventListener('click', load);
    field('reviewCopyButton').addEventListener('click', copy);
    if (dirty()) {
      state.status = reportChanged ? '보고서 날짜가 바뀌어도 수정한 초안은 유지됩니다. 새 기간의 요약이 필요하면 요약 만들기를 눌러 주세요.' : '수정한 초안을 유지했습니다.';
      update();
    } else {
      update();
      load();
    }
  }
  window.reviewCopySummary = {mount, suspend};
})();
