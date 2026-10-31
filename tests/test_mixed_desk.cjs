/* Local interactions only; a mocked DOM does not establish visual acceptance. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.env.MIXED_SCRIPT, 'utf8');
function element(id, dataset = {}) {
  return {id, dataset, attrs: {}, events: {}, hidden: false, textContent: '',
    setAttribute(k,v) {this.attrs[k]=v;}, addEventListener(k,fn) {this.events[k]=fn;},
    scrollIntoView() {this.scrolled=true;}, closest() {return null;}};
}
function desk({stored='{}', denied=false, hash='', population='one'}={}) {
  const orders=['DEGEN','SWING','UNKNOWN'].map((f,i)=>element('order-'+i,{orderFamily:f}));
  orders.forEach(o=>{o.closest=s=>s==='[data-order-family]'?o:null;});
  const choices=['DEGEN','SWING','SCOPE'].map(f=>element(f,{familyChoice:f}));
  const filters=['ALL','DEGEN','SWING','SCOPE'].map(f=>element(f,{filterFamily:f}));
  const label=element('label');
  const events=Array.from({length:12},(_,i)=>element('event-'+i,{eventKind:i%2?'FILL':'REVIEW'}));
  const select=element('activity-filter');select.value='ALL';
  const more=element('activity-more');const empty=element('activity-empty');
  const detail=element('detail');detail.parentElement={closest(){return null;}};
  const point=element('point',{pointDetail:'Oct 09, 2026 11:00:00 EDT · $1000.01'});
  const pointLabel=element('point-label');point.closest=()=>({querySelector:()=>pointLabel});
  const trades=element('trades');const tradesMore=element('trades-more');
  const ids=[...orders,select,more,empty,detail,trades,tradesMore];
  const groups={'[data-order-family]':orders,'[data-family-choice]':choices,'[data-filter-family]':filters,
    '[data-family-label]':[label],'a[href^="#"]':[],'details[id]':[detail],
    '[data-point-detail]':[point],'[data-event-kind]':events};
  const keys=[];const listeners={};
  vm.runInNewContext(source,{AbortController,document:{addEventListener(){},body:{dataset:{population}},getElementById:id=>ids.find(e=>e.id===id),
    querySelectorAll:s=>groups[s]||[]},location:{hash},matchMedia:()=>({matches:false}),
    sessionStorage:{getItem(k){keys.push(k);if(denied)throw Error('denied');return stored;},
      setItem(k,v){keys.push(k);if(denied)throw Error('denied');stored=v;}},
    addEventListener:(k,fn)=>{listeners[k]=fn;}});
  return {orders,choices,filters,label,events,select,more,empty,detail,point,pointLabel,keys,listeners,trades,tradesMore,
    saved:()=>JSON.parse(stored)};
}
test('family filter applies only to attributed order cards',()=>{
 const d=desk();d.filters[2].events.click();
 assert.deepEqual(d.orders.map(o=>o.hidden),[true,false,true]);
 assert.equal(d.saved().family,'SWING');assert.equal(d.label.textContent,'SWING');
 assert.equal(d.events.filter(e=>!e.hidden).length,3);
});
test('missing family selection resets to All instead of hiding all evidence',()=>{
 const d=desk({stored:'{"family":"SCOPE"}'});
 assert.equal(d.saved().family,'ALL');assert.ok(d.orders.every(o=>!o.hidden));
});
test('deep-linked order clears conflicting family filter',()=>{
 const d=desk({stored:'{"family":"SWING"}',hash:'#order-0'});
 assert.equal(d.saved().family,'ALL');assert.equal(d.orders[0].scrolled,true);
});
test('activity shows three rows, expands on request, and filters real rows',()=>{
 const d=desk();assert.equal(d.events.filter(e=>!e.hidden).length,3);
 d.more.events.click();assert.equal(d.events.filter(e=>!e.hidden).length,12);
 d.select.value='FILL';d.select.events.change();
 assert.equal(d.events.filter(e=>!e.hidden).length,3);assert.equal(d.more.hidden,false);
 assert.equal(d.more.attrs['aria-expanded'],'false');
 d.more.events.click();assert.equal(d.events.filter(e=>!e.hidden).length,6);
 assert.equal(d.more.attrs['aria-expanded'],'true');
 d.more.events.click();assert.equal(d.events.filter(e=>!e.hidden).length,3);
 assert.ok(d.events.filter(e=>!e.hidden).every(e=>e.dataset.eventKind==='FILL'));
});
test('point inspection works by focus and tap with exact saved values',()=>{
 const d=desk();d.point.events.focus();assert.equal(d.pointLabel.textContent,d.point.dataset.pointDetail);
 d.pointLabel.textContent='';d.point.events.click();assert.equal(d.pointLabel.textContent,d.point.dataset.pointDetail);
});
test('state is population scoped and storage denial leaves interactions usable',()=>{
 const a=desk({population:'alpha'}),b=desk({population:'beta'});
 assert.ok(a.keys.every(k=>k.endsWith(':alpha')));assert.ok(b.keys.every(k=>k.endsWith(':beta')));
 const d=desk({denied:true});d.filters[1].events.click();assert.equal(d.orders[0].hidden,false);
 for(const stored of ['null','[]','3','{broken']) assert.ok(desk({stored}).orders.every(o=>!o.hidden));
});
test('disclosures persist their own state without executing a refresh',()=>{
 const d=desk({stored:'{"details":{"detail":true}}'});assert.equal(d.detail.open,true);
 d.detail.open=false;d.detail.events.toggle();assert.equal(d.saved().details.detail,false);
});

test('Trades starts collapsed and toggles independently of activity',()=>{
 const d=desk();assert.equal(d.trades.dataset.expanded,'false');assert.equal(d.tradesMore.hidden,false);
 d.tradesMore.events.click();assert.equal(d.trades.dataset.expanded,'true');
 assert.equal(d.saved().tradesExpanded,true);assert.equal(d.tradesMore.textContent,'Collapse trades');
 assert.equal(d.more.attrs['aria-expanded'],'false');
 d.tradesMore.events.click();assert.equal(d.trades.dataset.expanded,'false');
});
test('Trades restores expansion and expands to reveal a linked order',()=>{
 assert.equal(desk({stored:'{"tradesExpanded":true}'}).trades.dataset.expanded,'true');
 assert.equal(desk({hash:'#order-0'}).trades.dataset.expanded,'true');
 const d=desk({denied:true});d.tradesMore.events.click();assert.equal(d.trades.dataset.expanded,'true');
});
