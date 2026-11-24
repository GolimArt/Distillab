window.DistillabReaders = (() => {
  const CHAPTER_HEADING_RE = /^(?:الفصل|فصل|الباب|المجلد|Chapter|Ch\.?)\s+(?:[0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)\b/im;
  const CHAPTER_SPLIT_RE = /(?=^(?:الفصل|فصل|الباب|المجلد|Chapter|Ch\.?)\s+(?:[0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)\b)/im;
  const SERIES_HINT_RE = /^(.+?)[\s_\-.]+(?:المجلد|الجزء|كتاب|Vol\.?|Volume|Book|Part)[\s_\-]*([0-9٠-٩]+)/i;

  function decodeBuffer(buf) {
    const bytes = new Uint8Array(buf);
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      try {
        return new TextDecoder("windows-1256").decode(bytes);
      } catch {
        return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
      }
    }
  }

  async function sha256Hex(arrayBuffer) {
    const hashBuf = await crypto.subtle.digest("SHA-256", arrayBuffer);
    return Array.from(new Uint8Array(hashBuf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  function extractTextFromHtmlString(htmlStr) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(htmlStr, "text/html");
    doc.querySelectorAll("head, script, style, svg, noscript").forEach((el) => el.remove());

    const blockTags = new Set([
      "P", "DIV", "BR", "HR", "LI", "TR",
      "H1", "H2", "H3", "H4", "H5", "H6",
      "BLOCKQUOTE", "SECTION", "ARTICLE", "HEADER", "FOOTER"
    ]);

    const parts = [];
    function walk(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        parts.push(node.nodeValue || "");
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const isBlock = blockTags.has(node.tagName);
      if (isBlock) parts.push("\n");
      for (const child of node.childNodes) walk(child);
      if (isBlock) parts.push("\n");
    }

    if (doc.body) walk(doc.body);
    return parts
      .join("")
      .replace(/\u00a0/g, " ")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .split("\n")
      .map((l) => l.trim())
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  async function extractEpub(arrayBuffer) {
    if (!window.JSZip) throw new Error("مكتبة JSZip غير محملة.");
    const zip = await window.JSZip.loadAsync(arrayBuffer);

    const fileMap = {};
    Object.keys(zip.files).forEach((k) => {
      fileMap[k.toLowerCase()] = k;
    });

    let opfPath = null;
    const containerKey = fileMap["meta-inf/container.xml"];
    if (containerKey) {
      const cXml = await zip.files[containerKey].async("string");
      const cDoc = new DOMParser().parseFromString(cXml, "application/xml");
      const rf = cDoc.getElementsByTagNameNS("*", "rootfile")[0] || cDoc.querySelector("rootfile");
      if (rf) opfPath = rf.getAttribute("full-path");
    }

    if (!opfPath) {
      opfPath = Object.keys(zip.files).find((n) => n.toLowerCase().endsWith(".opf"));
    }
    if (!opfPath) throw new Error("ملف EPUB لا يحتوي على فهرس OPF صالح.");

    const actualOpf = zip.files[opfPath] ? opfPath : fileMap[opfPath.toLowerCase()];
    const opfDir = actualOpf.includes("/") ? actualOpf.slice(0, actualOpf.lastIndexOf("/") + 1) : "";
    const opfXml = await zip.files[actualOpf].async("string");
    const opfDoc = new DOMParser().parseFromString(opfXml, "application/xml");

    const manifest = {};
    const items = opfDoc.getElementsByTagNameNS("*", "item");
    for (const it of items) {
      const id = it.getAttribute("id");
      const href = it.getAttribute("href") || "";
      const mtype = it.getAttribute("media-type") || "";
      if (id && href) manifest[id] = { href, mtype };
    }

    const ordered = [];
    const seen = new Set();
    const itemrefs = opfDoc.getElementsByTagNameNS("*", "itemref");
    for (const ref of itemrefs) {
      const idref = ref.getAttribute("idref");
      const entry = manifest[idref];
      if (!entry) continue;
      if (entry.mtype && !/html|xml/i.test(entry.mtype)) continue;
      const cleanHref = decodeURIComponent(entry.href.split("#")[0]).replace(/\\/g, "/");
      const joined = normalizeZipPath(opfDir + cleanHref);
      const actual = zip.files[joined] ? joined : fileMap[joined.toLowerCase()];
      if (actual && !seen.has(actual)) {
        seen.add(actual);
        ordered.push(actual);
      }
    }

    const texts = [];
    for (const path of ordered) {
      const rawBuf = await zip.files[path].async("arraybuffer");
      const htmlStr = decodeBuffer(rawBuf);
      const txt = extractTextFromHtmlString(htmlStr);
      if (txt) texts.push(txt);
    }
    return texts.join("\n\n");
  }

  function normalizeZipPath(path) {
    const stack = [];
    for (const seg of path.split("/")) {
      if (!seg || seg === ".") continue;
      if (seg === "..") stack.pop();
      else stack.push(seg);
    }
    return stack.join("/");
  }

  async function extractDocx(arrayBuffer) {
    if (!window.JSZip) throw new Error("مكتبة JSZip غير محملة.");
    const zip = await window.JSZip.loadAsync(arrayBuffer);
    const docEntry = zip.files["word/document.xml"];
    if (!docEntry) throw new Error("ملف DOCX غير صالح (لا يحتوي word/document.xml).");
    const xmlStr = await docEntry.async("string");
    const xmlDoc = new DOMParser().parseFromString(xmlStr, "application/xml");
    const paras = xmlDoc.getElementsByTagNameNS("*", "p");
    const out = [];
    for (const p of paras) {
      const runs = p.getElementsByTagNameNS("*", "t");
      let line = "";
      for (const r of runs) line += r.textContent || "";
      if (line.trim()) out.push(line.trim());
    }
    return out.join("\n\n");
  }

  async function extractPdf(arrayBuffer) {
    if (!window.pdfjsLib) throw new Error("مكتبة PDF.js غير محملة.");
    window.pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

    const pdf = await window.pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    const pages = [];
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      const strings = content.items.map((it) => it.str || "");
      const pageTxt = strings.join(" ").replace(/\s+/g, " ").trim();
      if (pageTxt) pages.push(pageTxt);
    }
    return pages.join("\n\n");
  }

  async function extractCleanText(fileName, arrayBuffer) {
    const ext = (fileName.split(".").pop() || "").toLowerCase();
    if (ext === "epub") return extractEpub(arrayBuffer);
    if (ext === "docx") return extractDocx(arrayBuffer);
    if (ext === "pdf") return extractPdf(arrayBuffer);
    if (ext === "txt") {
      return decodeBuffer(arrayBuffer)
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
    }
    throw new Error(`صيغة غير مدعومة: .${ext}`);
  }

  function parseFilenameMetadata(fileName) {
    const base = fileName.replace(/\.[^.]+$/, "").trim();
    const m = SERIES_HINT_RE.exec(base);
    if (m) {
      const series = m[1].replace(/[\s_\-.]+$/, "").trim();
      const vol = parseInt(m[2].replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d)), 10) || 0;
      return { title: base, series_name: series, volume_number: vol };
    }
    return { title: base, series_name: "", volume_number: 0 };
  }

  function computeTextStats(text) {
    const words = text ? text.trim().split(/\s+/).filter(Boolean).length : 0;
    const chars = text ? text.length : 0;
    const matches = text ? text.match(new RegExp(CHAPTER_HEADING_RE.source, "gim")) : null;
    return { word_count: words, char_count: chars, chapter_count: matches ? matches.length : 0 };
  }

  function buildScoutSample(text, totalSampleWords = 4500) {
    const words = text.trim().split(/\s+/);
    const n = words.length;
    if (n <= totalSampleWords) return text;
    const hLen = Math.floor(totalSampleWords * 0.4);
    const mLen = Math.floor(totalSampleWords * 0.3);
    const tLen = totalSampleWords - hLen - mLen;
    const midStart = Math.max(hLen, Math.floor(n / 2) - Math.floor(mLen / 2));
    return (
      `[مقطع البداية]\n${words.slice(0, hLen).join(" ")}\n\n` +
      `[مقطع الوسط]\n${words.slice(midStart, midStart + mLen).join(" ")}\n\n` +
      `[مقطع النهاية]\n${words.slice(-tLen).join(" ")}`
    );
  }

  function splitTextIntoChunks(text, maxWords = 45000) {
    const totalWords = text.trim().split(/\s+/).length;
    if (totalWords <= maxWords) return [text];

    let sections = text.split(new RegExp(CHAPTER_SPLIT_RE.source, "gim")).map((s) => s.trim()).filter(Boolean);
    if (sections.length <= 1) {
      sections = text.split("\n\n").map((s) => s.trim()).filter(Boolean);
    }

    const blocks = [];
    for (const sec of sections) {
      if (sec.split(/\s+/).length > maxWords) {
        blocks.push(...sec.split("\n\n").map((p) => p.trim()).filter(Boolean));
      } else {
        blocks.push(sec);
      }
    }

    const chunks = [];
    let current = [];
    let count = 0;
    for (const blk of blocks) {
      const wc = blk.split(/\s+/).length;
      if (current.length && count + wc > maxWords) {
        chunks.push(current.join("\n\n"));
        current = [];
        count = 0;
      }
      current.push(blk);
      count += wc;
    }
    if (current.length) chunks.push(current.join("\n\n"));
    return chunks;
  }

  async function createCompressedTxtZip(baseName, text) {
    const zip = new window.JSZip();
    const safe = baseName.replace(/[\\/*?:"<>|]/g, "_");
    zip.file(`${safe}.txt`, text);
    return zip.generateAsync({
      type: "blob",
      compression: "DEFLATE",
      compressionOptions: { level: 9 }
    });
  }

  return {
    sha256Hex,
    extractCleanText,
    parseFilenameMetadata,
    computeTextStats,
    buildScoutSample,
    splitTextIntoChunks,
    createCompressedTxtZip
  };
})();