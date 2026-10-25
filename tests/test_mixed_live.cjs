const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.env.LIVE_SCRIPT, 'utf8');
function harness(mode='auto') {
  const timers = new Map(), listeners = {}, calls = [], statuses = [];
  let seq=0, replacements=0, result={status:200}, hold;
  const root={dataset:{updateMode:mode,population:'mixed:test'},querySelector(){return null;},replaceWith(){replacements++;}};
  const label={set textContent(v){statuses.push(v);}};
  const document={hidden:false,body:{dataset:{population:'mixed:test'}},activeElement:null,
    getElementById(id){return id==='content'?root:id==='sync-status'?label:null;},
    querySelector(){return null;},querySelectorAll(){return [];},addEventListener(k,fn){listeners[k]=fn;},dispatchEvent(){}};
  const context={document,location:{search:''},URLSearchParams,AbortController,CustomEvent:function(){},
    DOMParser:function(){this.parseFromString=()=>({getElementById:()=>root});},
    window:{getSelection:()=>null,scrollTo(){},scrollX:0,scrollY:0},
    setTimeout(fn,ms){const id=++seq;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
    addEventListener(k,fn){listeners[k]=fn;},
    async fetch(url,options){calls.push({url,options});if(hold)await hold;
      return {...result,text:async()=>JSON.stringify({version:'mixed-desk-snapshot-v1',population:'mixed:test',html:'fixture',status:result.status===503?'UNAVAILABLE':'OK'})};}};
  vm.runInNewContext(source,context);
  return {timers,listeners,calls,statuses,document,context,replaced:()=>replacements,
    response:r=>{result=r;},hold:p=>{hold=p;},
    tick:async()=>{const [id,t]=timers.entries().next().value;timers.delete(id);t.fn();for(let i=0;i<12;i++)await Promise.resolve();}};
}
test('active page polls same-origin stored snapshot every five seconds',async()=>{
 const h=harness();assert.equal([...h.timers.values()][0].ms,5000);await h.tick();
 assert.equal(h.calls[0].url,'/desk/snapshot?');assert.equal(h.calls[0].options.credentials,'same-origin');
 assert.equal(h.calls[0].options.cache,'no-store');assert.equal(h.replaced(),1);
 assert.match(h.statuses.at(-1),/quote time is separate/);assert.equal([...h.timers.values()][0].ms,5000);
});
test('frozen, history and paused pages never start automatic polling',()=>{
 for(const mode of ['frozen','history','paused']){const h=harness(mode);assert.equal(h.timers.size,0);assert.equal(h.calls.length,0);}
});
test('hidden page suspends requests and resumes on visibility',async()=>{
 const h=harness();h.document.hidden=true;await h.tick();assert.equal(h.calls.length,0);
 h.document.hidden=false;h.listeners.visibilitychange();for(let i=0;i<12;i++)await Promise.resolve();
 assert.equal(h.calls.length,1);
});
test('inflight requests cannot overlap',async()=>{
 const h=harness();let release;h.hold(new Promise(r=>{release=r;}));await h.tick();
 h.listeners.online();h.listeners.visibilitychange();assert.equal(h.calls.length,1);
 release();for(let i=0;i<12;i++)await Promise.resolve();assert.equal(h.replaced(),1);
});
test('authentication failure stops retries and retains dated records',async()=>{
 const h=harness();h.response({status:401});await h.tick();
 assert.equal(h.timers.size,0);assert.equal(h.replaced(),0);assert.match(h.statuses.at(-1),/Authentication required/);
});
test('transport failure backs off and warns that displayed records may be old',async()=>{
 const h=harness();h.response({status:502});await h.tick();assert.equal(h.replaced(),0);
 assert.equal([...h.timers.values()][0].ms,10000);assert.match(h.statuses.at(-1),/may be old/);
});
test('valid unavailable snapshot replaces old balances, rather than retaining them as current',async()=>{
 const h=harness();h.response({status:503});await h.tick();assert.equal(h.replaced(),1);
 assert.match(h.statuses.at(-1),/Account evidence unavailable/);
});
test('inspection holds updates until text selection ends',async()=>{
 const h=harness();h.context.window.getSelection=()=>({toString:()=> 'selected'});await h.tick();
 assert.equal(h.replaced(),0);assert.match(h.statuses.at(-1),/while you inspect/);
 h.context.window.getSelection=()=>null;await h.tick();assert.equal(h.replaced(),1);
});
test('snapshot replacement preserves selected tabs, disclosure state, focus and scrolling',async()=>{
 const h=harness();let clicked=0,focused=false;
 const button={id:'tab-data-stream',click(){clicked++;},focus(options){focused=options.preventScroll;}};
 const detail={id:'quote-details',open:true,scrollTop:0,scrollLeft:0};
 const stream={id:'stream-scroll',scrollTop:125,scrollLeft:12};
 const ids={'content':h.document.getElementById('content'),'sync-status':h.document.getElementById('sync-status'),
   'tab-data-stream':button,'quote-details':detail,'stream-scroll':stream};
 h.document.activeElement=button;
 h.document.getElementById=id=>ids[id];
 h.document.querySelectorAll=selector=>selector.includes('aria-selected')?[button]:selector==='details[id]'?[detail]:selector==='[id]'?[stream]:[];
 h.document.dispatchEvent=()=>{detail.open=false;stream.scrollTop=0;stream.scrollLeft=0;};
 await h.tick();
 assert.equal(clicked,1);assert.ok(focused);assert.ok(detail.open);
 assert.equal(stream.scrollTop,125);assert.equal(stream.scrollLeft,12);
});
