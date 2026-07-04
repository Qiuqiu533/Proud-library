// ===== 検索履歴 =====
(function _initSearchHistory() {
  const HISTORY_KEY = "search_history";
  const MAX = 6;
  function getHistory() { try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; } }
  function saveHistory(kw) {
    if (!kw || kw.length < 2) return;
    let h = getHistory().filter(s => s !== kw);
    h.unshift(kw);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, MAX)));
  }
  function showHistory() {
    const inp = document.getElementById("searchInput");
    if (!inp) return;
    const h = getHistory();
    if (!h.length) return;
    const box = document.getElementById("suggestBox");
    if (!box) return;
    box.innerHTML = `<div style="font-size:0.75rem;color:#aaa;padding:6px 14px 2px">最近の検索</div>` +
      h.map(kw => `<div class="suggest-item" data-title="${esc(kw)}" style="padding:8px 14px;cursor:pointer;border-bottom:1px solid #f0ede8;font-size:0.87rem">
        <span style="color:#888;margin-right:6px">🕒</span>${esc(kw)}
      </div>`).join("");
    box.querySelectorAll(".suggest-item").forEach(el => {
      el.addEventListener("mousedown", () => {
        inp.value = el.dataset.title;
        window._hideSuggest && window._hideSuggest();
        switchToBooksAndSearch(inp.value);
      });
    });
    box.style.display = "block";
  }
  const origSwitch = window.switchToBooksAndSearch;
  window.switchToBooksAndSearch = function(kw) {
    saveHistory(kw.trim());
    return origSwitch(kw);
  };
  const inp = document.getElementById("searchInput");
  if (inp) {
    inp.addEventListener("focus", () => {
      if (!inp.value.trim()) showHistory();
    });
  }
})();

// ===== パスワード強度チェック =====
(function _initPasswordStrength() {
  const passEl = document.getElementById("regPass");
  if (!passEl) return;
  const bar = document.createElement("div");
  bar.id = "pwStrengthBar";
  bar.style.cssText = "height:4px;border-radius:4px;margin-top:4px;transition:all .3s;background:#eee;";
  const label = document.createElement("div");
  label.style.cssText = "font-size:0.72rem;color:#888;margin-top:2px;height:14px;";
  passEl.insertAdjacentElement("afterend", label);
  passEl.insertAdjacentElement("afterend", bar);
  passEl.addEventListener("input", () => {
    const pw = passEl.value;
    let score = 0;
    if (pw.length >= 8) score++;
    if (pw.length >= 12) score++;
    if (/[A-Z]/.test(pw)) score++;
    if (/[0-9]/.test(pw)) score++;
    if (/[^A-Za-z0-9]/.test(pw)) score++;
    const colors = ["#eee","#e05050","#e08a00","#e0c000","#5ba85a","#3d6b4f"];
    const labels = ["","弱い","やや弱い","普通","強い","とても強い"];
    const widths  = ["0%","20%","40%","60%","80%","100%"];
    bar.style.width = widths[score] || "0%";
    bar.style.background = colors[score] || "#eee";
    label.textContent = labels[score] || "";
    label.style.color = colors[score] || "#888";
  });
})();

// ===== 読書記録 CSVエクスポート =====
async function exportReadingLogCsv() {
  const entries = getLogEntries();
  if (!entries.length) { showToast("読書記録がありません", "warn"); return; }
  let rows = [["ISBN", "タイトル", "著者", "ステータス", "読んだ日", "メモ"]];
  try {
    const res = await fetch(`/api/books/batch?isbns=${entries.map(e => e.isbn).join(",")}`);
    const books = await res.json();
    const bookMap = Object.fromEntries(books.filter(Boolean).map(b => [b.isbn, b]));
    for (const e of entries) {
      const b = bookMap[e.isbn] || {};
      const m = getReadMeta(e.isbn);
      rows.push([e.isbn, b.title || "", b.author || "", e.status, m.date || "", m.memo || ""]);
    }
  } catch {
    for (const e of entries) {
      const m = getReadMeta(e.isbn);
      rows.push([e.isbn, "", "", e.status, m.date || "", m.memo || ""]);
    }
  }
  const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `読書記録_${new Date().toISOString().slice(0,10)}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

// ===== 管理者 リクエストCSVエクスポート =====
async function exportRequestsCsv() {
  const pw = boardPassword;
  if (!pw) { showToast("理事会パスワードが必要です", "warn"); return; }
  try {
    const res = await fetch("/api/admin/requests-csv", { headers: { "X-Password": pw } });
    if (!res.ok) { showToast("CSV取得に失敗しました", "warn"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `リクエスト一覧_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch { showToast("CSV取得に失敗しました", "warn"); }
}

// ===== 管理者 蔵書CSVエクスポート =====
async function exportBooksCsv() {
  const pw = boardPassword;
  if (!pw) { showToast("理事会パスワードが必要です", "warn"); return; }
  try {
    const res = await fetch("/api/admin/books-csv", { headers: { "X-Password": pw } });
    if (!res.ok) { showToast("CSV取得に失敗しました", "warn"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `蔵書一覧_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch { showToast("CSV取得に失敗しました", "warn"); }
}

// ===== フローティング「リクエストする」ボタン =====
function switchToRequestTab() {
  document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  const btn = document.querySelector('.tab-btn[data-tab="request"]');
  const panel = document.getElementById("tab-request");
  if (btn) { btn.classList.add("active"); btn.setAttribute("aria-selected", "true"); }
  if (panel) { panel.classList.add("active"); panel.scrollIntoView({ behavior: "smooth", block: "start" }); }
}

// ===== 読書記録タブのCSVボタン =====
(function _initLogCsvBtn() {
  const logSection = document.getElementById("tab-log");
  if (!logSection) return;
  const btn = document.createElement("button");
  btn.id = "logCsvBtn";
  btn.textContent = "📥 CSVエクスポート";
  btn.style.cssText = "margin:8px 0 0 0;padding:6px 14px;border:1.5px solid #3d6b4f;border-radius:8px;background:#fff;color:#3d6b4f;font-size:0.82rem;cursor:pointer;font-weight:600;";
  btn.onclick = exportReadingLogCsv;
  const firstEl = logSection.querySelector(".log-stats, .log-filter-bar, #logCharts");
  if (firstEl) firstEl.insertAdjacentElement("beforebegin", btn);
  else logSection.insertAdjacentElement("afterbegin", btn);
})();

// ===== QRコードポスター生成（管理者向け） =====
function generateQrPoster() {
  const title = (document.getElementById("qrPosterTitle")?.value || "").trim() || "プラウド船橋コミュニティ図書館";
  const subtitle = (document.getElementById("qrPosterSubtitle")?.value || "").trim();
  const url = window.location.origin;
  const canvas = document.getElementById("qrPosterCanvas");
  const wrap = document.getElementById("qrPosterPreviewWrap");
  if (!canvas || typeof QRCode === "undefined") { showToast("QRコード生成に失敗しました", "warn"); return; }

  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#3d6b4f";
  ctx.fillRect(0, 0, W, 16);

  ctx.fillStyle = "#222";
  ctx.textAlign = "center";
  ctx.font = "bold 54px sans-serif";
  _wrapText(ctx, title, W / 2, 150, W - 100, 64);

  if (subtitle) {
    ctx.font = "32px sans-serif";
    ctx.fillStyle = "#666";
    ctx.fillText(subtitle, W / 2, 260);
  }

  const qrHolder = document.createElement("div");
  new QRCode(qrHolder, { text: url, width: 480, height: 480, correctLevel: QRCode.CorrectLevel.M });
  setTimeout(() => {
    const qrImg = qrHolder.querySelector("img") || qrHolder.querySelector("canvas");
    const qrSize = 480, qrX = (W - qrSize) / 2, qrY = 340;
    const drawRestAndFinish = () => {
      ctx.font = "28px monospace";
      ctx.fillStyle = "#444";
      ctx.fillText(url, W / 2, qrY + qrSize + 60);
      ctx.font = "24px sans-serif";
      ctx.fillStyle = "#999";
      ctx.fillText("スマホのカメラでQRコードを読み取ってアクセス", W / 2, qrY + qrSize + 110);
      wrap.style.display = "block";
    };
    if (qrImg && qrImg.tagName === "IMG") {
      const img = new Image();
      img.onload = () => { ctx.drawImage(img, qrX, qrY, qrSize, qrSize); drawRestAndFinish(); };
      img.src = qrImg.src;
    } else if (qrImg) {
      ctx.drawImage(qrImg, qrX, qrY, qrSize, qrSize);
      drawRestAndFinish();
    }
  }, 100);
}

function _wrapText(ctx, text, x, y, maxWidth, lineHeight) {
  const chars = text.split("");
  let line = "";
  let curY = y;
  for (let i = 0; i < chars.length; i++) {
    const test = line + chars[i];
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, x, curY);
      line = chars[i];
      curY += lineHeight;
    } else {
      line = test;
    }
  }
  if (line) ctx.fillText(line, x, curY);
}

function downloadQrPoster() {
  const canvas = document.getElementById("qrPosterCanvas");
  if (!canvas) return;
  const a = document.createElement("a");
  a.href = canvas.toDataURL("image/png");
  a.download = `QRポスター_${new Date().toISOString().slice(0,10)}.png`;
  a.click();
}

// ===== 個別書籍QR（棚シール用・管理者向け） =====
function showBookQr(isbn) {
  const preview = document.getElementById("bookQrPreview");
  if (!preview || typeof QRCode === "undefined") return;
  preview.style.display = "block";
  preview.innerHTML = "";
  const holder = document.createElement("div");
  preview.appendChild(holder);
  const url = `${window.location.origin}/?book=${isbn}`;
  new QRCode(holder, { text: url, width: 160, height: 160, correctLevel: QRCode.CorrectLevel.M });
  const dlBtn = document.createElement("button");
  dlBtn.textContent = "📥 このQRを画像で保存";
  dlBtn.style.cssText = "display:block;margin:8px auto 0;padding:5px 12px;font-size:0.78rem;border:1px solid #999;border-radius:6px;background:#fff;cursor:pointer";
  dlBtn.onclick = () => {
    setTimeout(() => {
      const img = holder.querySelector("img") || holder.querySelector("canvas");
      const a = document.createElement("a");
      a.href = img.tagName === "IMG" ? img.src : img.toDataURL("image/png");
      a.download = `本QR_${isbn}.png`;
      a.click();
    }, 50);
  };
  preview.appendChild(dlBtn);
}
