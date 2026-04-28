/**
 * script.js – Showcase "Arsip Rasa"
 * Menangani: infinite scroll, filter tipe, sumber, tag, search, sorting,
 * serta menampilkan statistik ringan di halaman.
 */

// ---------- Konfigurasi ----------
const API_ENTRIES = '/api/entries';
const API_STATS   = '/api/stats';
const BATCH_SIZE  = 15;

// State filter
let currentType   = '';   // id tipe (string)
let currentSource = '';   // pencarian sumber
let currentTag    = '';   // pencarian tag
let currentSearch = '';   // pencarian umum
let currentSort   = 'newest'; // newest, oldest, a-z, z-a

let currentPage   = 1;
let currentTotal  = 0;
let isLoading     = false;

// Elemen DOM
const grid         = document.getElementById('cardGrid');
const loader       = document.getElementById('loader');
const searchInput  = document.getElementById('searchInput');
const typeSelect   = document.getElementById('typeSelect');
const sourceInput  = document.getElementById('sourceInput');
const tagInput     = document.getElementById('tagInput');
const sortSelect   = document.getElementById('sortSelect');
const statsContainer = document.getElementById('statsContainer'); // opsional

// ---------- Escape HTML (XSS prevention) ----------
function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ---------- Fetch Entries ----------
async function fetchEntries(reset = false) {
  if (reset) {
    currentPage = 1;
    grid.innerHTML = '';
  }

  const params = new URLSearchParams();
  params.set('page', currentPage);
  params.set('per_page', BATCH_SIZE);
  if (currentSearch) params.set('search', currentSearch);
  if (currentType)   params.set('type', currentType);
  if (currentSource) params.set('source', currentSource);
  if (currentTag)    params.set('tag', currentTag);
  if (currentSort)   params.set('sort', currentSort);

  try {
    const res = await fetch(`${API_ENTRIES}?${params}`);
    if (!res.ok) throw new Error('Gagal memuat data');
    const data = await res.json();
    currentTotal = data.total;
    renderCards(data.entries);
    loader.style.display = (currentPage * BATCH_SIZE < currentTotal) ? 'block' : 'none';
  } catch (err) {
    console.error(err);
    loader.textContent = 'Gagal memuat konten.';
    loader.style.display = 'block';
  }
}

// ---------- Render Kartu ----------
function renderCards(entries) {
  entries.forEach(entry => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <span class="type-badge type-${entry.type}">${entry.type.toUpperCase()}</span>
      <div class="content">${escapeHTML(entry.content)}</div>
      <div class="footer">
        <span class="source">— ${escapeHTML(entry.source)}</span>
        <div class="tags">
          ${entry.tags.map(tag => `<span class="tag">#${escapeHTML(tag)}</span>`).join('')}
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
}

// ---------- Infinite Scroll ----------
window.addEventListener('scroll', () => {
  if (isLoading) return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 200) {
    if (currentPage * BATCH_SIZE < currentTotal) {
      isLoading = true;
      currentPage++;
      fetchEntries().finally(() => (isLoading = false));
    }
  }
});

// ---------- Handler Filter / Sort ----------
function updateFilters() {
  // Ambil nilai dari input
  currentSearch = searchInput.value.trim();
  currentType   = typeSelect?.value || '';
  currentSource = sourceInput?.value.trim() || '';
  currentTag    = tagInput?.value.trim() || '';
  currentSort   = sortSelect?.value || 'newest';

  // Reset tampilan & muat ulang
  fetchEntries(true);
}

// ---------- Pasang Event Listener ----------
if (searchInput) searchInput.addEventListener('input', debounce(updateFilters, 300));
if (typeSelect)  typeSelect.addEventListener('change', updateFilters);
if (sourceInput) sourceInput.addEventListener('input', debounce(updateFilters, 300));
if (tagInput)    tagInput.addEventListener('input', debounce(updateFilters, 300));
if (sortSelect)  sortSelect.addEventListener('change', updateFilters);

// Fungsi debounce sederhana
function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

// ---------- Muat Statistik (Opsional) ----------
async function loadStats() {
  if (!statsContainer) return;
  try {
    const res = await fetch(API_STATS);
    const stats = await res.json();
    let html = '<div style="display:flex; gap:2rem; flex-wrap:wrap; margin:1rem 0;">';

    // Tipe
    html += '<div><strong>Tipe:</strong><ul>';
    stats.types.forEach(t => {
      html += `<li>${t.name} (${t.count})</li>`;
    });
    html += '</ul></div>';

    // Sumber teratas (5)
    html += '<div><strong>Sumber Teratas:</strong><ul>';
    stats.sources.slice(0, 5).forEach(s => {
      html += `<li>${s.source} (${s.count})</li>`;
    });
    html += '</ul></div>';

    // Tag teratas (5)
    html += '<div><strong>Tag Populer:</strong><ul>';
    stats.tags.slice(0, 5).forEach(t => {
      html += `<li>#${t.tag} (${t.count})</li>`;
    });
    html += '</ul></div></div>';

    statsContainer.innerHTML = html;
  } catch (err) {
    console.error('Gagal memuat statistik:', err);
  }
}

// ---------- Inisialisasi ----------
document.addEventListener('DOMContentLoaded', () => {
  // Isi dropdown tipe dari API stats (bisa di-cache)
  fetch(API_STATS)
    .then(res => res.json())
    .then(stats => {
      if (typeSelect) {
        // Tambahkan opsi "Semua"
        typeSelect.innerHTML = '<option value="">Semua Tipe</option>';
        stats.types.forEach(t => {
          typeSelect.innerHTML += `<option value="${t.id}">${t.name} (${t.count})</option>`;
        });
      }
    })
    .catch(console.error);

  // Muat entri pertama kali
  fetchEntries(true);
  // Muat statistik jika ada
  loadStats();
});