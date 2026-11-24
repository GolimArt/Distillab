/* global JSZip, DistillabDB, BrowserGDriveClient, BrowserPipeline, DEFAULT_LENSES, generateExportArtifacts */

const db = new DistillabDB();
let pipeline = null;
let wakeLockSentinel = null;
let generatedArtifacts = [];

const $ = (id) => document.getElementById(id);

function appendLog(msg) {
  const box = $("log-box");
  const ts = new Date().toLocaleTimeString("ar-EG", { hour12: false });
  box.textContent += `[${ts}] ${msg}\n`;
  box.scrollTop = box.scrollHeight;
}

function setProgress(pct, label) {
  $("progress-bar").style.width = `${Math.min(100, Math.max(0, pct))}%`;
  $("progress-label").textContent = label || "";
}

async function acquireWakeLockIfEnabled() {
  if (!$("chk-wakelock").checked || !("wakeLock" in navigator)) return;
  try {
    wakeLockSentinel = await navigator.wakeLock.request("screen");
    appendLog("🔆 تم تفعيل منع انطفاء الشاشة أثناء التشغيل.");
  } catch {}
}

async function releaseWakeLock() {
  if (wakeLockSentinel) {
    try { await wakeLockSentinel.release(); } catch {}
    wakeLockSentinel = null;
  }
}

async function refreshStats() {
  const novels = await db.getAllNovels();
  const cfg = await db.getSettings();
  const bySt = {};
  const byLens = {};
  for (const n of novels) {
    bySt[n.status] = (bySt[n.status] || 0) + 1;
    if (n.primaryLens) byLens[n.primaryLens] = (byLens[n.primaryLens] || 0) + 1;
  }
  const gdStatus = (cfg.gdriveClientId && cfg.gdriveClientSecret && cfg.gdriveRefreshToken) ? "مربوط (API دائم)" : "غير مربوط";
  const lines = [
    `ربط Google Drive: ${gdStatus} | مفاتيح AI: ${(cfg.apiKeys || []).length}`,
    `إجمالي الروايات: ${novels.length}`,
    `بانتظار الفرز (scanned): ${bySt.scanned || 0}`,
    `مصنفة (scouted): ${bySt.scouted || 0}`,
    `قيد الاستئناف (chunking): ${bySt.chunking || 0}`,
    `مكتملة (distilled): ${bySt.distilled || 0}`,
    `أخطاء (error): ${bySt.error || 0}`,
    "--- توزيع العدسات ---"
  ];
  for (const [lid, cnt] of Object.entries(byLens)) {
    lines.push(`• ${(DEFAULT_LENSES[lid] || {}).display_name || lid}: ${cnt}`);
  }
  $("stats-box").textContent = lines.join("\n");
}

async function refreshLibraryTable() {
  const novels = await db.getAllNovels();
  const tbody = $("lib-tbody");
  tbody.innerHTML = "";
  for (const n of novels) {
    const tr = document.createElement("tr");
    const lensName = (DEFAULT_LENSES[n.primaryLens] || {}).display_name || "-";
    tr.innerHTML = `
      <td>${n.id}</td>
      <td>${n.title || n.fileName}</td>
      <td>${n.seriesName ? `${n.seriesName} (م${n.volumeNumber || 0})` : "-"}</td>
      <td>${lensName}</td>
      <td>${(n.wordCount || 0).toLocaleString()}</td>
      <td><span class="badge badge-${n.status}">${n.status}</span></td>
      <td>${n.cleanupDone ? "نعم" : "لا"}</td>
      <td>${(n.errorMsg || "").slice(0, 50)}</td>
      <td><button class="btn btn-danger" data-del-id="${n.id}" style="padding:3px 8px;font-size:0.78rem;">حذف</button></td>
    `;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("button[data-del-id]").forEach((btn) => {
    btn.onclick = async () => {
      const id = Number(btn.getAttribute("data-del-id"));
      if (confirm("حذف هذه الرواية من المكتبة؟")) {
        await db.deleteNovel(id);
        await refreshLibraryTable();
        await refreshStats();
      }
    };
  });
}

async function loadSettingsUI() {
  const c = await db.getSettings();
  $("cfg-provider").value = c.provider;
  $("cfg-base-url").value = c.baseUrl;
  $("cfg-scout-model").value = c.scoutModel;
  $("cfg-distill-model").value = c.distillModel;
  $("cfg-meta-model").value = c.metaModel;
  $("cfg-api-keys").value = (c.apiKeys || []).join("\n");
  $("cfg-delay").value = c.minDelaySec;
  $("cfg-chunk-mode").value = c.chunkMode;
  $("cfg-chunk-words").value = c.chunkMaxWords;
  $("cfg-export-words").value = c.exportMaxWordsPerPart;
  $("cfg-meta-batch").value = c.metaBatchSize;
  $("cfg-mut-target").value = c.customMutationTarget || "";
  $("cfg-cleanup-action").value = c.postCompleteAction || "archive_compressed";
  $("cfg-gd-client-id").value = c.gdriveClientId || "";
  $("cfg-gd-client-secret").value = c.gdriveClientSecret || "";
  $("cfg-gd-refresh").value = c.gdriveRefreshToken || "";
}

async function saveSettingsUI() {
  const cur = await db.getSettings();
  const next = {
    ...cur,
    provider: $("cfg-provider").value,
    baseUrl: $("cfg-base-url").value.trim(),
    scoutModel: $("cfg-scout-model").value.trim(),
    distillModel: $("cfg-distill-model").value.trim(),
    metaModel: $("cfg-meta-model").value.trim(),
    apiKeys: $("cfg-api-keys").value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean),
    minDelaySec: Number($("cfg-delay").value) || 6.5,
    chunkMode: $("cfg-chunk-mode").value,
    chunkMaxWords: Number($("cfg-chunk-words").value) || 45000,
    exportMaxWordsPerPart: Number($("cfg-export-words").value) || 350000,
    metaBatchSize: Number($("cfg-meta-batch").value) || 8,
    customMutationTarget: $("cfg-mut-target").value.trim(),
    postCompleteAction: $("cfg-cleanup-action").value,
    gdriveClientId: $("cfg-gd-client-id").value.trim(),
    gdriveClientSecret: $("cfg-gd-client-secret").value.trim(),
    gdriveRefreshToken: $("cfg-gd-refresh").value.trim()
  };
  await db.saveSettings(next);
  $("cfg-status").textContent = "تم حفظ الإعدادات محلياً في المتصفح بنجاح!";
  await refreshStats();
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function extractFolderId(val) {
  const s = (val || "").trim();
  const m = s.match(/\/folders\/([a-zA-Z0-9_-]+)/);
  return m ? m[1] : s;
}

async function initApp() {
  await db.open();
  pipeline = new BrowserPipeline(db, appendLog, setProgress);

  // تعبئة قوائم العدسات
  const lensOpts = `<option value="">الكل</option>` + Object.entries(DEFAULT_LENSES).map(([k, v]) => `<option value="${k}">${v.display_name}</option>`).join("");
  $("run-lens").innerHTML = lensOpts;
  $("export-lens").innerHTML = lensOpts;

  // التبويبات
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(btn.getAttribute("data-tab")).classList.add("active");
    };
  });

  // أزرار التشغيل
  const runSafe = async (fn) => {
    $("log-box").textContent = "";
    setProgress(5, "جارٍ البدء...");
    await acquireWakeLockIfEnabled();
    try {
      await fn();
      setProgress(100, "انتهى.");
    } catch (e) {
      appendLog(`! خطأ: ${e.message}`);
    } finally {
      await releaseWakeLock();
      await refreshStats();
      await refreshLibraryTable();
    }
  };

  $("btn-stop").onclick = () => {
    if (pipeline) pipeline.requestStop();
    appendLog("⏹ تم طلب الإيقاف الآمن — سيتوقف بعد الطلب الحالي مباشرة.");
  };

  $("btn-scout").onclick = () => runSafe(() => pipeline.runScout(Number($("run-limit").value) || 0));
  $("btn-distill").onclick = () => runSafe(() => pipeline.runDistillation(Number($("run-limit").value) || 0, $("run-lens").value || null));
  $("btn-meta").onclick = () => runSafe(() => pipeline.runMetaSynthesis($("run-lens").value || null));
  $("btn-cleanup").onclick = () => runSafe(() => pipeline.runCleanup());

  $("btn-full").onclick = () => runSafe(async () => {
    const lim = Number($("run-limit").value) || 0;
    const lf = $("run-lens").value || null;
    await pipeline.runScout(lim);
    await pipeline.runDistillation(lim, lf);
    await pipeline.runMetaSynthesis(lf);
    await pipeline.runCleanup();
    appendLog("🎉 اكتملت الدورة! اذهب إلى تبويب (التصدير والمزامنة) لتحميل الملفات أو رفعها إلى Drive.");
  });

  // رفع محلي
  $("btn-local-import").onclick = async () => {
    const files = $("local-file-input").files;
    if (!files || !files.length) { $("local-import-status").textContent = "اختر ملفاً واحداً على الأقل."; return; }
    let added = 0, skipped = 0;
    for (const f of files) {
      try {
        $("local-import-status").textContent = `جارٍ قراءة: ${f.name}...`;
        const buf = await f.arrayBuffer();
        const res = await pipeline.ingestFileBuffer(f.name, buf);
        if (res.added) added++; else skipped++;
      } catch (e) {
        appendLog(`! فشل قراءة ${f.name}: ${e.message}`);
      }
    }
    $("local-import-status").textContent = `تمت إضافة ${added} رواية (تم تخطي ${skipped} مكررة).`;
    await refreshStats();
    await refreshLibraryTable();
  };

  // استيراد Google Drive
  $("btn-drv-folders").onclick = async () => {
    const gd = new BrowserGDriveClient(await db.getSettings());
    try {
      $("drv-status").textContent = "جارٍ جلب المجلدات من Drive...";
      const folders = await gd.listFolders($("drv-search").value.trim());
      $("drv-folder-select").innerHTML = folders.map((f) => `<option value="${f.id}">${f.name}</option>`).join("");
      $("drv-status").textContent = `تم العثور على ${folders.length} مجلد.`;
    } catch (e) {
      $("drv-status").textContent = `خطأ: ${e.message}`;
    }
  };

  $("btn-drv-files").onclick = async () => {
    const gd = new BrowserGDriveClient(await db.getSettings());
    const fid = extractFolderId($("drv-custom").value) || $("drv-folder-select").value;
    if (!fid) { $("drv-status").textContent = "اختر مجلداً أو الصق رابط المجلد."; return; }
    try {
      $("drv-status").textContent = "جارٍ قراءة قائمة الملفات...";
      const files = await gd.listNovelFiles(fid);
      const listEl = $("drv-files-list");
      listEl.innerHTML = files.map((f) =>
        `<label class="file-item"><input type="checkbox" value="${f.id}" data-fname="${f.name}"><span>${f.name}</span></label>`
      ).join("");
      $("drv-status").textContent = `تم العثور على ${files.length} رواية داخل المجلد.`;
    } catch (e) {
      $("drv-status").textContent = `خطأ: ${e.message}`;
    }
  };

  $("btn-drv-sel-all").onclick = () => $("drv-files-list").querySelectorAll("input[type=checkbox]").forEach((c) => { c.checked = true; });
  $("btn-drv-sel-none").onclick = () => $("drv-files-list").querySelectorAll("input[type=checkbox]").forEach((c) => { c.checked = false; });

  $("btn-drv-import").onclick = async () => {
    const gd = new BrowserGDriveClient(await db.getSettings());
    const checked = Array.from($("drv-files-list").querySelectorAll("input[type=checkbox]:checked"));
    if (!checked.length) { $("drv-status").textContent = "حدد ملفات أولاً."; return; }
    let added = 0;
    for (let i = 0; i < checked.length; i++) {
      const fid = checked[i].value;
      const fname = checked[i].getAttribute("data-fname");
      try {
        $("drv-status").textContent = `(${i + 1}/${checked.length}) جارٍ تنزيل ومعالجة: ${fname}...`;
        const buf = await gd.downloadArrayBuffer(fid);
        const res = await pipeline.ingestFileBuffer(fname, buf);
        if (res.added) added++;
      } catch (e) {
        appendLog(`! تعذر استيراد ${fname}: ${e.message}`);
      }
    }
    $("drv-status").textContent = `تم استيراد ${added} رواية جديدة إلى المتصفح بنجاح!`;
    await refreshStats();
    await refreshLibraryTable();
  };

  // المكتبة والبحث
  $("btn-lib-refresh").onclick = refreshLibraryTable;
  $("btn-lib-retry").onclick = async () => {
    const all = await db.getAllNovels();
    let cnt = 0;
    for (const n of all) {
      if (n.status === "error") {
        n.status = n.primaryLens ? "scouted" : "scanned";
        n.errorMsg = "";
        await db.saveNovel(n);
        cnt++;
      }
    }
    appendLog(`تمت إعادة تفعيل ${cnt} رواية متعطلة.`);
    await refreshLibraryTable();
    await refreshStats();
  };

  $("btn-search").onclick = async () => {
    const kw = $("search-kw").value.trim();
    if (!kw) return;
    const all = await db.getAllNovels();
    const hits = [];
    for (const n of all) {
      if (n.status !== "distilled" || !n.sections) continue;
      const sec = n.sections;
      (sec.section_1_philosophy || []).forEach((q) => {
        if (JSON.stringify(q).includes(kw)) hits.push(`[${n.title} | مقولة] "${q.quote}" — ${q.psychological_rule}`);
      });
      (sec.section_2_dialogues || []).forEach((d) => {
        if (JSON.stringify(d).includes(kw)) hits.push(`[${n.title} | حوار] ${d.title} (${d.tactic_name}): ${d.tactical_breakdown}`);
      });
      (sec.section_4_foreshadowing || []).forEach((f) => {
        if (JSON.stringify(f).includes(kw)) hits.push(`[${n.title} | بذرة] ${f.title}: ${f.early_seed} --> ${f.payoff_twist}`);
      });
      (sec.section_7_micro_tactics || []).forEach((t) => {
        if (JSON.stringify(t).includes(kw)) hits.push(`[${n.title} | تكتيك] ${t.name}: ${t.abstract_equation}`);
      });
    }
    $("search-res").textContent = hits.length ? hits.slice(0, 50).join("\n\n") : `لا توجد نتائج لـ: ${kw}`;
  };

  // التصدير والمزامنة
  const buildExportsUI = async () => {
    $("export-status").textContent = "جارٍ تجهيز ملفات DOCX و MD (مع التقسيم التلقائي وفهرسة الأجزاء)...";
    generatedArtifacts = await generateExportArtifacts(db, $("export-lens").value || null);
    const list = $("export-list");
    list.innerHTML = "";
    generatedArtifacts.forEach((art, idx) => {
      const row = document.createElement("div");
      row.className = "file-item";
      row.style.justifyContent = "space-between";
      row.innerHTML = `<span>${art.folder} / <strong>${art.name}</strong></span><button class="btn" data-exp-idx="${idx}">⬇️ تحميل</button>`;
      list.appendChild(row);
    });
    list.querySelectorAll("button[data-exp-idx]").forEach((b) => {
      b.onclick = () => {
        const a = generatedArtifacts[Number(b.getAttribute("data-exp-idx"))];
        downloadBlob(a.blob, a.name);
      };
    });
    $("export-status").textContent = `تم تجهيز ${generatedArtifacts.length} ملفاً جاهزاً للتحميل أو الرفع لـ Drive.`;
  };

  $("btn-export-zip").onclick = async () => {
    await buildExportsUI();
    if (!generatedArtifacts.length) return;
    const zip = new JSZip();
    for (const a of generatedArtifacts) {
      zip.folder(a.folder).file(a.name, a.blob);
    }
    const zBlob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
    downloadBlob(zBlob, `Distillab_Exports_${new Date().toISOString().slice(0, 10)}.zip`);
  };

  $("btn-export-drive").onclick = async () => {
    await buildExportsUI();
    if (!generatedArtifacts.length) return;
    const gd = new BrowserGDriveClient(await db.getSettings());
    try {
      $("export-status").textContent = "جارٍ إنشاء المجلدات ورفع ملفات DOCX و MD إلى Google Drive...";
      const rootId = await gd.ensureFolder("Distillab_Cloud");
      const expId = await gd.ensureFolder("_Vault_Exports", rootId);
      const cacheFolders = {};
      for (let i = 0; i < generatedArtifacts.length; i++) {
        const a = generatedArtifacts[i];
        if (!cacheFolders[a.folder]) cacheFolders[a.folder] = await gd.ensureFolder(a.folder, expId);
        $("export-status").textContent = `(${i + 1}/${generatedArtifacts.length}) رفع: ${a.name}...`;
        await gd.uploadOrUpdateBlob(a.name, a.blob, cacheFolders[a.folder]);
      }
      $("export-status").textContent = `تم رفع جميع الملفات (${generatedArtifacts.length}) إلى Distillab_Cloud في Google Drive بنجاح!`;
    } catch (e) {
      $("export-status").textContent = `خطأ أثناء الرفع: ${e.message}`;
    }
  };

  // مزامنة قاعدة البيانات بين الأجهزة (Drive / JSON)
  $("btn-vault-push-drive").onclick = async () => {
    const gd = new BrowserGDriveClient(await db.getSettings());
    try {
      $("vault-sync-status").textContent = "جارٍ رفع نسخة قاعدة البيانات (بدون المفاتيح السرية) إلى Drive...";
      const jsonStr = await db.exportFullVaultJSON(false);
      const rootId = await gd.ensureFolder("Distillab_Cloud");
      const bkpId = await gd.ensureFolder("_Backups", rootId);
      await gd.uploadOrUpdateBlob("distillab_vault_sync.json", new Blob([jsonStr], { type: "application/json" }), bkpId);
      $("vault-sync-status").textContent = "تمت مزامنة قاعدة البيانات إلى Drive بنجاح! يمكنك استرجاعها من الهاتف الآن.";
    } catch (e) {
      $("vault-sync-status").textContent = `خطأ: ${e.message}`;
    }
  };

  $("btn-vault-pull-drive").onclick = async () => {
    const gd = new BrowserGDriveClient(await db.getSettings());
    try {
      $("vault-sync-status").textContent = "جارٍ البحث عن distillab_vault_sync.json في Drive...";
      const rootId = await gd.ensureFolder("Distillab_Cloud");
      const bkpId = await gd.ensureFolder("_Backups", rootId);
      const f = await gd.findFileInFolder("distillab_vault_sync.json", bkpId);
      if (!f) { $("vault-sync-status").textContent = "لا توجد نسخة مزامنة في Drive بعد."; return; }
      const buf = await gd.downloadArrayBuffer(f.id);
      const cnt = await db.importFullVaultJSON(new TextDecoder("utf-8").decode(buf));
      $("vault-sync-status").textContent = `تم استيراد ودمج ${cnt} رواية من Drive بنجاح!`;
      await refreshStats();
      await refreshLibraryTable();
    } catch (e) {
      $("vault-sync-status").textContent = `خطأ: ${e.message}`;
    }
  };

  $("btn-vault-dl-json").onclick = async () => {
    const jsonStr = await db.exportFullVaultJSON(false);
    downloadBlob(new Blob([jsonStr], { type: "application/json" }), `Distillab_Vault_${new Date().toISOString().slice(0, 10)}.json`);
  };

  $("btn-vault-restore-json").onclick = async () => {
    const file = $("vault-restore-input").files[0];
    if (!file) { $("vault-sync-status").textContent = "اختر ملف JSON أولاً."; return; }
    const txt = await file.text();
    const cnt = await db.importFullVaultJSON(txt);
    $("vault-sync-status").textContent = `تمت استعادة ${cnt} رواية بنجاح!`;
    await refreshStats();
    await refreshLibraryTable();
  };

  $("btn-save-cfg").onclick = saveSettingsUI;

  await loadSettingsUI();
  await refreshStats();
  await refreshLibraryTable();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}

window.addEventListener("DOMContentLoaded", initApp);