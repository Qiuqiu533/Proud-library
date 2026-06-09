// State
let currentPage = 1;
let currentKeyword = "";
let currentTotal = 0;
let ratingTarget = null;
let ratingScore = 0;

// --- localStorage ratings (stored per device) ---
function getRating(isbn) {
  try {
    const data = localStorage.getItem("rating_" + isbn);
    return data ? JSON.parse(data) : { score: 0, votes: 0, reviews: [] };
  } catch { return { score: 0, votes: 0, reviews: [] }; }
}
function saveRating(isbn, score, review) {
  const r = getRating(isbn);
  const newVotes = r.votes + 1;
  const newScore = Math.round(((r.score * r.votes + score) / newVotes) * 10) / 10;
  const reviews = review ? [...r.reviews, review] : r.reviews;
  const updated = { score: newScore, votes: newVotes, reviews };
  localStorage.setItem("rating_" + isbn, JSON.stringify(updated));
  return updated;
}

// --- Utility ---
function stars(score, maxStars = 5) {
  if (!score) return '<span class="stars-empty">☆☆☆☆☆</span>';
  const full = Math.round(score);
  return '<span class="stars">' + "★".repeat(full) + "☆".repeat(maxStars - full) + "</span>" +
    `<span style="font-size:0.8rem;color:#888;margin-left:4px">${score.toFixed(1)}</span>`;
}

function statusBadge(statusText) {
  const s = statusText ? statusText.trim() : "";
  if (s === "貸出中") return `<span class="book-status status-loaned">貸出中</span>`;
  if (s === "利用可能" || s === "在架") return `<span class="book-status status-available">貸出可</span>`;
  return `<span class="book-status status-unknown">${s || "不明"}</span>`;
}

function coverImg(book, cls = "book-cover") {
  if (book.cover) {
    return `<img class="${cls}" src="${book.cover}" alt="${book.title}" onerror="this.replaceWith(placeholder())">`;
  }
  return `<div class="book-cover-placeholder">📖</div>`;
}

function placeholder() {
  const d = document.createElement("div");
  d.className = "book-cover-placeholder";
  d.textContent = "📖";
  return d;
}

// --- Book card ---
function renderCard(book) {
  const div = document.createElement("div");
  div.className = "book-card";
  const rating = book.rating || { score: 0, votes: 0 };
  const img = book.cover
    ? `<img class="book-cover" src="${book.cover}" alt="${book.title}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'book-cover-placeholder',textContent:'📖'}))">`
    : `<div class="book-cover-placeholder">📖</div>`;
  div.innerHTML = `
    ${img}
    <div class="book-info">
      <div class="book-title">${book.title}</div>
      <div class="book-author">${book.author || "著者不明"}</div>
      <div class="book-meta">${book.publisher || ""}</div>
      <div>${stars(rating.score)}</div>
    </div>`;
  div.addEventListener("click", () => openModal(book.isbn));
  return div;
}

// --- Grid rendering ---
function renderGrid(containerId, books) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = "";
  if (!books.length) {
    grid.innerHTML = '<div class="loading">該当する本が見つかりませんでした。</div>';
    return;
  }
  books.forEach(b => grid.appendChild(renderCard(b)));
}

// --- Pagination ---
function renderPagination(containerId, total, page, onPage) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";
  const totalPages = Math.ceil(total / 50);
  if (totalPages <= 1) return;

  const add = (label, p, disabled = false, active = false) => {
    const btn = document.createElement("button");
    btn.className = "page-btn" + (active ? " active" : "");
    btn.textContent = label;
    btn.disabled = disabled;
    if (!disabled) btn.addEventListener("click", () => onPage(p));
    el.appendChild(btn);
  };

  add("＜前", page - 1, page === 1);
  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  if (start > 1) { add("1", 1); if (start > 2) el.appendChild(Object.assign(document.createElement("span"), { textContent: "…", style: "padding:6px 4px;color:#999" })); }
  for (let p = start; p <= end; p++) add(String(p), p, false, p === page);
  if (end < totalPages) { el.appendChild(Object.assign(document.createElement("span"), { textContent: "…", style: "padding:6px 4px;color:#999" })); add(String(totalPages), totalPages); }
  add("次＞", page + 1, page === totalPages);
}

// --- Fetch books ---
async function loadBooks(keyword = "", page = 1) {
  currentKeyword = keyword;
  currentPage = page;
  document.getElementById("bookGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  document.getElementById("totalCount").textContent = "";

  const res = await fetch(`/api/books?keyword=${encodeURIComponent(keyword)}&page=${page}`);
  const data = await res.json();
  currentTotal = data.total;

  // Attach local ratings
  data.books.forEach(b => { b.rating = getRating(b.isbn); });

  document.getElementById("totalCount").textContent = `全 ${data.total.toLocaleString()} 件`;
  renderGrid("bookGrid", data.books);
  renderPagination("paginationTop", data.total, page, p => loadBooks(keyword, p));
  renderPagination("paginationBottom", data.total, page, p => loadBooks(keyword, p));
}

// --- New arrivals ---
async function loadNew() {
  document.getElementById("newGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch(`/api/books?keyword=&page=1`);
  const data = await res.json();
  renderGrid("newGrid", data.books.slice(0, 20));
}

// --- Library info ---
async function loadInfo() {
  const res = await fetch("/api/library-info");
  const info = await res.json();
  const hoursHtml = info.hours.map(h =>
    `<div class="avail-row"><span>${h.day}</span><span>${h.time}</span></div>`
  ).join("");
  document.getElementById("infoCard").innerHTML = `
    <h2>📍 ${info.name}</h2>
    <div class="info-row">
      <span class="info-label">所在地</span>
      <span class="info-value">${info.location}</span>
    </div>
    <div class="info-row">
      <span class="info-label">開館時間</span>
      <span class="info-value">${hoursHtml}</span>
    </div>
    <div class="info-row">
      <span class="info-label">休館日</span>
      <span class="info-value">${info.closed}</span>
    </div>
    <div class="info-source">
      📌 最新情報は <a href="https://www2.librarylife.net/booksearch?location=0011" target="_blank">図書館生活サイト</a> をご確認ください。
      <br>${info.note}
    </div>`;
}

// --- Modal ---
async function openModal(isbn) {
  const modal = document.getElementById("modal");
  document.getElementById("modalContent").innerHTML = '<div class="loading">読み込み中…</div>';
  modal.style.display = "flex";

  const res = await fetch(`/api/book/${isbn}`);
  const book = await res.json();
  const rating = getRating(isbn);

  const isbn13 = book.isbn13 || isbn;
  const isbn10 = book.isbn10 || "";
  const ndlUrl = `https://ndlsearch.ndl.go.jp/search?q=${encodeURIComponent(book.title || "")}&cs=bib`;
  const meterUrl = `https://bookmeter.com/books/${isbn13}`;
  const libUrl = `https://www2.librarylife.net/booksearch/detail/${isbn}`;

  const coverHtml = book.cover
    ? `<div class="modal-cover"><img src="${book.cover}" alt="${book.title}" onerror="this.parentElement.innerHTML='<div class=\\'modal-cover-placeholder\\'>📖</div>'"></div>`
    : `<div class="modal-cover-placeholder">📖</div>`;

  const tags = [
    book.publisher ? `<span class="tag tag-publisher">${book.publisher}</span>` : "",
    book.pubdate ? `<span class="tag tag-year">${book.pubdate.slice(0,4)}年</span>` : "",
    book.format && book.format !== "不明" ? `<span class="tag tag-format">${book.format}</span>` : "",
    book.pages && book.pages !== "0" ? `<span class="tag tag-pages">${book.pages}ページ</span>` : "",
  ].filter(Boolean).join("");

  const availHtml = book.availability && book.availability.length
    ? book.availability.map(a =>
        `<div class="avail-row"><span>${a.library}</span>${statusBadge(a.status)}</div>`
      ).join("")
    : `<div class="avail-row"><span>情報なし</span></div>`;

  const reviewsHtml = rating.reviews && rating.reviews.length
    ? rating.reviews.map(r => `<div class="review-item">💬 ${r}</div>`).join("")
    : `<div style="color:#aaa;font-size:0.85rem">まだコメントはありません</div>`;

  const descHtml = book.description
    ? `<div class="modal-desc"><h3>内容紹介</h3><p>${book.description}</p></div>`
    : "";

  document.getElementById("modalContent").innerHTML = `
    <div class="modal-top">
      ${coverHtml}
      <div class="modal-header">
        <h2>${book.title || "タイトル不明"}</h2>
        <div class="modal-author">${book.author || "著者不明"}</div>
        <div class="modal-tags">${tags}</div>
      </div>
    </div>

    <div class="modal-rating-section">
      <h3>⭐ みんなの評価</h3>
      <div class="big-stars">${rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆"}</div>
      <div class="rating-info">${rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません"}</div>
      <button class="btn-rate" data-isbn="${isbn}">この本を評価する</button>
    </div>

    <div class="modal-availability">
      <h3>📚 貸出状況</h3>
      ${availHtml}
    </div>

    ${descHtml}

    <div class="modal-reviews">
      <h3>💬 コメント</h3>
      ${reviewsHtml}
    </div>

    <div>
      <h3 style="font-size:1rem;font-weight:700;color:#3d6b4f;margin-bottom:10px">🔗 外部リンク</h3>
      <div class="external-links">
        <a class="ext-link ext-link-ndl" href="${ndlUrl}" target="_blank">国立国会図書館で検索</a>
        <a class="ext-link ext-link-meter" href="${meterUrl}" target="_blank">読書メーター</a>
        <a class="ext-link ext-link-lib" href="${libUrl}" target="_blank">図書館生活で見る</a>
      </div>
    </div>`;

  // Rate button in modal
  document.querySelector(".btn-rate").addEventListener("click", () => {
    ratingTarget = isbn;
    openRateModal();
  });
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
}

// --- Rating modal ---
function openRateModal() {
  ratingScore = 0;
  document.getElementById("reviewText").value = "";
  document.getElementById("rateMsg").textContent = "";
  updateStarUI(0);
  document.getElementById("rateModal").style.display = "flex";
}

function updateStarUI(n) {
  document.querySelectorAll(".star-opt").forEach((el, i) => {
    el.classList.toggle("active", i < n);
  });
}

// --- Event listeners ---
document.getElementById("searchBtn").addEventListener("click", () => {
  loadBooks(document.getElementById("searchInput").value);
});
document.getElementById("searchInput").addEventListener("keydown", e => {
  if (e.key === "Enter") loadBooks(document.getElementById("searchInput").value);
});
document.getElementById("modalClose").addEventListener("click", closeModal);
document.getElementById("modal").addEventListener("click", e => {
  if (e.target === document.getElementById("modal")) closeModal();
});

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const tabId = "tab-" + btn.dataset.tab;
    document.getElementById(tabId).classList.add("active");
    if (btn.dataset.tab === "new") loadNew();
    if (btn.dataset.tab === "info") loadInfo();
  });
});

document.querySelectorAll(".star-opt").forEach(el => {
  el.addEventListener("click", () => {
    ratingScore = parseInt(el.dataset.v);
    updateStarUI(ratingScore);
  });
  el.addEventListener("mouseover", () => updateStarUI(parseInt(el.dataset.v)));
  el.addEventListener("mouseleave", () => updateStarUI(ratingScore));
});

document.getElementById("rateClose").addEventListener("click", () => {
  document.getElementById("rateModal").style.display = "none";
});
document.getElementById("rateModal").addEventListener("click", e => {
  if (e.target === document.getElementById("rateModal"))
    document.getElementById("rateModal").style.display = "none";
});

document.getElementById("submitRate").addEventListener("click", () => {
  if (!ratingScore) { document.getElementById("rateMsg").textContent = "星を選んでください"; return; }
  const review = document.getElementById("reviewText").value.trim();
  saveRating(ratingTarget, ratingScore, review);
  document.getElementById("rateMsg").textContent = "✅ 投稿しました！";
  setTimeout(() => {
    document.getElementById("rateModal").style.display = "none";
    if (ratingTarget) openModal(ratingTarget);
  }, 800);
});

// Initial load
loadBooks();
