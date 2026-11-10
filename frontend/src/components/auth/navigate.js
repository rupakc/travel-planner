// Full-page navigation to an OAuth start URL. Kept in its own module so tests
// can replace it (jsdom cannot navigate).
export function navigateTo(url) {
  window.location.assign(url)
}
