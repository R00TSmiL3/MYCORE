// ==================== CONFIGURATION ====================
const API_ENTRIES = '/api/entries';
const API_STATS   = '/api/stats';
const API_RANDOM  = '/api/random';
const BATCH_SIZE  = 15;

// ==================== STATE ====================
let currentType = '', currentSource = '', currentTag = '', currentSearch = '', currentSort = 'newest';
let currentPage = 1, currentTotal = 0, isLoadingMore = false;
let bookmarkMode = false;

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

// ==================== DARK/LIGHT MODE (LILIN) ====================
const themeToggle = document.getElementById('themeToggle');
const lilinWrapper = document.getElementById('lilinWrapper');
const body = document.body;

const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'dark') {
    body.classList.remove('light-mode');
    lilinWrapper.classList.add('dark');
    themeToggle.checked = false;
} else {
    body.classList.add('light-mode');
    lilinWrapper.classList.remove('dark');
    themeToggle.checked = true;
}

themeToggle.addEventListener('change', () => {
    if (themeToggle.checked) {
        body.classList.add('light-mode');
        lilinWrapper.classList.remove('dark');
        localStorage.setItem('theme', 'light');
    } else {
        body.classList.remove('light-mode');
        lilinWrapper.classList.add('dark');
        localStorage.setItem('theme', 'dark');
    }
});

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
const bookmarkBtn = document.getElementById('bookmarkBtn');
const bookmarkBadge = document.getElementById('bookmarkBadge');

// Auth elements (ditambahkan)
let loginLink = null;
let logoutLink = null;
let displayUsername = null;
let btnUpload = null;

function createAuthElements() {
  // Buat elemen dinamis jika tidak ada di HTML
  if (!document.getElementById('authArea')) {
    const authArea = document.createElement('div');
    authArea.id = 'authArea';
    authArea.style.display = 'flex';
    authArea.style.alignItems = 'center';
    authArea.style.gap = '0.5rem';
    // tempatkan di dalam search-area atau di sampingnya
    const searchArea = document.querySelector('.search-area');
    if (searchArea) {
      searchArea.appendChild(authArea);
    } else {
      document.querySelector('.header-inner')?.appendChild(authArea);
    }

    loginLink = document.createElement('a');
    loginLink.href = '/logreg';
    loginLink.className = 'btn-random';
    loginLink.textContent = 'Masuk';
    loginLink.id = 'loginLink';

    logoutLink = document.createElement('a');
    logoutLink.href = '#';
    logoutLink.className = 'btn-random';
    logoutLink.textContent = 'Keluar';
    logoutLink.id = 'logoutLink';
    logoutLink.style.display = 'none';

    displayUsername = document.createElement('span');
    displayUsername.id = 'display-username';
    displayUsername.style.color = 'var(--gold)';
    displayUsername.style.display = 'none';

    btnUpload = document.createElement('button');
    btnUpload.className = 'btn-random';
    btnUpload.textContent = '+ Upload';
    btnUpload.id = 'btn-upload';
    btnUpload.style.display = 'none';

    authArea.appendChild(loginLink);
    authArea.appendChild(displayUsername);
    authArea.appendChild(btnUpload);
    authArea.appendChild(logoutLink);
  } else {
    loginLink = document.getElementById('loginLink');
    logoutLink = document.getElementById('logoutLink');
    displayUsername = document.getElementById('display-username');
    btnUpload = document.getElementById('btn-upload');
  }
}

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
function updateBookmarkBadge() {
  const count = getBookmarks().length;
  if (bookmarkBadge) {
    bookmarkBadge.textContent = count;
    bookmarkBadge.style.display = count > 0 ? 'inline' : 'none';
  }
}

// ==================== AUTH ====================
async function checkLogin() {
  try {
    const res = await fetch('/api/me');
    if (res.ok) {
      const user = await res.json();
      showLoggedIn(user);
    } else {
      showLoggedOut();
    }
  } catch { showLoggedOut(); }
}

function showLoggedIn(user) {
  if (!loginLink) return;
  loginLink.style.display = 'none';
  if (displayUsername) {
    displayUsername.style.display = 'inline';
    displayUsername.textContent = user.username;
  }
  if (btnUpload) btnUpload.style.display = 'inline-flex';
  if (logoutLink) logoutLink.style.display = 'inline-flex';
  // tambahkan event logout
  if (logoutLink) {
    logoutLink.onclick = async (e) => {
      e.preventDefault();
      await fetch('/api/logout');
      showLoggedOut();
      showToast('Anda telah keluar.', 'info');
    };
  }
  // event upload
  if (btnUpload) {
    btnUpload.onclick = () => showUploadModal();
  }
}

function showLoggedOut() {
  if (!loginLink) return;
  loginLink.style.display = 'inline-flex';
  if (displayUsername) displayUsername.style.display = 'none';
  if (btnUpload) btnUpload.style.display = 'none';
  if (logoutLink) logoutLink.style.display = 'none';
}

// ==================== MODAL (untuk upload) ====================
function openModal(html) {
  let modal = document.getElementById('modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal';
    modal.className = 'modal';
    modal.innerHTML = `<div class="modal-content"><span class="modal-close">&times;</span><div id="modal-body"></div></div>`;
    document.body.appendChild(modal);
    modal.querySelector('.modal-close').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  }
  document.getElementById('modal-body').innerHTML = html;
  modal.classList.add('active');
}
function closeModal() {
  const modal = document.getElementById('modal');
  if (modal) modal.classList.remove('active');
}

async function showUploadModal() {
  try {
    const res = await fetch('/api/stats');
    const stats = await res.json();
    const types = stats.types;
    const html = `
      <h3>Upload Puisi/Quote</h3>
      <select id="upload-type" class="form-control" style="margin-bottom:0.5rem;">${types.map(t => `<option value="${t.id}">${t.name}</option>`).join('')}</select>
      <textarea id="upload-content" class="form-control" rows="5" placeholder="Tulis isi..." style="margin-bottom:0.5rem;"></textarea>
      <input type="text" id="upload-source" class="form-control" placeholder="Sumber (penulis)" style="margin-bottom:0.5rem;">
      <input type="text" id="upload-tags" class="form-control" placeholder="Tag (pisahkan koma)" style="margin-bottom:0.5rem;">
      <button class="btn" id="upload-submit">Kirim</button>
    `;
    openModal(html);
    document.getElementById('upload-submit').addEventListener('click', async () => {
      const data = {
        type_id: document.getElementById('upload-type').value,
        content: document.getElementById('upload-content').value,
        source: document.getElementById('upload-source').value,
        tags: document.getElementById('upload-tags').value
      };
      const res = await fetch('/api/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        closeModal();
        showToast('Entri berhasil dikirim dan menunggu moderasi.', 'success');
      } else {
        const err = await res.json();
        showToast(err.error, 'error');
      }
    });
  } catch {
    showToast('Gagal memuat daftar tipe.', 'error');
  }
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

    const likeHtml = `
      <button class="like-btn ${isLiked ? 'liked' : ''}" data-entry-id="${e.id}">
        <svg viewBox="0 0 24 24" fill="${isLiked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
          <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
        </svg>
        <span class="like-count">${e.like_count}</span>
      </button>`;

    const bookmarkHtml = `
      <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" data-entry-id="${e.id}">
        <svg viewBox="0 0 24 24" fill="${isBookmarked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
        </svg>
      </button>`;

    const copyHtml = `
      <button class="copy-btn" data-text="${escapeHtml(e.content)}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
      </button>`;

    const shareHtml = `
      <button class="share-btn" data-text="${escapeHtml(e.content)}" data-source="${escapeHtml(e.source)}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
        </svg>
      </button>`;

    card.innerHTML = `
      <span class="type-badge ${typeClass}">${e.type.toUpperCase()}</span>
      <div class="content">${escapeHtml(e.content)}</div>
      <div class="card-footer">
        <span class="source">— ${escapeHtml(e.source)}</span>
        <span class="author" style="margin-left:auto;">👤 ${escapeHtml(e.username)}</span>
        <div class="tags">${e.tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join('')}</div>
      </div>
      <div class="actions">
        ${likeHtml}
        ${bookmarkHtml}
        ${copyHtml}
        ${shareHtml}
      </div>`;

    card.querySelector('.like-btn').addEventListener('click', toggleLike);
    card.querySelector('.bookmark-btn').addEventListener('click', toggleBookmark);
    card.querySelector('.copy-btn').addEventListener('click', copyText);
    card.querySelector('.share-btn').addEventListener('click', shareEntry);
    grid.appendChild(card);
  });
}

// ==================== LIKE (Toggle) ====================
async function toggleLike(e) {
  const btn = e.currentTarget;
  const entryId = btn.dataset.entryId;
  const isLiked = btn.classList.contains('liked');
  btn.disabled = true;
  const method = isLiked ? 'DELETE' : 'POST';
  try {
    const res = await fetch(`/api/entries/${entryId}/like`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor_id: visitorId })
    });
    const data = await res.json();
    if (res.ok) {
      if (isLiked) {
        btn.classList.remove('liked');
        btn.querySelector('svg').setAttribute('fill', 'none');
      } else {
        btn.classList.add('liked');
        btn.querySelector('svg').setAttribute('fill', 'currentColor');
      }
      btn.querySelector('.like-count').textContent = data.like_count;
    } else {
      showToast(data.error || 'Gagal', 'error');
    }
  } catch {
    showToast('Tidak dapat terhubung ke server', 'error');
  }
  btn.disabled = false;
}

// ==================== BOOKMARK ====================
function toggleBookmark(e) {
  const btn = e.currentTarget;
  const id = parseInt(btn.dataset.entryId);
  let bookmarks = getBookmarks();
  if (bookmarks.includes(id)) {
    bookmarks = bookmarks.filter(bid => bid !== id);
    btn.classList.remove('bookmarked');
    btn.querySelector('svg').setAttribute('fill', 'none');
    showToast('Dihapus dari bookmark', 'info');
  } else {
    bookmarks.push(id);
    btn.classList.add('bookmarked');
    btn.querySelector('svg').setAttribute('fill', 'currentColor');
    showToast('Ditambahkan ke bookmark', 'success');
  }
  saveBookmarks(bookmarks);
  updateBookmarkBadge();
  if (bookmarkMode) loadBookmarkEntries();
}

function copyText(e) {
  const text = e.currentTarget.dataset.text;
  navigator.clipboard.writeText(text).then(() => showToast('Teks disalin!', 'success'));
}

function shareEntry(e) {
  const btn = e.currentTarget;
  const text = btn.dataset.text;
  const source = btn.dataset.source;
  const url = window.location.href.split('?')[0];
  if (navigator.share) {
    navigator.share({ title: 'Arsip Rasa', text: `"${text}"\n— ${source}\n`, url }).catch(() => {});
  } else {
    navigator.clipboard.writeText(`${text}\n— ${source}\n${url}`).then(() => showToast('Tautan bagikan disalin!', 'success'));
  }
}

// ==================== RANDOM & BOOKMARK MODE ====================
randomBtn?.addEventListener('click', async () => {
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

async function loadBookmarkEntries() {
  const bookmarks = getBookmarks();
  if (bookmarks.length === 0) {
    grid.innerHTML = '';
    emptyState.style.display = 'block';
    emptyState.querySelector('h3').textContent = 'Belum ada bookmark';
    return;
  }
  const params = new URLSearchParams({ ids: bookmarks.join(','), visitor_id: visitorId });
  try {
    const res = await fetch(`${API_ENTRIES}?${params}`);
    const data = await res.json();
    grid.innerHTML = '';
    renderCards(data.entries);
    emptyState.style.display = 'none';
  } catch { showToast('Gagal memuat bookmark', 'error'); }
}

bookmarkBtn?.addEventListener('click', () => {
  bookmarkMode = !bookmarkMode;
  if (bookmarkMode) {
    bookmarkBtn.classList.add('active');
    loadBookmarkEntries();
  } else {
    bookmarkBtn.classList.remove('active');
    fetchEntries(true);
  }
});

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
  if (bookmarkMode) return;
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
  if (bookmarkMode || isLoadingMore || currentPage * BATCH_SIZE >= currentTotal) return;
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
  if (bookmarkMode) {
    bookmarkMode = false;
    bookmarkBtn.classList.remove('active');
  }
  fetchEntries(true);
}

function debounce(fn, delay) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), delay); }; }

searchInput.addEventListener('input', debounce(updateFilters, 350));
typeSelect?.addEventListener('change', updateFilters);
sourceInput?.addEventListener('input', debounce(updateFilters, 400));
tagInput?.addEventListener('input', debounce(updateFilters, 400));
sortSelect?.addEventListener('change', updateFilters);

filterToggle?.addEventListener('click', () => filterPanel.classList.toggle('visible'));
clearFiltersBtn?.addEventListener('click', () => {
  searchInput.value = ''; typeSelect.value = ''; sourceInput.value = ''; tagInput.value = ''; sortSelect.value = 'newest';
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
  createAuthElements();
  populateSortSelect();
  updateBookmarkBadge();
  showSkeletons();
  loadStatsAndTypes();
  fetchEntries(true);
  checkLogin();  // cek status login
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