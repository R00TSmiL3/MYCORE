/**
 * script.js – Fetch data dari API Flask dan render grid + infinite scroll.
 * Kompatibel dengan template showcase.
 */

// Konfigurasi
const API_BASE = '/api/entries';
const BATCH_SIZE = 15;
let currentPage = 1;
let currentTotal = 0;
let currentType = 'all';
let currentTag = '';
let searchTerm = '';

// DOM elements
const grid = document.getElementById('cardGrid');
const loader = document.getElementById('loader');
const searchInput = document.getElementById('searchInput');
const filterBtns = document.querySelectorAll('.filter-btn');

/**
 * Melakukan request ke API dengan parameter.
 * @param {Object} params
 * @returns {Promise<Object>} { entries, total, page, per_page }
 */
async function fetchEntries(params = {}) {
    const url = new URL(API_BASE, window.location.origin);
    Object.keys(params).forEach(key => url.searchParams.append(key, params[key]));

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Gagal mengambil data');
        return await response.json();
    } catch (error) {
        console.error(error);
        loader.textContent = 'Gagal memuat.';
        return { entries: [], total: 0 };
    }
}

/**
 * Merender sejumlah kartu ke grid.
 * @param {Array} entries
 */
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

// Fungsi sederhana untuk mencegah XSS saat render dinamis
function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Reset grid dan muat halaman pertama dengan filter saat ini.
 */
async function resetAndLoad() {
    grid.innerHTML = '';
    currentPage = 1;
    loader.style.display = 'block';
    const data = await fetchEntries({
        page: currentPage,
        per_page: BATCH_SIZE,
        search: searchTerm,
        type: currentType,
        tag: currentTag
    });
    currentTotal = data.total;
    renderCards(data.entries);
    loader.style.display = currentPage * BATCH_SIZE < currentTotal ? 'block' : 'none';
}

/**
 * Muat halaman berikutnya (infinite scroll).
 */
async function loadMore() {
    if (currentPage * BATCH_SIZE >= currentTotal) return;
    currentPage++;
    loader.style.display = 'block';
    const data = await fetchEntries({
        page: currentPage,
        per_page: BATCH_SIZE,
        search: searchTerm,
        type: currentType,
        tag: currentTag
    });
    renderCards(data.entries);
    loader.style.display = currentPage * BATCH_SIZE < currentTotal ? 'block' : 'none';
}

// Event listener untuk infinite scroll dengan debounce sederhana
let isLoading = false;
window.addEventListener('scroll', () => {
    if (isLoading) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    if (scrollBottom >= document.body.offsetHeight - 200) {
        if (currentPage * BATCH_SIZE < currentTotal) {
            isLoading = true;
            loadMore().finally(() => { isLoading = false; });
        }
    }
});

// Event: Search
searchInput.addEventListener('input', (e) => {
    searchTerm = e.target.value.trim().toLowerCase();
    resetAndLoad();
});

// Event: Filter buttons
filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        const tag = btn.dataset.tag;

        // Reset semua button active
        filterBtns.forEach(b => b.classList.remove('active'));

        if (type) {
            // Filter tipe
            btn.classList.add('active');
            currentType = type;
            currentTag = ''; // reset tag
            // Nonaktifkan tag button yang mungkin aktif
        } else if (tag) {
            // Filter tag
            btn.classList.add('active');
            currentTag = tag;
            currentType = 'all';
            // Aktifkan tombol "Semua"
            document.querySelector('.filter-btn[data-type="all"]').classList.add('active');
        }
        resetAndLoad();
    });
});

// Muat awal
resetAndLoad();