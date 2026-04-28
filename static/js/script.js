const API_ENTRIES = '/api/entries';
const API_STATS = '/api/stats';
const BATCH_SIZE = 15;

// State global
let currentType = '', currentSource = '', currentTag = '', currentSearch = '', currentSort = 'newest';
let currentPage = 1, currentTotal = 0, isLoadingMore = false;

// Fungsi buat visitor ID yang panjang & unik
function generateVisitorId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback UUID v4 sederhana (36 karakter)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

let visitorId = localStorage.getItem('visitor_id');
if (!visitorId || visitorId.length < 8) {
  visitorId = generateVisitorId();
  localStorage.setItem('visitor_id', visitorId);
}

// DOM elements
const grid = document.getElementById('cardGrid');
const loader = document.getElementById('loader');
const emptyState = document.getElementById('emptyState');
const clearFiltersBtn = document.getElementById('clearFiltersBtn');
const searchInput = document.getElementById('searchInput');
const typeSelect = document.getElementById('typeSelect');
const sourceInput = document.getElementById('sourceInput');
const tagInput = document.getElementById('tagInput');
const sortSelect = document.getElementById('sortSelect');
const filterToggle = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const activeFiltersDiv = document.getElementById('activeFilters');
const statsContainer = document.getElementById('statsContainer');

// Escape HTML
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Render kartu
function renderCards(entries) {
  entries.forEach(e => {
    const card = document.createElement('div');
    card.className = 'card';
    const typeClass = `type-${e.type.toLowerCase().replace(/[^a-z]/g, '')}`;
    const likedClass = e.user_liked ? 'liked' : '';
    card.innerHTML = `
      <span class="type-badge ${typeClass}">${e.type.toUpperCase()}</span>
      <div class="content">${esc(e.content)}</div>
      <div class="card-footer">
        <span class="source">— ${esc(e.source)}</span>
        <div class="tags">${e.tags.map(t => `<span class="tag">#${esc(t)}</span>`).join('')}</div>
      </div>
      <div class="like-area">
        <button class="like-btn ${likedClass}" data-entry-id="${e.id}" ${e.user_liked ? 'disabled' : ''}>
          <span class="heart">${e.user_liked ? '❤️' : '🤍'}</span>
          <span class="like-count">${e.like_count}</span>
        </button>
      </div>`;
    card.querySelector('.like-btn').addEventListener('click', handleLike);
    grid.appendChild(card);
  });
}

// Handle Like
async function handleLike(e) {
  const btn = e.currentTarget;
  const entryId = btn.dataset.entryId;

  if (btn.disabled) return;
  btn.disabled = true;

  try {
    const res = await fetch(`/api/entries/${entryId}/like`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor_id: visitorId })
    });
    const data = await res.json();

    if (res.ok) {
      btn.querySelector('.heart').textContent = '❤️';
      btn.querySelector('.like-count').textContent = data.like_count;
      btn.classList.add('liked');
      // Tetap disabled setelah sukses
    } else {
      alert(data.error || 'Gagal menyukai. Coba lagi nanti.');
      btn.disabled = false; // boleh coba lagi (biasanya untuk 409 atau rate limit)
    }
  } catch (err) {
    console.error('Like network error:', err);
    alert('Tidak dapat terhubung ke server.');
    btn.disabled = false;
  }
}

// Skeleton loader
function showSkeletons(count = 6) {
  grid.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const skel = document.createElement('div');
    skel.className = 'skeleton-card';
    skel.innerHTML = `
      <div class="skeleton-badge"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
      <div class="skeleton-footer">
        <span class="skeleton-line" style="width:30%"></span>
        <span class="skeleton-line" style="width:20%"></span>
      </div>`;
    grid.appendChild(skel);
  }
}

// Fetch entries dari API
async function fetchEntries(reset = false) {
  if (reset) {
    currentPage = 1;
    grid.innerHTML = '';
    loader.style.display = 'none';
    emptyState.style.display = 'none';
    showSkeletons();
  }

  const params = new URLSearchParams({
    page: currentPage,
    per_page: BATCH_SIZE,
    sort: currentSort,
    visitor_id: visitorId
  });
  if (currentSearch) params.set('search', currentSearch);
  if (currentType) params.set('type', currentType);
  if (currentSource) params.set('source', currentSource);
  if (currentTag) params.set('tag', currentTag);

  try {
    const res = await fetch(`${API_ENTRIES}?${params}`);
    const data = await res.json();
    currentTotal = data.total;
    if (reset) grid.innerHTML = '';
    renderCards(data.entries);
    if (reset && data.entries.length === 0) {
      emptyState.style.display = 'block';
    } else {
      emptyState.style.display = 'none';
    }
    loader.style.display = (currentPage * BATCH_SIZE < currentTotal) ? 'flex' : 'none';
  } catch (err) {
    console.error('Fetch entries error:', err);
    loader.innerHTML = '<span>⚠ Gagal memuat.</span>';
    loader.style.display = 'flex';
  }
}

// Infinite scroll
window.addEventListener('scroll', () => {
  if (isLoadingMore || currentPage * BATCH_SIZE >= currentTotal) return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 300) {
    isLoadingMore = true;
    currentPage++;
    fetchEntries().finally(() => isLoadingMore = false);
  }
});

// Filter & sort
function updateFilters() {
  currentSearch = searchInput.value.trim();
  currentType = typeSelect.value;
  currentSource = sourceInput.value.trim();
  currentTag = tagInput.value.trim();
  currentSort = sortSelect.value;
  renderActiveChips();
  fetchEntries(true);
}

// Debounce
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}

searchInput.addEventListener('input', debounce(updateFilters, 350));
typeSelect.addEventListener('change', updateFilters);
sourceInput.addEventListener('input', debounce(updateFilters, 400));
tagInput.addEventListener('input', debounce(updateFilters, 400));
sortSelect.addEventListener('change', updateFilters);

// Filter panel
filterToggle.addEventListener('click', () => {
  const visible = filterPanel.classList.toggle('visible');
  filterToggle.setAttribute('aria-expanded', visible);
  filterPanel.setAttribute('aria-hidden', !visible);
});

clearFiltersBtn.addEventListener('click', () => {
  searchInput.value = '';
  typeSelect.value = '';
  sourceInput.value = '';
  tagInput.value = '';
  sortSelect.value = 'newest';
  updateFilters();
  filterPanel.classList.remove('visible');
  filterToggle.setAttribute('aria-expanded', 'false');
});

// Active chips
function renderActiveChips() {
  let html = '';
  if (currentType) {
    const selectedText = typeSelect.options[typeSelect.selectedIndex]?.text || currentType;
    html += `<span class="chip">Tipe: ${selectedText.split(' (')[0]} <button data-clear="type">×</button></span>`;
  }
  if (currentSource) {
    html += `<span class="chip">Sumber: ${esc(currentSource)} <button data-clear="source">×</button></span>`;
  }
  if (currentTag) {
    html += `<span class="chip">Tag: ${esc(currentTag)} <button data-clear="tag">×</button></span>`;
  }
  activeFiltersDiv.innerHTML = html;
  activeFiltersDiv.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', e => {
      const clear = e.target.dataset.clear;
      if (clear === 'type') typeSelect.value = '';
      else if (clear === 'source') sourceInput.value = '';
      else if (clear === 'tag') tagInput.value = '';
      updateFilters();
    });
  });
}

// Statistik & populer
async function loadStatsAndTypes() {
  try {
    const res = await fetch(API_STATS);
    const s = await res.json();
    typeSelect.innerHTML = '<option value="">Semua Tipe</option>';
    s.types.forEach(t => {
      typeSelect.innerHTML += `<option value="${t.id}">${t.name} (${t.count})</option>`;
    });
    if (statsContainer) {
      let html = '';
      s.types.forEach(t => html += `<span class="stat-badge" data-filter-type="${t.id}">${t.name}: <strong>${t.count}</strong></span>`);
      s.sources.slice(0,3).forEach(s => html += `<span class="stat-badge" data-filter-source="${s.source}">${s.source}: <strong>${s.count}</strong></span>`);
      s.tags.slice(0,5).forEach(t => html += `<span class="stat-badge" data-filter-tag="${t.tag}">#${t.tag}: <strong>${t.count}</strong></span>`);
      statsContainer.innerHTML = html;
      document.querySelectorAll('.stat-badge').forEach(b => {
        b.addEventListener('click', () => {
          const fType = b.dataset.filterType;
          const fSource = b.dataset.filterSource;
          const fTag = b.dataset.filterTag;
          if (fType) typeSelect.value = fType;
          if (fSource) sourceInput.value = fSource;
          if (fTag) tagInput.value = fTag;
          updateFilters();
          filterPanel.classList.add('visible');
          filterToggle.setAttribute('aria-expanded', 'true');
        });
      });
    }
  } catch (err) {
    console.error('Gagal memuat statistik:', err);
  }
}

// Opsi sort
function populateSortSelect() {
  sortSelect.innerHTML = `
    <option value="newest">Terbaru</option>
    <option value="oldest">Terlama</option>
    <option value="a-z">A-Z</option>
    <option value="z-a">Z-A</option>
    <option value="most_likes">❤️ Terbanyak Like</option>
    <option value="least_likes">🤍 Tersedikit Like</option>
  `;
  sortSelect.value = currentSort;
}

// Inisialisasi
document.addEventListener('DOMContentLoaded', () => {
  populateSortSelect();
  showSkeletons();
  loadStatsAndTypes();
  fetchEntries(true);
});