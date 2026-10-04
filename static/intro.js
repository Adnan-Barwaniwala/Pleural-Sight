'use strict';
(() => {
  const scenes = [...document.querySelectorAll('.scroll-scene')];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const canvas = document.getElementById('cosmos');
  const ctx = canvas.getContext('2d');
  let width, height, stars = [], scroll = 0, queued = false;
  function resize() {
    width = innerWidth; height = innerHeight;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = width * ratio; canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    // Deterministic star field: no external assets or persistent animation loop.
    let seed = 139;
    const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    stars = Array.from({length:Math.min(220, Math.round(width / 7))}, () => ({x:random(),y:random(),r:.3+random()*1.1,depth:.1+random()*.9}));
    update();
  }
  function draw() {
    ctx.clearRect(0,0,width,height);
    stars.forEach(star => {
      const y = ((star.y*height - (reduced.matches ? 0 : scroll*star.depth*.12))%height+height)%height;
      ctx.fillStyle = `rgba(162,194,244,${.2+star.depth*.5})`;
      ctx.beginPath();ctx.arc(star.x*width,y,star.r,0,Math.PI*2);ctx.fill();
    });
  }
  function update() {
    queued = false; scroll = scrollY;
    scenes.forEach(scene => {
      const rect = scene.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > height) return;
      const progress = reduced.matches ? 0 : Math.min(1,Math.max(0,-rect.top/Math.max(1,rect.height-height)));
      scene.style.setProperty('--p',progress.toFixed(4));
    });
    draw();
  }
  addEventListener('scroll', () => {if(!queued){queued=true;requestAnimationFrame(update);}}, {passive:true});
  addEventListener('resize',resize,{passive:true});
  reduced.addEventListener('change',resize);
  resize();
})();
