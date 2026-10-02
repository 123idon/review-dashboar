// Run: node tests/test_review_copy_ui.cjs
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const code = fs.readFileSync('static/review-copy-summary.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
class Element {
  constructor(id) { this.id = id; this.value = ''; this.textContent = ''; this.disabled = false; this.hidden = false; this.listeners = {}; this.attributes = {}; this.nodes = {}; }
  set innerHTML(html) { this.html = html; this.nodes = {}; for (const match of html.matchAll(/id="([^"]+)"/g)) this.nodes[match[1]] = new Element(match[1]); }
  get innerHTML() { return this.html; }
  querySelector(selector) { return this.nodes[selector.slice(1)]; }
  addEventListener(event, handler) { this.listeners[event] = handler; }
  emit(event, value) { if (value !== undefined) this.value = value; return this.listeners[event]({target: this}); }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  setSelectionRange(start, end) { this.selection = [start, end]; }
}
function setup() {
  const pending = [], confirmations = [], clipboard = [];
  let root, confirmed = true, execResult = false, execCalls = 0;
  class Clock extends Date { constructor(...args) { super(...(args.length ? args : ['2026-10-01T05:00:00Z'])); } static now() { return new Date('2026-10-01T05:00:00Z').getTime(); } }
  const document = {getElementById: id => id === 'reviewCopySummary' ? root : null, execCommand: command => { assert.equal(command, 'copy'); ++execCalls; return execResult; }};
  const context = vm.createContext({Date: Clock, URLSearchParams, AbortController, currentShop: 'daily', document,
    window: {confirm: message => { confirmations.push(message); return confirmed; }},
    navigator: {clipboard: {writeText: text => { const task = deferred(); clipboard.push({text, ...task}); return task.promise; }}},
    fetch: (url, options) => { const task = deferred(); pending.push({url, options, ...task}); return task.promise; }
  });
  vm.runInContext(code, context);
  const mount = report => { root = new Element('reviewCopySummary'); context.window.reviewCopySummary.mount(root, report); return root; };
  const payload = (n, extra = {}) => {
    const params = new URL('https://example.test' + pending[n].url).searchParams;
    return {date_from: params.get('date_from'), date_to: params.get('date_to'), brand: params.get('brand'), text: '[후기 요약]\n짧은 실제 요약입니다.', total_count: 10, brands: [{count: 10}], notice: '수집분 기준', method: 'source_phrases', ...extra};
  };
  return {context, pending, clipboard, confirmations, mount, payload,
    field: id => root.querySelector('#reviewCopy' + id), root: () => root,
    confirm: value => { confirmed = value; }, exec: value => { execResult = value; }, execCalls: () => execCalls,
    reply: async (n, extra, ok = true) => { pending[n].resolve({ok, json: async () => payload(n, extra)}); await flush(); }
  };
}
const report = {date: '2026-09-30', date_from: '2026-09-30', date_to: '2026-09-30'};
(async () => {
  // Report defaults, loading state, full text preview and escaped/uninterpreted values.
  const s = setup();
  s.mount({...report, date_from: '2026-09-25', date_to: '2026-09-27'});
  assert(s.pending[0].url.includes('date_from=2026-09-25&date_to=2026-09-27&brand=all'));
  assert(s.field('Button').disabled); assert(s.field('Load').disabled);
  assert.equal(s.root().attributes['aria-busy'], 'true');
  const hostile = '</textarea><img src=x onerror=alert(1)><script>alert(1)</script>';
  await s.reply(0, {text: hostile, notice: hostile});
  assert.equal(s.field('Text').value, hostile);
  assert(s.field('Notice').textContent.includes(hostile));
  assert(!s.root().innerHTML.includes(hostile));
  assert(!s.field('Button').disabled); assert(!s.field('Load').disabled);
  assert(s.root().innerHTML.includes('aria-live="polite"'));
  assert(s.root().innerHTML.includes('for="reviewCopyText"'));

  // Success is shown only after awaited clipboard write; repeated clicks are ignored.
  const copying = s.field('Button').emit('click');
  assert(s.field('Button').disabled); assert(!s.field('Status').textContent.includes('복사했습니다'));
  assert.equal(await s.field('Button').emit('click'), false); assert.equal(s.clipboard.length, 1);
  assert.equal(s.clipboard[0].text, hostile); s.clipboard[0].resolve();
  assert.equal(await copying, true); assert(s.field('Status').textContent.includes('복사했습니다'));
  // Rejected clipboard falls back to execCommand, including a truthful failure/manual path.
  s.exec(true);
  const fallback = s.field('Button').emit('click'); s.clipboard[1].reject(new Error('denied'));
  assert.equal(await fallback, true); assert.equal(s.execCalls(), 1);
  s.exec(false);
  const failedCopy = s.field('Button').emit('click'); s.clipboard[2].reject(new Error('denied'));
  assert.equal(await failedCopy, false);
  assert(s.field('Status').textContent.includes('자동 복사에 실패'));
  assert(s.field('Status').textContent.includes('모바일'));
  assert(s.field('Text').focused && s.field('Text').selected);
  assert.deepEqual(s.field('Text').selection, [0, hostile.length]);
  assert(!s.field('Status').textContent.includes('복사했습니다'));
  delete s.context.navigator.clipboard;
  const noClipboard = s.field('Button').emit('click'); assert.equal(await noClipboard, false);

  // Range/brand changes preserve editable text; a cancelled discard never fetches.
  s.field('Text').emit('input', '직접 다듬은 요약');
  s.field('From').emit('input', '2026-09-01');
  s.field('To').emit('input', '2026-09-30');
  s.field('Brand').emit('change', 'myeongga');
  assert.equal(s.field('Text').value, '직접 다듬은 요약'); assert(s.field('Button').disabled);
  assert(s.field('Scope').textContent.includes('현재 선택과 다름'));
  s.confirm(false); await s.field('Load').emit('click');
  assert.equal(s.pending.length, 1); assert.equal(s.field('Text').value, '직접 다듬은 요약');
  s.confirm(true); const loading = s.field('Load').emit('click');
  assert(s.pending[1].url.endsWith('brand=myeongga'));
  assert(s.field('Button').disabled); assert.equal(s.field('Text').value, '직접 다듬은 요약');
  await s.field('Load').emit('click'); assert.equal(s.pending.length, 2);
  // Typing during fetch cancels it; even a server ignoring AbortSignal cannot overwrite edits.
  s.field('Text').emit('input', '조회 중 새로 쓴 초안');
  assert(s.pending[1].options.signal.aborted);
  await s.reply(1, {text: '늦게 온 응답'}); await loading;
  assert.equal(s.field('Text').value, '조회 중 새로 쓴 초안');
  const generated = s.field('Load').emit('click'); await s.reply(2, {text: '새 기간 요약'}); await generated;
  assert.equal(s.field('Text').value, '새 기간 요약'); assert(!s.field('Button').disabled);

  // Out-of-order requests across filters and tab/report navigation cannot paint a new view.
  s.field('Brand').emit('change', 'jasaol'); const old = s.field('Load').emit('click');
  s.field('Brand').emit('change', 'all'); const newer = s.field('Load').emit('click');
  await s.reply(4, {text: '최신 선택 요약'}); await newer;
  await s.reply(3, {text: '이전 선택 요약'}); await old;
  assert.equal(s.field('Text').value, '최신 선택 요약');
  const awayLoad = s.field('Load').emit('click'), oldRoot = s.root();
  s.context.currentShop = 'jasaol'; s.context.window.reviewCopySummary.suspend();
  await s.reply(5, {text: '떠난 탭 응답'}); await awayLoad;
  assert.equal(oldRoot.querySelector('#reviewCopyText').value, '최신 선택 요약');
  s.context.currentShop = 'daily'; s.mount({...report, date_from: '2026-09-25', date_to: '2026-09-27'});
  assert.equal(s.field('From').value, '2026-09-01'); // own range survives same report remount
  await s.reply(6, {text: '돌아온 요약'});
  s.field('Text').emit('input', '보존할 수정본');
  s.mount({date: '2026-09-29'});
  assert.equal(s.pending.length, 7); assert.equal(s.field('Text').value, '보존할 수정본');
  assert.equal(s.field('From').value, '2026-09-29'); assert(s.field('Button').disabled);
  s.confirm(false); await s.field('Load').emit('click'); assert.equal(s.pending.length, 7);
  s.confirm(true); const changeReport = s.field('Load').emit('click'); await s.reply(7); await changeReport;
  assert(!s.field('Button').disabled);

  // Month selection is leap-year safe and limits current month to today in Korea.
  s.field('Mode').emit('change', 'month');
  assert(s.field('RangeFields').hidden); assert(!s.field('MonthField').hidden);
  s.field('Month').emit('input', '2024-02');
  assert.equal(s.field('From').value, '2024-02-01'); assert.equal(s.field('To').value, '2024-02-29');
  s.field('Month').emit('input', '2026-10');
  assert.equal(s.field('To').value, '2026-10-01');
  s.field('Mode').emit('change', 'range');
  s.field('From').emit('input', '2026-10-02');
  await s.field('Load').emit('click'); assert.equal(s.pending.length, 8);
  s.field('From').emit('input', '2026-02-30'); await s.field('Load').emit('click'); assert.equal(s.pending.length, 8);
  s.field('From').emit('input', '2026-10-01'); s.field('To').emit('input', '2026-10-02');
  await s.field('Load').emit('click'); assert.equal(s.pending.length, 8);
  s.field('To').emit('input', '2026-10-01');

  // Errors, incompatible server scopes and zero rows all disable copy, retaining prior text on errors.
  const errorRequest = s.field('Load').emit('click'); await s.reply(8, {detail: '<script>서버 오류</script>'}, false); await errorRequest;
  assert(s.field('Button').disabled); assert.equal(s.field('Text').value, '[후기 요약]\n짧은 실제 요약입니다.');
  assert(s.field('Status').textContent.includes('<script>서버 오류</script>'));
  s.field('Brand').emit('change', 'jasaol'); s.field('Brand').emit('change', 'all');
  assert(s.field('Button').disabled);
  const mismatch = s.field('Load').emit('click'); await s.reply(9, {date_to: '2020-01-01', text: 'wrong'}); await mismatch;
  assert(s.field('Status').textContent.includes('일치하지')); assert(s.field('Button').disabled);
  const empty = s.field('Load').emit('click'); await s.reply(10, {total_count: 0, text: '수집 0건'}); await empty;
  assert(s.field('Button').disabled); assert(s.field('Status').textContent.includes('수집된 후기가 없어'));
  const network = s.field('Load').emit('click'); s.pending[11].reject(new Error('offline')); await network;
  assert(s.field('Button').disabled); assert.equal(s.field('Text').value, '수집 0건');

  // A response for another brand is rejected even with matching dates.
  const b = setup(); b.mount(report); await b.reply(0, {brand: 'myeongga'});
  assert(b.field('Button').disabled); assert(b.field('Status').textContent.includes('기간·브랜드'));

  // Clipboard completion for a departed tab or changed textarea cannot announce false current success.
  const c = setup(); c.mount(report); await c.reply(0);
  const staleCopy = c.field('Button').emit('click'); c.field('Text').emit('input', '새 편집'); c.clipboard[0].resolve();
  assert.equal(await staleCopy, false); assert(!c.field('Status').textContent.includes('복사했습니다'));
  const copyAway = c.field('Button').emit('click'); c.context.window.reviewCopySummary.suspend(); c.context.currentShop = 'memo';
  c.clipboard[1].resolve(); assert.equal(await copyAway, false);

  // Hook preserves archive/image rendering and places summary outside image export.
  const daily = fs.readFileSync('static/daily-report.js', 'utf8'), index = fs.readFileSync('static/index.html', 'utf8');
  assert(daily.includes('<div id="reviewCopySummary"></div><div id="dailyPaper"'));
  assert(daily.includes('reviewCopySummary.mount(document.getElementById(\'reviewCopySummary\'),r)'));
  assert(daily.includes('stage.innerHTML=dailyPaper(exportReport)'));
  assert(index.includes('/static/review-copy-summary.js?v=1'));
  assert(index.includes('/static/review-copy-summary.css?v=1'));
  assert(index.includes('function switchShop(shop, el){\n  if(window.reviewCopySummary) window.reviewCopySummary.suspend();'));
  console.log('Review copy UI: clipboard truthfulness, manual/mobile fallback, filters, month bounds, XSS, dirty drafts, stale requests, navigation, error/empty states and report/export integration passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
