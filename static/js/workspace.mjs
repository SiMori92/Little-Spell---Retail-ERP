export const artworkStorageKey = 'little-spell-ledger-artwork-v1';
const visitStorageKey = `${artworkStorageKey}-visit`;

// One bag contains every work. Storage denial still permits an in-memory bag.
export function createArtworkShuffler(artworks, random = Math.random) {
  const ids = artworks.map(art => art.id);
  let memory = { remaining: [], last: null };
  return function next(storage) {
    let state = memory;
    try {
      const parsed = JSON.parse(storage?.getItem(artworkStorageKey) ?? 'null');
      if (parsed && Array.isArray(parsed.remaining) &&
          parsed.remaining.every(id => ids.includes(id)) &&
          new Set(parsed.remaining).size === parsed.remaining.length &&
          (parsed.last === null || ids.includes(parsed.last)) &&
          !parsed.remaining.includes(parsed.last)) state = parsed;
    } catch { /* Damaged or blocked storage uses the in-memory bag. */ }
    const remaining = [...state.remaining];
    if (!remaining.length) {
      remaining.push(...ids);
      for (let i = remaining.length - 1; i > 0; i--) {
        const j = Math.floor(random() * (i + 1));
        [remaining[i], remaining[j]] = [remaining[j], remaining[i]];
      }
      if (remaining.length > 1 && remaining[0] === state.last) {
        const j = 1 + Math.floor(random() * (remaining.length - 1));
        [remaining[0], remaining[j]] = [remaining[j], remaining[0]];
      }
    }
    const id = remaining.shift();
    memory = { remaining, last: id };
    try { storage?.setItem(artworkStorageKey, JSON.stringify(memory)); } catch { /* Optional persistence. */ }
    return artworks.find(art => art.id === id);
  };
}

export function artworkForVisit({ artworks, next, storage, pathname, search, navigationType }) {
  let art;
  try {
    const previous = JSON.parse(storage?.getItem(visitStorageKey) ?? 'null');
    // Django filter forms load a new document. Preserve art when only its query
    // changed; a deliberate refresh or history traversal still advances the bag.
    if (navigationType === 'navigate' && previous?.pathname === pathname && previous.search !== search) {
      art = artworks.find(item => item.id === previous.id);
    }
  } catch { /* Ignore untrusted session data. */ }
  art ??= next(storage);
  try { storage?.setItem(visitStorageKey, JSON.stringify({ pathname, search, id: art.id })); } catch { /* Optional persistence. */ }
  return art;
}

function initializeArtwork(panel) {
  const catalog = panel.querySelector('[data-artwork-catalog]');
  const artworks = [...catalog.content.children].map(node => ({ ...node.dataset }));
  if (!artworks.length) return;
  const next = createArtworkShuffler(artworks);
  let storage = null;
  try { storage = window.sessionStorage; } catch { /* In-memory fallback. */ }
  let pending;
  function display(art) {
    if (pending) pending.onload = pending.onerror = null;
    const image = new Image();
    pending = image;
    image.onload = () => {
      panel.style.backgroundImage = `url("${art.image}")`;
      panel.querySelector('a')?.remove();
      const caption = document.createElement('a');
      caption.className = 'artwork-caption';
      caption.href = art.source;
      caption.target = '_blank';
      caption.rel = 'noopener noreferrer';
      caption.textContent = `${art.artist} · ${art.title}, ${art.year}`;
      caption.setAttribute('aria-label', `${art.title} by ${art.artist}, ${art.year}. Explore on Google Arts & Culture (opens in a new tab).`);
      panel.append(caption);
    };
    image.onerror = () => {
      panel.style.backgroundImage = '';
      panel.querySelector('a')?.remove();
    };
    image.src = art.image;
  }
  display(artworkForVisit({ artworks, next, storage, pathname:location.pathname, search:location.search,
    navigationType:performance.getEntriesByType('navigation')[0]?.type ?? 'navigate' }));
  window.addEventListener('pageshow', event => { if (event.persisted) display(next(storage)); });
  window.addEventListener('pagehide', () => {
    if (pending) pending.onload = pending.onerror = null;
  });
}

function initializeLibrarySearch() {
  const control = document.querySelector('[data-library-search]');
  if (!control) return;
  control.hidden = false;
  const input = control.querySelector('input');
  const groups = [...document.querySelectorAll('.report-group')];
  const total = document.querySelectorAll('.report-card').length;
  const counter = document.getElementById('library-count');
  const empty = document.getElementById('library-no-matches');
  function update() {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const group of groups) {
      let groupVisible = 0;
      for (const card of group.querySelectorAll('.report-card')) {
        const match = card.textContent.toLocaleLowerCase().includes(query);
        card.hidden = !match;
        if (match) groupVisible++;
      }
      group.hidden = groupVisible === 0;
      group.querySelector('.section-caption').textContent = `${groupVisible} views`;
      visible += groupVisible;
    }
    counter.textContent = `${visible} of ${total} reports`;
    empty.hidden = visible !== 0;
  }
  input.addEventListener('input', update);
  update();
}

function initializeTableSearch() {
  const control = document.querySelector('[data-table-search]');
  if (!control) return;
  control.hidden = false;
  const input = control.querySelector('input');
  const bodies = [...document.querySelectorAll('[data-report-body]')];
  const counter = document.getElementById('row-count');
  const empty = document.getElementById('no-matches');
  input.addEventListener('input', () => {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const body of bodies) {
      for (const row of body.querySelectorAll('tr:not([data-empty-row])')) {
        row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
        if (!row.hidden) visible++;
      }
    }
    counter.textContent = String(visible);
    empty.hidden = visible !== 0;
  });
}

if (typeof document !== 'undefined') {
  document.querySelectorAll('[data-artwork-header]').forEach(initializeArtwork);
  initializeLibrarySearch();
  initializeTableSearch();
}
