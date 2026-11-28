/* ProductLens 前端交互 */
const $ = (sel) => document.querySelector(sel);

const el = {
  urlInput: $("#urlInput"),
  btn: $("#analyzeBtn"),
  errorBar: $("#errorBar"),
  progressCard: $("#progressCard"),
  progressLabel: $("#progressLabel"),
  progressFill: $("#progressFill"),
  progressTimer: $("#progressTimer"),
  results: $("#results"),
  topbarMeta: $("#topbarMeta"),
};

let state = { result: null, lang: "zh" };
let timerHandle = null;

/* ---------------- 初始化 ---------------- */
fetch("/api/health").then(r => r.json()).then(h => {
  el.topbarMeta.textContent = h.text_model
    ? `文本模型 ${h.text_model} · 图片理解 ${h.vision_enabled ? "已启用" : "未启用"}`
    : "未配置 LLM_API_KEY";
}).catch(() => { el.topbarMeta.textContent = "后端未就绪"; });
document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    el.urlInput.value = chip.dataset.url;
    el.urlInput.focus();
  });
});
el.urlInput.addEventListener("keydown", e => { if (e.key === "Enter") start(); });
el.btn.addEventListener("click", start);

document.querySelectorAll(".lang-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".lang-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    state.lang = tab.dataset.lang;
    $("#copyZh").classList.toggle("hidden", state.lang !== "zh");
    $("#copyEn").classList.toggle("hidden", state.lang !== "en");
  });
});

document.addEventListener("click", e => {
  if (e.target.classList.contains("copy-btn")) {
    const lang = e.target.dataset.copy;
    const script = state.result
      ? (lang === "zh" ? state.result.copy_zh?.script : state.result.copy_en?.script) || ""
      : "";
    navigator.clipboard.writeText(script).then(() => {
      e.target.textContent = "已复制";
      setTimeout(() => (e.target.textContent = "复制文案"), 1500);
    });
  }
  if (e.target.tagName === "IMG" && e.target.closest(".gallery")) {
    $("#lightboxImg").src = e.target.src;
    $("#lightbox").classList.remove("hidden");
  }
});

/* 灯箱关闭：按钮 / 点击遮罩 / ESC */
function closeLightbox() {
  $("#lightbox").classList.add("hidden");
  $("#lightboxImg").src = "";
}
$("#lbClose").addEventListener("click", e => { e.stopPropagation(); closeLightbox(); });
$("#lightbox").addEventListener("click", e => {
  if (e.target.id === "lightbox") closeLightbox();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("#lightbox").classList.contains("hidden")) closeLightbox();
});

/* ---------------- 主流程（异步任务 + 轮询） ---------------- */
function start() {
  const url = el.urlInput.value.trim();
  if (!url) { showError("请先粘贴 Amazon 商品链接"); return; }
  hideError();
  el.btn.disabled = true;
  el.btn.textContent = "分析中…";
  el.results.classList.add("hidden");
  el.progressCard.classList.remove("hidden");
  setProgress(4, "正在提交任务…");

  const t0 = Date.now();
  const timer = setInterval(() => {
    el.progressTimer.textContent = ((Date.now() - t0) / 1000).toFixed(0) + "s";
  }, 500);

  const finish = () => {
    clearInterval(timer);
    clearInterval(pollHandle);
    el.progressCard.classList.add("hidden");
    el.btn.disabled = false;
    el.btn.textContent = "开始分析";
  };

  let pollHandle = null;
  (async () => {
    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || `提交失败 (${resp.status})`);

      let fails = 0;
      pollHandle = setInterval(async () => {
        try {
          const pr = await fetch(`/api/job/${data.job_id}`);
          const pj = await pr.json();
          fails = 0;
          if (pj.status === "error") throw new Error(pj.error || "流水线执行失败");
          updateProgress(pj);
          if (pj.status === "done") {
            state.result = pj.result;
            render(pj.result);
            finish();
          }
        } catch (e) {
          if (++fails >= 3) { showError(e.message); finish(); }
        }
      }, 1500);
    } catch (err) {
      showError(err.message);
      finish();
    }
  })();
}

function updateProgress(pj) {
  const stages = pj.stages || [];
  const done = stages.filter(s => s.status === "done").length;
  const running = stages.find(s => s.status === "running");
  const pct = Math.min(96, (done / stages.length) * 100 + (running ? 8 : 0));
  setProgress(pct, running ? `正在${running.name}…` : "即将完成…");
  if (pj.elapsed != null) el.progressTimer.textContent = pj.elapsed.toFixed(0) + "s";
}

function setProgress(pct, label) {
  el.progressFill.style.width = pct + "%";
  el.progressLabel.textContent = label;
}

function showError(msg) {
  el.errorBar.textContent = "出错了：" + msg;
  el.errorBar.classList.remove("hidden");
  el.progressCard.classList.add("hidden");
}
function hideError() { el.errorBar.classList.add("hidden"); }

/* ---------------- 渲染 ---------------- */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function render(r) {
  renderProduct(r.product);
  renderAnalysis(r.analysis);
  renderCopy("zh", r.copy_zh, 150);
  renderCopy("en", r.copy_en, null);
  renderQC(r.quality_check);
  renderMeta(r);
  el.results.classList.remove("hidden");
  el.results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderProduct(p) {
  $("#pTitle").textContent = p.title || "（未获取到标题）";
  const gallery = $("#gallery");
  gallery.innerHTML = "";
  if (p.images?.length) {
    p.images.slice(0, 6).forEach(src => {
      const img = document.createElement("img");
      img.src = src; img.alt = "商品图片"; img.loading = "lazy";
      gallery.appendChild(img);
    });
  } else {
    gallery.innerHTML = '<div class="no-img">未提取到商品图片</div>';
  }

  const badges = [];
  if (p.price) badges.push(`<span class="badge price">${esc(p.currency || "")} ${esc(p.price)}</span>`);
  if (p.rating) badges.push(`<span class="badge">评分 ${esc(p.rating)}</span>`);
  if (p.reviews_count) badges.push(`<span class="badge">${esc(p.reviews_count)} 条评论</span>`);
  if (p.brand) badges.push(`<span class="badge">品牌 ${esc(p.brand)}</span>`);
  if (p.category) badges.push(`<span class="badge">${esc(p.category)}</span>`);
  if (p.asin) badges.push(`<span class="badge">ASIN ${esc(p.asin)}</span>`);
  $("#badgeRow").innerHTML = badges.join("");

  $("#pBullets").innerHTML = (p.bullets || [])
    .slice(0, 6)
    .map(b => `<li>${esc(b)}</li>`)
    .join("");

  const specs = p.specs || {};
  const keys = Object.keys(specs);
  $("#specsFold").classList.toggle("hidden", keys.length === 0);
  $("#specsTable").innerHTML = keys
    .slice(0, 16)
    .map(k => `<tr><td>${esc(k)}</td><td>${esc(specs[k])}</td></tr>`)
    .join("");
}

function renderAnalysis(a) {
  $("#positioning").textContent = a.positioning || "—";
  $("#blockUsers").innerHTML =
    "<h3>目标用户</h3><ul>" +
    (a.target_users || []).map(u => `<li><strong>${esc(u.segment)}</strong> — ${esc(u.reason)}</li>`).join("") +
    "</ul>";
  $("#blockScenarios").innerHTML =
    "<h3>使用场景</h3><ul>" +
    (a.use_scenarios || []).map(s => `<li><strong>${esc(s.scenario)}</strong> — ${esc(s.detail)}</li>`).join("") +
    "</ul>";
  $("#blockPains").innerHTML =
    "<h3>用户痛点</h3><ul>" +
    (a.pain_points || []).map(x => `<li>${esc(x)}</li>`).join("") +
    "</ul>";
  $("#blockPricing").innerHTML =
    "<h3>价格洞察</h3><p>" + esc(a.pricing_insight || "—") + "</p>" +
    (a.image_insights?.length
      ? "<h3 style='margin-top:12px'>视觉洞察</h3><ul>" +
        a.image_insights.map(x => `<li>${esc(x)}</li>`).join("") + "</ul>"
      : "");
  $("#blockSelling").innerHTML =
    "<h3>核心卖点</h3>" +
    (a.selling_points || []).map((s, i) =>
      `<div class="selling-item">
         <div class="sp-point"><span class="idx">${i + 1}</span>${esc(s.point)}</div>
         ${s.evidence ? `<div class="sp-evidence">${esc(s.evidence)}</div>` : ""}
         ${s.copy_angle ? `<div class="sp-angle">${esc(s.copy_angle)}</div>` : ""}
       </div>`).join("");
  const risks = a.risks_concerns || [];
  $("#blockRisks").innerHTML =
    risks.length ? "<h3>客观风险与顾虑</h3><ul>" + risks.map(x => `<li>${esc(x)}</li>`).join("") + "</ul>" : "";
}

function renderCopy(lang, copy, zhLimit) {
  if (!copy) return;
  const script = copy.script || "";
  $("#" + (lang === "zh" ? "zhHook" : "enHook")).textContent = copy.hook_5s || "—";
  $("#" + (lang === "zh" ? "zhScript" : "enScript")).textContent = script;
  const count = (script || "").replace(/\s/g, "").length;
  const cntEl = $("#" + (lang === "zh" ? "zhCount" : "enCount"));
  if (lang === "zh") {
    cntEl.textContent = `${count} / 150 字`;
    cntEl.classList.toggle("over", count > 150);
  } else {
    const words = (script.match(/[A-Za-z0-9']+/g) || []).length;
    cntEl.textContent = `${words} 词`;
  }
  $("#" + (lang === "zh" ? "zhShot" : "enShot")).textContent = copy.shot_suggestion || "";
}

function renderQC(qc) {
  const issueCount = qc.issues_found?.length || 0;
  const verdict = qc.verdict === "fixed" && issueCount > 0 ? "fixed" : "pass";
  $("#qcHead").innerHTML =
    `<span class="verdict ${verdict}">${verdict === "pass" ? "检查通过" : "已自动修正"}</span>
     <span class="qc-note">${
       verdict === "pass"
         ? "全部检查项通过，文案未做修改"
         : `发现 ${issueCount} 处问题，已自动修正后展示`
     }</span>`;
  $("#qcChecks").innerHTML = (qc.checks || []).map(c =>
    `<div class="check-item">
       <span class="st ${c.status === "pass" ? "pass" : "fail"}">${c.status === "pass" ? "PASS" : "FIX"}</span>
       <span><span class="ci-item">${esc(c.item)}</span><span class="ci-note">${esc(c.note || "")}</span></span>
     </div>`).join("");
}

function renderMeta(r) {
  const stepStr = (r.steps || []).map(s => `${s.name} ${s.seconds}s`).join(" · ");
  $("#metaBar").innerHTML =
    `<span><b>总耗时</b> ${r.elapsed}s</span>
     <span><b>抓取来源</b> ${r.fetch_source === "direct" ? "直连" : "reader 代理"}</span>
     <span><b>模型</b> ${esc(r.model)}</span>
     <span><b>图片理解</b> ${r.vision_enabled ? "已启用" : "未启用"}</span>
     <span style="flex-basis:100%">${esc(stepStr)}</span>`;
}
