window.DISTILLAB_DEFAULT_CONFIG = {
  active_provider: "gemini",
  providers: {
    gemini: {
      type: "gemini",
      base_url: "https://generativelanguage.googleapis.com/v1beta",
      scout_model: "gemini-2.5-flash",
      distill_model: "gemini-2.5-flash",
      meta_model: "gemini-2.5-pro",
      api_keys: [],
      min_delay_sec: 6.5,
      temperature: 0.25
    },
    openai_compatible: {
      type: "openai",
      base_url: "https://api.groq.com/openai/v1",
      scout_model: "llama-3.3-70b-versatile",
      distill_model: "llama-3.3-70b-versatile",
      meta_model: "llama-3.3-70b-versatile",
      api_keys: [],
      min_delay_sec: 3.5,
      temperature: 0.25
    }
  },
  chunk_mode: "smart_chunks",
  chunk_max_words: 45000,
  full_novel_max_words: 130000,
  export_max_words_per_part: 350000,
  meta_batch_size: 8,
  custom_mutation_target: "",
  post_complete_action: "archive_compressed",
  delete_drive_source: false,
  gdrive_client_id: "",
  gdrive_client_secret: "",
  gdrive_refresh_token: "",
  gdrive_root_folder_id: ""
};

class DistillabDB {
  constructor() {
    this.dbName = "DistillabBrowserDB";
    this.version = 1;
    this.db = null;
  }

  async open() {
    if (this.db) return this.db;
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(this.dbName, this.version);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("settings")) {
          db.createObjectStore("settings", { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains("novels")) {
          const st = db.createObjectStore("novels", { keyPath: "id", autoIncrement: true });
          st.createIndex("file_hash", "file_hash", { unique: true });
          st.createIndex("status", "status", { unique: false });
        }
        if (!db.objectStoreNames.contains("chunks")) {
          const st = db.createObjectStore("chunks", { keyPath: "key" });
          st.createIndex("novel_id", "novel_id", { unique: false });
        }
        if (!db.objectStoreNames.contains("analyses")) {
          db.createObjectStore("analyses", { keyPath: "novel_id" });
        }
        if (!db.objectStoreNames.contains("meta_batches")) {
          const st = db.createObjectStore("meta_batches", { keyPath: "key" });
          st.createIndex("lens_id", "lens_id", { unique: false });
        }
        if (!db.objectStoreNames.contains("meta_final")) {
          db.createObjectStore("meta_final", { keyPath: "lens_id" });
        }
        if (!db.objectStoreNames.contains("exports")) {
          db.createObjectStore("exports", { keyPath: "key" });
        }
      };
      req.onsuccess = (e) => {
        this.db = e.target.result;
        resolve(this.db);
      };
      req.onerror = () => reject(req.error);
    });
  }

  async _tx(storeName, mode, fn) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);
      const req = fn(store);
      if (req && typeof req.onsuccess !== "undefined") {
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      } else {
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => reject(tx.error);
      }
    });
  }

  async getAll(storeName) {
    return this._tx(storeName, "readonly", (s) => s.getAll());
  }

  async get(storeName, key) {
    return this._tx(storeName, "readonly", (s) => s.get(key));
  }

  async put(storeName, obj) {
    return this._tx(storeName, "readwrite", (s) => s.put(obj));
  }

  async del(storeName, key) {
    return this._tx(storeName, "readwrite", (s) => s.delete(key));
  }

  async clearStore(storeName) {
    return this._tx(storeName, "readwrite", (s) => s.clear());
  }

  // -------- الإعدادات --------
  async getConfig() {
    const row = await this.get("settings", "app_config");
    const def = JSON.parse(JSON.stringify(window.DISTILLAB_DEFAULT_CONFIG));
    if (!row || !row.value) return def;
    const saved = row.value;
    return {
      ...def,
      ...saved,
      providers: {
        gemini: { ...def.providers.gemini, ...(saved.providers?.gemini || {}) },
        openai_compatible: { ...def.providers.openai_compatible, ...(saved.providers?.openai_compatible || {}) }
      }
    };
  }

  async saveConfig(cfg) {
    await this.put("settings", { key: "app_config", value: cfg });
  }

  // -------- الروايات --------
  async getNovelByHash(fileHash) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("novels", "readonly");
      const idx = tx.objectStore("novels").index("file_hash");
      const req = idx.get(fileHash);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async listNovels(status = null, lensId = null) {
    const all = await this.getAll("novels");
    return all
      .filter((n) => (!status || n.status === status) && (!lensId || n.primary_lens === lensId))
      .sort((a, b) => {
        const s = (a.series_name || "").localeCompare(b.series_name || "");
        if (s !== 0) return s;
        const v = (a.volume_number || 0) - (b.volume_number || 0);
        return v !== 0 ? v : a.id - b.id;
      });
  }

  async addOrUpdateScannedNovel(data) {
    const existing = await this.getNovelByHash(data.file_hash);
    const now = new Date().toISOString();
    if (existing) {
      if (data.raw_text) existing.raw_text = data.raw_text;
      if (data.drive_file_id) existing.drive_file_id = data.drive_file_id;
      existing.updated_at = now;
      await this.put("novels", existing);
      return { id: existing.id, isNew: false };
    }
    const id = await this.put("novels", {
      file_hash: data.file_hash,
      file_name: data.file_name,
      file_format: data.file_format,
      drive_file_id: data.drive_file_id || "",
      raw_text: data.raw_text || "",
      word_count: data.word_count || 0,
      char_count: data.char_count || 0,
      chapter_count: data.chapter_count || 0,
      title: data.title || data.file_name,
      author: "",
      series_name: data.series_name || "",
      volume_number: data.volume_number || 0,
      primary_lens: "",
      sub_tags: [],
      synopsis: "",
      status: "scanned",
      error_msg: "",
      cleanup_done: false,
      drive_source_trashed: false,
      created_at: now,
      updated_at: now
    });
    return { id, isNew: true };
  }

  // -------- المقاطع --------
  async getChunksForNovel(novelId) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("chunks", "readonly");
      const idx = tx.objectStore("chunks").index("novel_id");
      const req = idx.getAll(novelId);
      req.onsuccess = () => resolve((req.result || []).sort((a, b) => a.chunk_index - b.chunk_index));
      req.onerror = () => reject(req.error);
    });
  }

  async clearChunksForNovel(novelId) {
    const rows = await this.getChunksForNovel(novelId);
    for (const r of rows) {
      await this.del("chunks", r.key);
    }
  }

  // -------- التحليلات والقسم 10 --------
  async getDistilledNovelsWithAnalyses(lensId) {
    const novels = await this.listNovels("distilled", lensId);
    const out = [];
    for (const n of novels) {
      const a = await this.get("analyses", n.id);
      if (a) {
        out.push({
          ...n,
          sections: a.sections,
          model_used: a.model_used,
          analysis_updated_at: a.updated_at
        });
      }
    }
    return out;
  }

  async getMetaBatchesForLens(lensId) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("meta_batches", "readonly");
      const idx = tx.objectStore("meta_batches").index("lens_id");
      const req = idx.getAll(lensId);
      req.onsuccess = () => resolve((req.result || []).sort((a, b) => a.batch_index - b.batch_index));
      req.onerror = () => reject(req.error);
    });
  }

  // -------- النسخ الاحتياطي والمزامنة --------
  async exportSnapshotObject() {
    const novels = (await this.getAll("novels")).map((n) => ({
      ...n,
      raw_text: "" // نستثني النص الضخم من ملف المزامنة الخفيف
    }));
    const analyses = await this.getAll("analyses");
    const meta_batches = await this.getAll("meta_batches");
    const meta_final = await this.getAll("meta_final");
    const chunks = (await this.getAll("chunks")).map((c) => ({ ...c, chunk_text: "" }));
    return {
      schema_version: 1,
      exported_at: new Date().toISOString(),
      novels,
      analyses,
      meta_batches,
      meta_final,
      chunks
    };
  }

  async importSnapshotObject(snap) {
    if (!snap || !Array.isArray(snap.novels)) {
      throw new Error("ملف النسخة الاحتياطية غير صالح.");
    }
    for (const n of snap.novels) await this.put("novels", n);
    for (const a of snap.analyses || []) await this.put("analyses", a);
    for (const mb of snap.meta_batches || []) await this.put("meta_batches", mb);
    for (const mf of snap.meta_final || []) await this.put("meta_final", mf);
    for (const ch of snap.chunks || []) await this.put("chunks", ch);
    return snap.novels.length;
  }

  async wipeAllLocalData() {
    for (const s of ["novels", "chunks", "analyses", "meta_batches", "meta_final", "exports"]) {
      await this.clearStore(s);
    }
  }
}

window.distillabDB = new DistillabDB();