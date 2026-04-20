const adminParts = [
  '/admin/sidebar.html',
];

const viewFiles = [
  { id: 'view-brand',     file: '/admin/views/brand.html' },
  { id: 'view-objective', file: '/admin/views/objective.html' },
  { id: 'view-pipeline',  file: '/admin/views/pipeline.html' },
  { id: 'view-todo',      file: '/admin/views/requirements.html' },
  { id: 'view-platforms', file: '/admin/views/platforms.html' },
  { id: 'view-schedule',  file: '/admin/views/schedule.html' },
  { id: 'view-plan1',     file: '/admin/views/plan1.html' },
];

const views = ['brand','objective','pipeline','todo','platforms','schedule','plan1'];
const titles = {
  brand:     'Brand Identity',
  objective: 'Tool Objective',
  pipeline:  'Content Pipeline',
  todo:      'Requirements',
  platforms: 'Platforms & Voice',
  schedule:  'Weekly Schedule',
  plan1:     'Plan 1 · Know Elaina'
};

function showView(name) {
  views.forEach(v => {
    document.getElementById('view-' + v).style.display = (v === name) ? '' : 'none';
  });
  document.querySelectorAll('.sidebar-link:not(.soon)').forEach(el => el.classList.remove('active'));
  const navLinks = document.querySelectorAll('.sidebar-link:not(.soon)');
  const map = { brand:0, objective:1, pipeline:2, todo:3, platforms:4, schedule:5, plan1:6 };
  if (navLinks[map[name]] !== undefined) navLinks[map[name]].classList.add('active');
  document.getElementById('topbar-title').textContent = titles[name] || 'Admin';
}

function toggleTodo(el) { el.classList.toggle('done'); }

let navOpen = false;
function toggleNav() {
  navOpen = !navOpen;
  document.getElementById('nav-extra').classList.toggle('open', navOpen);
  document.getElementById('nav-toggle-icon').classList.toggle('open', navOpen);
}

async function init() {
  const app = document.getElementById('app');

  // Load sidebar
  const sidebarHtml = await fetch('/admin/sidebar.html').then(r => r.text());

  // Load all views
  const viewHtmls = await Promise.all(viewFiles.map(v => fetch(v.file).then(r => r.text())));

  // Build the main layout
  // The admin layout is: sidebar (aside) + main (with topbar + content area containing all views)
  const viewsHtml = viewFiles.map((v, i) => viewHtmls[i]).join('\n');

  app.innerHTML = `
${sidebarHtml}
<main class="main">
  <div class="topbar">
    <div class="topbar-title" id="topbar-title">Brand Identity</div>
    <div class="topbar-actions">
      <span class="badge badge-green"><span class="badge-dot"></span>Live</span>
      <span class="badge badge-blue">BBB Admin</span>
    </div>
  </div>
  <div class="content">
${viewsHtml}
  </div>
</main>
`;

  // Make showView, toggleTodo, toggleNav globally accessible (called from inline onclick)
  window.showView = showView;
  window.toggleTodo = toggleTodo;
  window.toggleNav = toggleNav;
}

init();
