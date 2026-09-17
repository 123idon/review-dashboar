const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/index.html','utf8');
function source(name){
 const start=html.indexOf('function '+name+'(');
 assert(start>=0,name);
 return (html.slice(start-6,start)==='async '?'async ':'')+html.slice(start,html.indexOf('\n}',start)+2);
}
const pending=[];
const ctx=vm.createContext({Intl,Date,URLSearchParams,AbortController,clearTimeout,
 fetch:(url,options)=>new Promise(resolve=>pending.push({url,resolve})),
 document:{getElementById:()=>null},showToast:()=>{},render:()=>{},
});
vm.runInContext(`let dateFilterStart=null,dateFilterEnd=null,filteredData=null,allData={id:'all'};
let _filterAbort=null,_filterRequestId=0,_filterLoading=false,_filterError='';
let reviewFilter='all',reviewKeyword='',currentPage=1,revSelected=new Map(),_reviewRequestId=0,keywordDebounceTimer=null;
`+['resetReviewScope','kstToday','presetStart','fetchFilteredData','resetDateFilter','refreshActiveRange'].map(source).join('\n'),ctx);
const run=code=>vm.runInContext(code,ctx);
const reply=(n,data,ok=true)=>pending[n].resolve({ok,json:async()=>data});
(async()=>{
 assert.equal(run("kstToday(new Date('2026-09-16T15:01:00Z'))"),'2026-09-17');
 assert.equal(run("presetStart(3,'2026-09-17')"),'2026-09-15');
 assert.equal(run("presetStart(7,'2026-01-03')"),'2025-12-28');
 assert.equal(run("presetStart(30,'2024-03-01')"),'2024-02-01');
 const old=run("fetchFilteredData('2026-09-14','2026-09-17')");
 const latest=run("fetchFilteredData('2026-09-16','2026-09-16')");
 reply(1,{id:'latest'});await latest;
 reply(0,{id:'stale'});await old;
 assert.equal(run('filteredData.id'),'latest');
 assert.equal(run('dateFilterStart'),'2026-09-16');
 const reset=run("fetchFilteredData('2026-09-15','2026-09-17')");
 await run('resetDateFilter()');reply(2,{id:'reset-stale'});await reset;
 assert.equal(run('filteredData'),null);assert.equal(run('dateFilterStart'),null);
 const fail=run("fetchFilteredData('2026-09-15','2026-09-17')");reply(3,{},false);await fail;
 assert.equal(run('dateFilterStart'),null);assert(run('_filterError'));
 const success=run("fetchFilteredData(null,'2026-09-15')");reply(4,{id:'to-only'});await success;
 assert.equal(run('dateFilterStart'),null);assert.equal(run('dateFilterEnd'),'2026-09-15');
 const refreshed=run('refreshActiveRange()');
 assert(pending[5].url.includes('date_to=2026-09-15'));
 reply(5,{id:'refreshed'});await refreshed;
 assert.equal(run('filteredData.id'),'refreshed');
 assert.equal(run('dateFilterEnd'),'2026-09-15');
 console.log('KST, inclusive presets, stale response, reset, failure, open bounds and refresh tests passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
