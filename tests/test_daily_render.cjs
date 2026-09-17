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
assert.equal(vm.runInContext('dailyImageScale(8001)',context),1);
for(const height of [16000,40000,100000]){
 context.height=height;const scale=vm.runInContext('dailyImageScale(height)',context);
 assert(height*scale<=16000);
 assert(Math.floor(1040*scale)*Math.floor(height*scale)<=16000000);
 assert(scale>0);
}
console.log('Full body, Unicode evidence, escaped HTML, wrapped marks and single image sizing passed.');
context.stats={basis:'전체 <후기>',total:{count:2,average:4,low_count:1,low_percent:50,unrated_count:0},brands:[{name:'<브랜드>',count:2,average:4,low_count:1,low_percent:50,unrated_count:0,scores:[{score:5,count:1},{score:3,count:1}],platforms:[{name:'<채널>',count:2}]}]};
const statsHtml=vm.runInContext('dailyStatistics(stats)',context);
assert(statsHtml.includes('전일 후기 통계'));
assert(statsHtml.includes('&lt;브랜드&gt;'));
assert(statsHtml.includes('50%'));
const code=fs.readFileSync('static/daily-report.js','utf8');
assert(!code.includes('dailyAnalysis'));
assert(code.includes('${dailyStatistics(r.statistics)}'));
assert(code.includes('stage.innerHTML=dailyPaper(exportReport)'));
console.log('Full-review statistics share the screen/image renderer.');
