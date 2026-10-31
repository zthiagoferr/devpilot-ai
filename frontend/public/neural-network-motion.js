/* DevPilot AI — decorative monochrome neural network. No app/API/auth state access. */
(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = window.matchMedia('(max-width: 720px)');
  const canvas = document.createElement('canvas');
  canvas.className = 'dp-neural-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  const ctx = canvas.getContext('2d', {alpha: true});
  if (!ctx) return;
  let points = [], width = 0, height = 0, scale = 1, frame = 0, raf = 0;
  let px = -1000, py = -1000;
  let lastTime = 0;
  const random = (a,b) => a + Math.random() * (b-a);
  function resize() {
    const host = document.querySelector('app-shell .content');
    if (!host) return;
    const b = host.getBoundingClientRect();
    width = Math.max(1, Math.round(b.width));
    height = Math.max(1, Math.round(window.innerHeight));
    scale = Math.min(window.devicePixelRatio || 1, 1.7);
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    const count = reduced.matches ? 0 : Math.min(narrow.matches ? 24 : 54, Math.max(12, Math.floor(width * height / 20500)));
    points = Array.from({length:count}, () => ({ x:random(0,width), y:random(0,height), dx:random(-.23,.23), dy:random(-.20,.20), r:random(.75,2.0), phase:random(0,6.28) }));
  }
  function draw(time) {
    raf = 0;
    if (document.hidden || reduced.matches) { ctx.clearRect(0,0,width,height); return; }
    // Throttle to about 30 fps; animation remains decorative and lightweight.
    if (time - lastTime < 30) { raf = requestAnimationFrame(draw); return; }
    const delta = Math.min(1.6, (time-lastTime || 33)/33);
    lastTime = time;
    ctx.clearRect(0,0,width,height);
    const limit = narrow.matches ? 108 : 150;
    points.forEach(p => {
      p.x += p.dx*delta; p.y += p.dy*delta;
      if (p.x < -15) p.x = width+15;
      if (p.x > width+15) p.x = -15;
      if (p.y < -15) p.y = height+15;
      if (p.y > height+15) p.y = -15;
    });
    for (let i=0;i<points.length;i++) {
      const a=points[i];
      for(let j=i+1;j<points.length;j++) {
        const b=points[j], dx=a.x-b.x,dy=a.y-b.y;
        const d2=dx*dx+dy*dy;
        if(d2>limit*limit) continue;
        const nearPointer = Math.max(0, 1 - Math.hypot((a.x+b.x)*.5-px,(a.y+b.y)*.5-py)/240);
        const opacity=(1-Math.sqrt(d2)/limit)*(.13 + nearPointer*.18);
        ctx.strokeStyle=`rgba(255,255,255,${opacity.toFixed(3)})`;
        ctx.lineWidth=.8;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      }
      const pointerBoost=Math.max(0,1-Math.hypot(a.x-px,a.y-py)/190);
      const pulse=(Math.sin(time*.0013+a.phase)+1)*.5;
      ctx.fillStyle=`rgba(255,255,255,${(.24+pulse*.20+pointerBoost*.32).toFixed(3)})`;
      ctx.beginPath();ctx.arc(a.x,a.y,a.r+pointerBoost*.65,0,Math.PI*2);ctx.fill();
    }
    frame++;
    raf=requestAnimationFrame(draw);
  }
  function start() { cancelAnimationFrame(raf); raf=0; resize(); lastTime=0; if(!reduced.matches&&!document.hidden) raf=requestAnimationFrame(draw); }
  function attach() {
    const host=document.querySelector('app-shell .content');
    if(!host) { requestAnimationFrame(attach); return; }
    host.prepend(canvas);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => start()) : null;
    ro?.observe(host);
    window.addEventListener('resize',start,{passive:true});
    host.addEventListener('pointermove', event => {
      const b=host.getBoundingClientRect();px=event.clientX-b.left;py=event.clientY-b.top;
    },{passive:true});
    host.addEventListener('pointerleave',()=>{px=-1000;py=-1000;},{passive:true});
    document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(raf);raf=0;}else start();});
    reduced.addEventListener?.('change',start);
    narrow.addEventListener?.('change',start);
    start();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',attach,{once:true}); else attach();
})();
