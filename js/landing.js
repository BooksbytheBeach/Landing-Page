const sections = [
  '/content/landing/nav.html',
  '/content/landing/hero.html',
  '/content/landing/about.html',
  '/content/landing/quote.html',
  '/content/landing/how.html',
  '/content/landing/testimonials.html',
  '/content/landing/cta.html',
  '/content/landing/footer.html',
];

async function init() {
  const app = document.getElementById('app');
  const parts = await Promise.all(sections.map(url => fetch(url).then(r => r.text())));
  app.innerHTML = parts.join('\n');

  // Scroll nav shadow
  const nav = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  });

  // Intersection observer for reveal animations
  const revealItems = document.querySelectorAll('.feature-card, .step-item, .t-card');
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
    });
  }, { threshold: 0.12 });
  revealItems.forEach(el => io.observe(el));

  // Smooth scroll for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const target = document.querySelector(this.getAttribute('href'));
      if (target) { e.preventDefault(); target.scrollIntoView({ behavior: 'smooth' }); }
    });
  });
}

init();
