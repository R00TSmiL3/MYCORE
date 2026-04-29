// ==================== CONFIGURATION ====================
const API_ENTRIES = '/api/entries';
const API_STATS   = '/api/stats';
const API_RANDOM  = '/api/random';
const BATCH_SIZE  = 15;

// ==================== STATE ====================
let currentType = '', currentSource = '', currentTag = '', currentSearch = '', currentSort = 'newest';
let currentPage = 1, currentTotal = 0, isLoadingMore = false;

// ==================== VISITOR ID ====================
function generateVisitorId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}
let visitorId = localStorage.getItem('visitor_id');
if (!visitorId || visitorId.length < 8) {
  visitorId = generateVisitorId();
  localStorage.setItem('visitor_id', visitorId);
}

// ==================== DOM ELEMENTS ====================
const grid = document.getElementById('cardGrid');
const loader = document.getElementById('loader');
const emptyState = document.getElementById('emptyState');
const searchInput = document.getElementById('searchInput');
const typeSelect = document.getElementById('typeSelect');
const sourceInput = document.getElementById('sourceInput');
const tagInput = document.getElementById('tagInput');
const sortSelect = document.getElementById('sortSelect');
const filterToggle = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const activeFiltersDiv = document.getElementById('activeFilters');
const statsContainer = document.getElementById('statsContainer');
const clearFiltersBtn = document.getElementById('clearFiltersBtn');
const randomBtn = document.getElementById('randomBtn');

// ==================== UTILS ====================
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function showToast(msg, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function getBookmarks() {
  return JSON.parse(localStorage.getItem('bookmarks') || '[]');
}
function saveBookmarks(list) {
  localStorage.setItem('bookmarks', JSON.stringify(list));
}

// ==================== RENDER ====================
function renderCards(entries) {
  const bookmarks = getBookmarks();
  entries.forEach(e => {
    const card = document.createElement('div');
    card.className = 'card';
    const typeClass = `type-${e.type.toLowerCase().replace(/[^a-z]/g, '')}`;
    const isLiked = e.user_liked;
    const isBookmarked = bookmarks.includes(e.id);
    card.innerHTML = `
      <span class="type-badge ${typeClass}">${e.type.toUpperCase()}</span>
      <div class="content">${escapeHtml(e.content)}</div>
      <div class="card-footer">
        <span class="source">— ${escapeHtml(e.source)}</span>
        <div class="tags">${e.tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join('')}</div>
      </div>
      <div class="actions">
        <button class="like-btn ${isLiked ? 'liked' : ''}" data-entry-id="${e.id}" ${isLiked ? 'disabled' : ''}>
          <span class="heart">${isLiked ? '❤️' : '🤍'}</span>
          <span class="like-count">${e.like_count}</span>
        </button>
        <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" data-entry-id="${e.id}" title="Bookmark">🔖</button>
        <button class="copy-btn" data-text="${escapeHtml(e.content)}" title="Salin">📋</button>
        <button class="share-btn" data-text="${escapeHtml(e.content)}" data-source="${escapeHtml(e.source)}" title="Bagikan">🔗</button>
      </div>`;
    // event listeners
    card.querySelector('.like-btn').addEventListener('click', handleLike);
    card.querySelector('.bookmark-btn').addEventListener('click', toggleBookmark);
    card.querySelector('.copy-btn').addEventListener('click', copyText);
    card.querySelector('.share-btn').addEventListener('click', shareEntry);
    grid.appendChild(card);
  });
}

// ==================== LIKE ====================
async function handleLike(e) {
  const btn = e.currentTarget;
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/entries/${btn.dataset.entryId}/like`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor_id: visitorId })
    });
    const data = await res.json();
    if (res.ok) {
      btn.querySelector('.heart').textContent = '❤️';
      btn.querySelector('.like-count').textContent = data.like_count;
      btn.classList.add('liked');
      btn.disabled = true;
    } else {
      showToast(data.error || 'Gagal menyukai', 'error');
      btn.disabled = false;
    }
  } catch {
    showToast('Tidak dapat terhubung ke server', 'error');
    btn.disabled = false;
  }
}

// ==================== BOOKMARK ====================
function toggleBookmark(e) {
  const btn = e.currentTarget;
  const id = parseInt(btn.dataset.entryId);
  let bookmarks = getBookmarks();
  if (bookmarks.includes(id)) {
    bookmarks = bookmarks.filter(bid => bid !== id);
    btn.classList.remove('bookmarked');
    showToast('Dihapus dari bookmark', 'info');
  } else {
    bookmarks.push(id);
    btn.classList.add('bookmarked');
    showToast('Ditambahkan ke bookmark', 'success');
  }
  saveBookmarks(bookmarks);
}

// ==================== COPY & SHARE ====================
function copyText(e) {
  const text = e.currentTarget.dataset.text;
  navigator.clipboard.writeText(text).then(() => showToast('Teks disalin!', 'success'));
}

function shareEntry(e) {
  const btn = e.currentTarget;
  const text = btn.dataset.text;
  const source = btn.dataset.source;
  const url = window.location.href.split('?')[0];
  const shareData = { title: 'Arsip Rasa', text: `"${text}"\n— ${source}\n`, url };
  if (navigator.share) {
    navigator.share(shareData);
  } else {
    navigator.clipboard.writeText(`${text}\n— ${source}\n${url}`).then(() => showToast('Tautan disalin!', 'success'));
  }
}

// ==================== RANDOM QUOTE ====================
if (randomBtn) {
  randomBtn.addEventListener('click', async () => {
    try {
      const res = await fetch(API_RANDOM);
      if (res.ok) {
        const entry = await res.json();
        grid.innerHTML = '';
        renderCards([entry]);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } else {
        showToast('Gagal mengambil kutipan acak', 'error');
      }
    } catch { showToast('Gagal terhubung', 'error'); }
  });
}

// ==================== FETCH & INFINITE SCROLL ====================
function showSkeletons(count = 6) {
  grid.innerHTML = '';
  for (let i=0; i<count; i++) {
    const skel = document.createElement('div');
    skel.className = 'skeleton-card';
    skel.innerHTML = '<div class="skeleton-badge"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div><div class="skeleton-footer"><span class="skeleton-line" style="width:30%"></span><span class="skeleton-line" style="width:20%"></span></div>';
    grid.appendChild(skel);
  }
}

async function fetchEntries(reset = false) {
  if (reset) {
    currentPage = 1;
    grid.innerHTML = '';
    emptyState.style.display = 'none';
    loader.style.display = 'none';
    showSkeletons();
  }
  const params = new URLSearchParams({
    page: currentPage, per_page: BATCH_SIZE, sort: currentSort,
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
    emptyState.style.display = (reset && data.entries.length === 0) ? 'block' : 'none';
    loader.style.display = (currentPage * BATCH_SIZE < currentTotal) ? 'flex' : 'none';
  } catch {
    loader.innerHTML = '<span>⚠ Gagal memuat</span>';
    loader.style.display = 'flex';
  }
}

window.addEventListener('scroll', () => {
  if (isLoadingMore || currentPage * BATCH_SIZE >= currentTotal) return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 300) {
    isLoadingMore = true;
    currentPage++;
    fetchEntries().finally(() => isLoadingMore = false);
  }
});

// ==================== FILTERS ====================
function updateFilters() {
  currentSearch = searchInput.value.trim();
  currentType = typeSelect.value;
  currentSource = sourceInput.value.trim();
  currentTag = tagInput.value.trim();
  currentSort = sortSelect.value;
  renderActiveChips();
  fetchEntries(true);
}

function debounce(fn, delay) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), delay); }; }

searchInput.addEventListener('input', debounce(updateFilters, 350));
typeSelect?.addEventListener('change', updateFilters);
sourceInput?.addEventListener('input', debounce(updateFilters, 400));
tagInput?.addEventListener('input', debounce(updateFilters, 400));
sortSelect?.addEventListener('change', updateFilters);

filterToggle?.addEventListener('click', () => {
  filterPanel.classList.toggle('visible');
  document.querySelector('.filter-overlay')?.classList.toggle('active');
});
clearFiltersBtn?.addEventListener('click', () => {
  searchInput.value = '';
  typeSelect.value = '';
  sourceInput.value = '';
  tagInput.value = '';
  sortSelect.value = 'newest';
  updateFilters();
  filterPanel.classList.remove('visible');
});

function renderActiveChips() {
  let html = '';
  if (currentType) html += `<span class="chip">Tipe: ${typeSelect.options[typeSelect.selectedIndex]?.text.split(' (')[0] || currentType} <button data-clear="type">×</button></span>`;
  if (currentSource) html += `<span class="chip">Sumber: ${escapeHtml(currentSource)} <button data-clear="source">×</button></span>`;
  if (currentTag) html += `<span class="chip">Tag: ${escapeHtml(currentTag)} <button data-clear="tag">×</button></span>`;
  activeFiltersDiv.innerHTML = html;
  activeFiltersDiv.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', e => {
      if (e.target.dataset.clear === 'type') typeSelect.value = '';
      else if (e.target.dataset.clear === 'source') sourceInput.value = '';
      else if (e.target.dataset.clear === 'tag') tagInput.value = '';
      updateFilters();
    });
  });
}

// ==================== STATS & INIT ====================
async function loadStatsAndTypes() {
  try {
    const res = await fetch(API_STATS);
    const s = await res.json();
    if (typeSelect) {
      typeSelect.innerHTML = '<option value="">Semua Tipe</option>';
      s.types.forEach(t => { typeSelect.innerHTML += `<option value="${t.id}">${t.name} (${t.count})</option>`; });
    }
    if (statsContainer) {
      statsContainer.innerHTML = s.types.map(t => `<span class="stat-badge" data-filter-type="${t.id}">${t.name}: <strong>${t.count}</strong></span>`).join('') +
        s.sources.slice(0,3).map(s => `<span class="stat-badge" data-filter-source="${s.source}">${s.source}: <strong>${s.count}</strong></span>`).join('') +
        s.tags.slice(0,5).map(t => `<span class="stat-badge" data-filter-tag="${t.tag}">#${t.tag}: <strong>${t.count}</strong></span>`).join('');
      document.querySelectorAll('.stat-badge').forEach(b => {
        b.addEventListener('click', () => {
          if (b.dataset.filterType) typeSelect.value = b.dataset.filterType;
          if (b.dataset.filterSource) sourceInput.value = b.dataset.filterSource;
          if (b.dataset.filterTag) tagInput.value = b.dataset.filterTag;
          updateFilters();
        });
      });
    }
  } catch { console.error('Gagal memuat statistik'); }
}

function init() {
  populateSortSelect();
  showSkeletons();
  loadStatsAndTypes();
  fetchEntries(true);
}

function populateSortSelect() {
  if (sortSelect) {
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
}

document.addEventListener('DOMContentLoaded', init);