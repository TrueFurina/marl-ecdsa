// Non-invasive navigation enhancements; existing dashboard.js owns data and charts.
(() => {
  const menu = document.getElementById('mobile-menu');
  const sidebar = document.querySelector('.sidebar');
  const breadcrumb = document.getElementById('current-location');
  const update = () => {
    const active = document.querySelector('.nav-tab.active');
    if (active && breadcrumb) breadcrumb.textContent = active.querySelector('span:nth-child(2)')?.textContent || '总览';
  };
  document.querySelectorAll('.nav-tab').forEach(tab => tab.addEventListener('click', () => {
    sidebar?.classList.remove('mobile-open');
    menu?.setAttribute('aria-expanded', 'false');
    update();
  }));
  menu?.addEventListener('click', () => {
    const opened = sidebar.classList.toggle('mobile-open');
    menu.setAttribute('aria-expanded', String(opened));
  });
  document.addEventListener('click', e => {
    if (window.innerWidth <= 850 && sidebar?.classList.contains('mobile-open') && !sidebar.contains(e.target) && e.target !== menu) {
      sidebar.classList.remove('mobile-open'); menu?.setAttribute('aria-expanded','false');
    }
  });
  new MutationObserver(update).observe(document.querySelector('.nav-tabs'), {subtree:true,attributes:true,attributeFilter:['class']});
  update();
})();
