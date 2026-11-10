// Applies the saved theme before any CSS loads, so dark-mode users see no light
// flash. Loaded from index.html as a render-blocking classic script: an external
// file because the production CSP is `script-src 'self'` (no inline scripts).
// Light is the default; the OS setting is consulted only when 'system' was chosen.
// Mirrors src/theme/ThemeContext.jsx; #121a2b is design/tokens.json dark.white.
(function () {
  var t = null, dark = false, root = document.documentElement;
  try { t = localStorage.getItem('tp_theme'); } catch (e) { /* storage blocked */ }
  try {
    dark = t === 'dark' || (t === 'system' && !!window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
  } catch (e) { /* no matchMedia */ }
  if (dark) root.classList.add('dark');
  root.style.colorScheme = dark ? 'dark' : 'light';
  var m = document.querySelector('meta[name="theme-color"]');
  if (m && dark) m.setAttribute('content', '#121a2b');
})();
