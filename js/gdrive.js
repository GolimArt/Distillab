// عميل Google Drive API v3 يعمل مباشرة من المتصفح عبر OAuth2 Refresh Token
export class GDriveBrowserClient {
  constructor(getSettingsFn, logFn = console.log) {
    this.getSettings = getSettingsFn;
    this.log = logFn;
    this.accessToken = "";
    this.tokenExpiry = 0;
    this.supportedExts = [".epub", ".pdf", ".docx", ".txt"];
  }

  isConfigured() {
    const s = this.getSettings();
    return Boolean(s.gdriveClientId && s.gdriveClientSecret && s.gdriveRefreshToken);
  }

  extractFolderId(input) {
    const val = (input || "").trim();
    if (!val) return "";
    const m = val.match(/\/folders\/([a-zA-Z0-9_-]+)/);
    if (m) return m[1];
    if (val.includes(" | [") && val.endsWith("]")) {
      return val.slice(val.lastIndexOf(" | [") + 4, -1);
    }
    return val;
  }

  async getAccessToken() {
    if (!this.isConfigured()) {
      throw new Error("بيانات Google Drive (Client ID / Secret / Refresh Token) غير مضبوطة في الإعدادات.");
    }
    if (this.accessToken && Date.now() < this.tokenExpiry - 120000) {
      return this.accessToken;
    }

    const s = this.getSettings();
    const body = new URLSearchParams({
      client_id: s.gdriveClientId.trim(),
      client_secret: s.gdriveClientSecret.trim(),
      refresh_token: s.gdriveRefreshToken.trim(),
      grant_type: "refresh_token",
    });

    const resp = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!resp.ok) {
      const errTxt = await resp.text();
      throw new Error(`فشل تجديد توكن Google Drive (${resp.status}): ${errTxt.slice(0, 250)}`);
    }
    const data = await resp.json();
    this.accessToken = data.access_token;
    this.tokenExpiry = Date.now() + Number(data.expires_in || 3600) * 1000;
    return this.accessToken;
  }

  async _authHeaders(extra = {}) {
    const token = await this.getAccessToken();
    return { Authorization: `Bearer ${token}`, ...extra };
  }

  async listFolders(searchQuery = "") {
    let q = "mimeType='application/vnd.google-apps.folder' and trashed=false";
    if (searchQuery.trim()) {
      const safe = searchQuery.trim().replace(/'/g, "\\'");
      q += ` and name contains '${safe}'`;
    }
    const params = new URLSearchParams({
      q,
      fields: "files(id, name, parents)",
      pageSize: "100",
      orderBy: "name",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
    });
    const resp = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: await this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`خطأ قراءة مجلدات Drive: ${await resp.text()}`);
    const data = await resp.json();
    return data.files || [];
  }

  async listNovelFiles(folderId) {
    const q = `'${folderId}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'`;
    const allFiles = [];
    let pageToken = "";

    do {
      const params = new URLSearchParams({
        q,
        fields: "nextPageToken, files(id, name, size)",
        pageSize: "200",
        orderBy: "name",
        supportsAllDrives: "true",
        includeItemsFromAllDrives: "true",
      });
      if (pageToken) params.set("pageToken", pageToken);

      const resp = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
        headers: await this._authHeaders(),
      });
      if (!resp.ok) throw new Error(`خطأ قراءة ملفات المجلد: ${await resp.text()}`);
      const data = await resp.json();

      for (const f of data.files || []) {
        const low = f.name.toLowerCase();
        if (this.supportedExts.some((ext) => low.endsWith(ext))) {
          allFiles.push(f);
        }
      }
      pageToken = data.nextPageToken || "";
    } while (pageToken);

    return allFiles;
  }

  async downloadFileAsArrayBuffer(fileId) {
    const url = `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?alt=media&supportsAllDrives=true`;
    const resp = await fetch(url, { headers: await this._authHeaders() });
    if (!resp.ok) throw new Error(`فشل تنزيل الملف من Drive: ${await resp.text()}`);
    return await resp.arrayBuffer();
  }

  async ensureProjectRoot(folderName = "Distillab_Cloud") {
    const s = this.getSettings();
    if (s.gdriveRootFolderId && s.gdriveRootFolderId.trim()) {
      return s.gdriveRootFolderId.trim();
    }
    const safe = folderName.replace(/'/g, "\\'");
    const params = new URLSearchParams({
      q: `name='${safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false`,
      fields: "files(id, name)",
    });
    const resp = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: await this._authHeaders(),
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.files && data.files.length > 0) return data.files[0].id;
    }

    const createResp = await fetch("https://www.googleapis.com/drive/v3/files", {
      method: "POST",
      headers: await this._authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        name: folderName,
        mimeType: "application/vnd.google-apps.folder",
      }),
    });
    if (!createResp.ok) throw new Error(`تعذر إنشاء مجلد المشروع في Drive: ${await createResp.text()}`);
    const created = await createResp.json();
    return created.id;
  }

  async ensureSubfolder(parentId, folderName) {
    const safe = folderName.replace(/'/g, "\\'");
    const params = new URLSearchParams({
      q: `name='${safe}' and '${parentId}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false`,
      fields: "files(id, name)",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
    });
    const resp = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: await this._authHeaders(),
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.files && data.files.length > 0) return data.files[0].id;
    }

    const createResp = await fetch("https://www.googleapis.com/drive/v3/files?supportsAllDrives=true", {
      method: "POST",
      headers: await this._authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        name: folderName,
        mimeType: "application/vnd.google-apps.folder",
        parents: [parentId],
      }),
    });
    if (!createResp.ok) throw new Error(`تعذر إنشاء مجلد فرعي: ${await createResp.text()}`);
    return (await createResp.json()).id;
  }

  async uploadOrUpdateBlob(filename, blob, parentId) {
    const safe = filename.replace(/'/g, "\\'");
    const params = new URLSearchParams({
      q: `name='${safe}' and '${parentId}' in parents and trashed=false`,
      fields: "files(id)",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
    });
    const checkResp = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: await this._authHeaders(),
    });

    let existingId = null;
    if (checkResp.ok) {
      const checkData = await checkResp.json();
      if (checkData.files && checkData.files.length > 0) {
        existingId = checkData.files[0].id;
      }
    }

    if (existingId) {
      const patchResp = await fetch(
        `https://www.googleapis.com/upload/drive/v3/files/${existingId}?uploadType=media&supportsAllDrives=true`,
        {
          method: "PATCH",
          headers: await this._authHeaders({
            "Content-Type": blob.type || "application/octet-stream",
          }),
          body: blob,
        }
      );
      if (!patchResp.ok) throw new Error(`فشل تحديث '${filename}': ${await patchResp.text()}`);
      return (await patchResp.json()).id;
    }

    const boundary = "distillab_web_boundary_" + Math.random().toString(36).slice(2);
    const metaPart =
      `--${boundary}\r\n` +
      `Content-Type: application/json; charset=UTF-8\r\n\r\n` +
      `${JSON.stringify({ name: filename, parents: [parentId] })}\r\n` +
      `--${boundary}\r\n` +
      `Content-Type: ${blob.type || "application/octet-stream"}\r\n\r\n`;
    const endPart = `\r\n--${boundary}--`;
    const multipartBlob = new Blob([metaPart, blob, endPart], {
      type: `multipart/related; boundary=${boundary}`,
    });

    const postResp = await fetch(
      "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true",
      {
        method: "POST",
        headers: await this._authHeaders({
          "Content-Type": `multipart/related; boundary=${boundary}`,
        }),
        body: multipartBlob,
      }
    );
    if (!postResp.ok) throw new Error(`فشل رفع '${filename}': ${await postResp.text()}`);
    return (await postResp.json()).id;
  }

  async deleteOrTrashDriveFile(fileId, permanent = false) {
    if (!fileId) return;
    if (permanent) {
      const resp = await fetch(
        `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?supportsAllDrives=true`,
        { method: "DELETE", headers: await this._authHeaders() }
      );
      if (!resp.ok && resp.status !== 404) {
        throw new Error(`فشل الحذف النهائي من Drive: ${await resp.text()}`);
      }
      return;
    }
    const resp = await fetch(
      `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?supportsAllDrives=true`,
      {
        method: "PATCH",
        headers: await this._authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ trashed: true }),
      }
    );
    if (!resp.ok) throw new Error(`فشل النقل إلى سلة مهملات Drive: ${await resp.text()}`);
  }

  async syncExportsToDrive(exportedArtifacts, backupZipBlob = null, backupName = "") {
    if (!this.isConfigured()) return 0;
    const rootId = await this.ensureProjectRoot("Distillab_Cloud");
    const exportsRootId = await this.ensureSubfolder(rootId, "_Vault_Exports");

    const folderCache = {};
    let uploaded = 0;

    for (const art of exportedArtifacts) {
      if (!folderCache[art.lensFolder]) {
        folderCache[art.lensFolder] = await this.ensureSubfolder(exportsRootId, art.lensFolder);
      }
      await this.uploadOrUpdateBlob(art.filename, art.blob, folderCache[art.lensFolder]);
      uploaded++;
    }

    if (backupZipBlob && backupName) {
      const backupsId = await this.ensureSubfolder(rootId, "_Backups");
      await this.uploadOrUpdateBlob(backupName, backupZipBlob, backupsId);
      uploaded++;
    }

    this.log(`[Drive Sync] تم رفع وتحديث ${uploaded} ملف في Google Drive بنجاح.`);
    return uploaded;
  }
}