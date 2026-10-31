/* DevPilot AI — Cinematic Motion V4 (presentation only).
   No API requests, login state, Angular bindings, or application state changed. */
(()=>{
  'use strict';
  const root=document.documentElement;
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)');
  const fine=window.matchMedia('(pointer: fine)');
  let mx=0.56,my=0.38, x=mx,y=my, scroll=0, raf=0, lastRoute='';
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const set=(name,v)=>root.style.setProperty(name,v);
  const tick=()=>{
    raf=0;
    if(reduce.matches||document.hidden)return;
    x+=(mx-x)*.095; y+=(my-y)*.095;
    set('--dp-mx',(x*100).toFixed(2)+'%');
    set('--dp-my',(y*100).toFixed(2)+'%');
    set('--dp-shift-x',((x-.5)*52).toFixed(1)+'px');
    set('--dp-shift-y',((y-.5)*32-scroll*.14).toFixed(1)+'px');
    set('--dp-scroll-shift',(-scroll*.12).toFixed(1)+'px');
    if(Math.abs(x-mx)>.002||Math.abs(y-my)>.002)raf=requestAnimationFrame(tick);
  };
  const schedule=()=>{if(!raf&&!reduce.matches&&!document.hidden)raf=requestAnimationFrame(tick)};
  if(fine.matches){
    document.addEventListener('pointermove',e=>{
      if(e.pointerType==='touch')return;
      mx=clamp(e.clientX/innerWidth,0,1); my=clamp(e.clientY/innerHeight,0,1);
      schedule();
      const card=e.target.closest?.('app-card, .help-card');
      if(card){
        const r=card.getBoundingClientRect();
        card.style.setProperty('--dp-card-x',((e.clientX-r.left)/r.width*100).toFixed(1)+'%');
        card.style.setProperty('--dp-card-y',((e.clientY-r.top)/r.height*100).toFixed(1)+'%');
        card.style.setProperty('--dp-rot-y',clamp((e.clientX-r.left-r.width/2)/r.width*5,-2.5,2.5).toFixed(2)+'deg');
        card.style.setProperty('--dp-rot-x',clamp((r.height/2-(e.clientY-r.top))/r.height*4,-2,2).toFixed(2)+'deg');
      }
    },{passive:true});
    document.addEventListener('pointerout',e=>{
      const card=e.target.closest?.('app-card, .help-card');
      if(card&&!card.contains(e.relatedTarget)){
        card.style.removeProperty('--dp-rot-x');card.style.removeProperty('--dp-rot-y');
      }
    },{passive:true});
  }
  document.addEventListener('scroll',e=>{
    const target=e.target;
    scroll=clamp((target?.scrollTop??0)||window.scrollY||0,0,800);
    schedule();
  },{capture:true,passive:true});
  const route=()=>{
    const current=location.hash||location.pathname;
    if(current===lastRoute)return;
    lastRoute=current;
    const main=document.querySelector('.content__main');
    if(!main)return;
    main.classList.remove('dp-route-enter');
    void main.offsetWidth;
    if(!reduce.matches)main.classList.add('dp-route-enter');
  };
  window.addEventListener('hashchange',()=>requestAnimationFrame(route));
  // Angular content insertion may lag behind hash change: watch only main's child list.
  const observer=new MutationObserver(()=>route());
  const attach=()=>{
    const main=document.querySelector('.content__main');
    if(!main){requestAnimationFrame(attach);return;}
    observer.observe(main,{childList:true});route();schedule();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',attach,{once:true});else attach();
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule()});

  // Visual-only re-entry for the newly rendered Angular route title.
  const titleObserver=new MutationObserver(()=>{
    const title=document.querySelector('.content__main h1');
    if(!title||title.dataset.dpV7Done)return;
    title.dataset.dpV7Done='1';
    if(!reduce.matches){title.classList.add('dp-v7-headline-flash');}
  });
  const startTitleObserver=()=>{
    const main=document.querySelector('.content__main');
    if(main)titleObserver.observe(main,{childList:true,subtree:true});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',startTitleObserver,{once:true});else startTitleObserver();

  // Replay a restrained reveal for visible headings after navigation/scroll.
  const seen = new WeakSet();
  const visible = new IntersectionObserver(entries=>{
    if(reduce.matches)return;
    for(const entry of entries){
      if(!entry.isIntersecting || seen.has(entry.target))continue;
      seen.add(entry.target);
      entry.target.classList.add('dp-v5-visible');
    }
  },{threshold:.16,rootMargin:'0px 0px -35px 0px'});
  const watch = ()=>{
    document.querySelectorAll('.content__main h2,.content__main h3').forEach(el=>{
      if(!seen.has(el))visible.observe(el);
    });
  };
  new MutationObserver(watch).observe(document.documentElement,{childList:true,subtree:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();

})();
