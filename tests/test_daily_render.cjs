// Run: node tests/test_daily_render.cjs
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({window:{addEventListener(){}},TextEncoder,Blob});
vm.runInContext(fs.readFileSync('static/daily-report.js','utf8'),context);
context.v={excerpt:'😀 추천해요. 많이 달지 않아서 좋았어요 <script>',highlights:[{start:8,end:17,reason:'당도'}]};
const html=vm.runInContext('dailyHighlighted(v)',context);
assert.equal(html.replace(/<mark[^>]*>|<\/mark>/g,''),vm.runInContext('dailyEscape(v.excerpt)',context));
assert(!html.includes('<script>'));
const marks=[...html.matchAll(/<mark[^>]*>(.*?)<\/mark>/g)].map(m=>m[1]);
assert.equal(marks.join(''),'많이 달지 않아서');
assert(marks.every(m=>Array.from(m).length===1)); // wrapped canvas glyph bounds
assert.equal(vm.runInContext('dailyImageSlices(8001).map(s=>s.height).join(",")',context),'4000,4000,1');
console.log('Full body, Unicode evidence, escaped HTML, wrapped marks and image slices passed.');
