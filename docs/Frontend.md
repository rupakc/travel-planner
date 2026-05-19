# Frontend

The Travel Planner frontend is a React 18 single-page application built with Vite 6 and styled with Tailwind CSS 4. This page covers the application structure, state management, the Web Worker SSE approach, and the key pages.

---

## Project structure

```
frontend/
├── src/
│   ├── pages/
│   │   ├── LoginPage.jsx
│   │   ├── ChangePasswordPage.jsx
│   │   ├── SearchPage.jsx
│   │   ├── ResultsPage.jsx
│   │   ├── ChatPage.jsx
│   │   ├── PlansPage.jsx
│   │   └── PreferencesPage.jsx
│   ├── components/
│   │   ├── Layout.jsx
│   │   ├── Navbar.jsx
│   │   ├── SearchForm.jsx
│   │   ├── ResultsSection.jsx
│   │   ├── SectionCard.jsx
│   │   └── ItineraryView.jsx
│   ├── context/
│   │   ├── AuthContext.jsx
│   │   └── SearchDataContext.jsx
│   ├── workers/
│   │   ├── sseWorker.js
│   │   └── chatWorker.js
│   ├── services/
│   │   └── api.js
│   └── main.jsx
├── index.html
├── vite.config.js
└── tailwind.config.js
```

---

## Routing

React Router 7 handles client-side routing. Routes are defined in `main.jsx`. Protected routes check `AuthContext` and redirect to `/login` if the user is not authenticated.

| Path | Page | Protected |
|---|---|---|
| `/login` | LoginPage | No |
| `/change-password` | ChangePasswordPage | Yes |
| `/` | SearchPage | Yes |
| `/results` | ResultsPage | Yes |
| `/chat` | ChatPage | Yes |
| `/plans` | PlansPage | Yes |
| `/preferences` | PreferencesPage | Yes |

After login, if `requires_password_change` is `true`, the router immediately pushes to `/change-password` and blocks all other routes until the password is changed.

---

## AuthContext

`AuthContext` (`src/context/AuthContext.jsx`) is a React context that wraps the entire application. It manages:

- **Authentication state** — whether a user is logged in, their JWT token, username, and role
- **Token storage** — the JWT is stored in `localStorage` and restored on page load
- **Auto-logout** — on 401 responses from the API, `AuthContext` clears the token and redirects to `/login`
- **User preferences** — fetches and caches preferences from `/api/preferences` on login so they are available across pages without repeated API calls

Key values exposed by the context:

```jsx
const { user, token, isAuthenticated, login, logout, preferences, updatePreferences } = useAuth();
```

---

## SearchDataContext

`SearchDataContext` (`src/context/SearchDataContext.jsx`) manages the state shared between the search form and the results page. Without this context, navigating from search to results would lose the in-progress streaming state.

It holds:

- **Search form values** — destination, dates, budget, nationality, interests (persisted across navigation)
- **Streaming results** — a `Map` of section name → content, updated as SSE events arrive
- **Streaming status** — `idle`, `streaming`, `complete`, `error`
- **Worker reference** — a ref to the active `sseWorker.js` instance

When the user submits the search form, `SearchDataContext` starts the Web Worker, which opens the SSE connection and posts parsed events back. As events arrive, the context updates the results map and React re-renders only the affected section card.

```jsx
const { searchParams, results, status, submitSearch, clearResults } = useSearchData();
```

---

## Web Worker SSE approach

### Why a Web Worker?

The SSE stream from a travel search runs for 25–30 seconds and emits 10–15 events of varying size. Parsing each event on the main thread — even though parsing itself is fast — risks being blocked by a React re-render cycle and can cause noticeable jank on lower-end devices. More importantly, if the main thread is busy (e.g. animations, user interactions), it may delay reading from the SSE buffer, which can cause events to pile up.

The Web Worker runs on a separate OS thread. It opens the SSE connection, reads and parses events, and posts structured messages to the main thread. The main thread only handles React state updates, which is its proper job.

### How it works

`sseWorker.js` (loaded via `new Worker(new URL('./workers/sseWorker.js', import.meta.url))`):

```javascript
// In sseWorker.js
self.onmessage = function(e) {
  const { url, token } = e.data;
  const eventSource = new EventSource(url + '?token=' + token);

  eventSource.onmessage = function(event) {
    if (event.data === '[DONE]') {
      self.postMessage({ type: 'done' });
      eventSource.close();
      return;
    }
    const parsed = JSON.parse(event.data);
    self.postMessage({ type: 'section', section: parsed.section, content: parsed.content });
  };

  eventSource.onerror = function() {
    self.postMessage({ type: 'error', message: 'SSE connection failed' });
    eventSource.close();
  };
};
```

In `SearchDataContext`, the main thread listens:
```javascript
worker.onmessage = (e) => {
  if (e.data.type === 'section') {
    setResults(prev => new Map(prev).set(e.data.section, e.data.content));
  } else if (e.data.type === 'done') {
    setStatus('complete');
  }
};
```

The same pattern is used in `chatWorker.js` for the chat SSE stream.

---

## Key pages

### SearchPage

The landing page after login. Contains `SearchForm`, which collects destination, dates, nationality, budget, and interests. Pre-populates from user preferences if available. On submit, calls `SearchDataContext.submitSearch()` and navigates to `/results`.

### ResultsPage

Renders the streaming trip plan. Sections appear as they arrive — the page does not wait for all sections before showing anything. Each section is wrapped in `SectionCard`, which handles its own loading/error/content states. The itinerary (Phase 2) renders last, after all Phase 1 sections are visible.

A "Save Plan" button appears when streaming is complete, which calls `POST /api/plans` and confirms with a toast notification.

### ChatPage

A chat interface with message history. The user types follow-up questions; the ChatAgent streams responses. Each response token appears as it is generated, similar to ChatGPT. Trip context (destination, dates) is included in each request so the agent does not need the user to repeat it.

---

## Vite dev proxy

In development, the Vite dev server proxies `/api/*` to `http://localhost:8001`. This avoids CORS issues during development and mirrors the production setup where the frontend nginx container proxies API requests to the backend service. The proxy config is in `vite.config.js`:

```javascript
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8001',
      changeOrigin: true
    }
  }
}
```

---

## Tailwind CSS setup

Tailwind CSS 4 (JIT mode by default) is configured in `tailwind.config.js`. The design uses a dark-first palette. Custom theme extensions include the travel planner's brand colours and responsive breakpoints. Tailwind classes are purged from unused HTML in production builds, keeping the CSS bundle minimal.

---

## API service layer

`src/services/api.js` is a thin wrapper around `fetch` that:

- Reads the JWT token from `AuthContext` via a module-level accessor
- Adds `Authorization: Bearer <token>` to all requests
- Handles 401 responses by triggering `AuthContext.logout()`
- Provides typed functions for each endpoint (`login`, `getPlans`, `savePlan`, etc.)

Components never call `fetch` directly — they always use functions from `api.js`. This makes it straightforward to add request interceptors, logging, or retry logic in one place.
