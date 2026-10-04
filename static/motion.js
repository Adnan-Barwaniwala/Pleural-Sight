'use strict';
// Image presentation and workspace motion. Analysis and intake stay in app.js.
(() => {
  const shell = document.querySelector('.viewer-shell');
  const viewer = document.getElementById('viewer');
  const modes = [...document.querySelectorAll('[data-view-mode]')];
  const slider = document.getElementById('swipe-position');
  const hint = document.getElementById('view-mode-hint');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let mode = 'side', frame = 'prior', observer;
  function setFrame(next) {
    frame = next;
    shell.dataset.frame = frame;
    if (mode === 'flicker') hint.textContent = 'Click image to switch';
  }
  function animate(element, name) {
    element.classList.remove(name);
    window.requestAnimationFrame(() => {
      element.classList.add(name);
      window.setTimeout(() => element.classList.remove(name), 650);
    });
  }
  function choose(next) {
    mode = next;
    shell.dataset.mode = mode;
    modes.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.viewMode === mode)));
    viewer.tabIndex = mode === 'flicker' ? 0 : -1;
    if (mode === 'flicker') { viewer.setAttribute('role', 'button'); viewer.setAttribute('aria-label', 'Switch earlier and current image'); }
    else { viewer.removeAttribute('role'); viewer.removeAttribute('aria-label'); }
    document.querySelector('.swipe-control').hidden = mode !== 'swipe';
    setFrame('prior');
    hint.textContent = mode === 'side' ? 'Earlier & current' : mode === 'swipe' ? 'Drag to compare' : 'Click image to switch';
    animate(shell, 'mode-enter');
  }
  modes.forEach(button => button.addEventListener('click', () => choose(button.dataset.viewMode)));
  let pointerStart;
  viewer.addEventListener('pointerdown', event => { pointerStart = {x:event.clientX,y:event.clientY}; });
  viewer.addEventListener('click', event => {
    if (mode !== 'flicker') return;
    if (pointerStart && Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>6) return;
    setFrame(frame === 'prior' ? 'current' : 'prior');
  });
  viewer.addEventListener('keydown', event => {
    if (mode === 'flicker' && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault(); setFrame(frame === 'prior' ? 'current' : 'prior');
    }
  });
  function swipe(value) {
    const position = Math.min(100, Math.max(0, Number(value)));
    slider.value = String(position);
    shell.style.setProperty('--swipe-position', position + '%');
  }
  slider.addEventListener('input', () => swipe(slider.value));
  const grip = document.querySelector('.swipe-grip');
  let dragging = false;
  function drag(event) {
    if (!dragging) return;
    const rect = viewer.getBoundingClientRect();
    swipe((event.clientX - rect.left) / rect.width * 100);
  }
  grip.addEventListener('pointerdown', event => {
    dragging = true;
    grip.setPointerCapture(event.pointerId);
    drag(event);
  });
  grip.addEventListener('pointermove', drag);
  grip.addEventListener('pointerup', () => dragging = false);
  grip.addEventListener('pointercancel', () => dragging = false);
  new MutationObserver(() => {
    setFrame('prior');
    swipe(50);
    animate(shell, 'case-transition');
  }).observe(document.getElementById('prior-image'), {attributes:true, attributeFilter:['src']});
  function configureMotion() {
    observer?.disconnect();
    document.documentElement.classList.toggle('motion-enabled', !reduced.matches);
    if ('IntersectionObserver' in window && !reduced.matches) {
      observer = new IntersectionObserver(entries => entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      }), {threshold:.08});
      document.querySelectorAll('.workspace-reveal').forEach(element => observer.observe(element));
    } else document.documentElement.classList.remove('motion-enabled');
  }
  reduced.addEventListener('change', configureMotion);
  configureMotion();
  choose('side');
})();
