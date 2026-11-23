import hashlib
import os
import posixpath
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote

SUPPORTED_EXTS = {".epub", ".pdf", ".docx", ".txt"}

CHAPTER_HEADING_RE = re.compile(
    r"(?m)^(?=(?:الفصل|فصل|الباب|المجلد|Chapter|Ch\.?)\s+(?:[0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)\b)",
    re.IGNORECASE
)

SERIES_HINT_RE = re.compile(
    r"^(?P<series>.+?)[\s_\-\.]+(?:المجلد|الجزء|كتاب|Vol\.?|Volume|Book|Part)[\s_\-]*([0-9٠-٩]+)",
    re.IGNORECASE
)


class _HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "p", "div", "br", "hr", "li", "tr",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "section", "article", "header", "footer"
    }
    IGNORE_TAGS = {"head", "script", "style", "svg", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self.IGNORE_TAGS:
            self.ignore_depth += 1
        elif self.ignore_depth == 0 and t in self.BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.IGNORE_TAGS and self.ignore_depth > 0:
            self.ignore_depth -= 1
        elif self.ignore_depth == 0 and t in self.BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self.ignore_depth == 0:
            self.chunks.append(data)

    def get_text(self):
        raw = "".join(self.chunks)
        raw = raw.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.strip() for ln in raw.split("\n")]
        cleaned = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _decode_bytes(raw_bytes):
    for enc in ("utf-8-sig", "utf-8", "cp1256", "cp1252"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def compute_file_hash(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def extract_epub_text(epub_path):
    def local_name(tag):
        return tag.split("}", 1)[-1].lower()

    with zipfile.ZipFile(epub_path, "r") as zf:
        zip_names = zf.namelist()
        zip_lower = {n.lower(): n for n in zip_names}

        opf_path = None
        if "meta-inf/container.xml" in zip_lower:
            c_root = ET.fromstring(zf.read(zip_lower["meta-inf/container.xml"]))
            for elem in c_root.iter():
                if local_name(elem.tag) == "rootfile":
                    opf_path = elem.attrib.get("full-path")
                    if opf_path:
                        break
        if not opf_path:
            for n in zip_names:
                if n.lower().endswith(".opf"):
                    opf_path = n
                    break
        if not opf_path:
            raise ValueError("ملف EPUB لا يحتوي على فهرس OPF صالح.")

        actual_opf = opf_path if opf_path in zip_names else zip_lower.get(opf_path.lower())
        opf_dir = posixpath.dirname(actual_opf)
        opf_root = ET.fromstring(zf.read(actual_opf))

        manifest = {}
        spine_ids = []
        for elem in opf_root.iter():
            tag = local_name(elem.tag)
            if tag == "item":
                iid = elem.attrib.get("id")
                href = elem.attrib.get("href", "")
                mtype = elem.attrib.get("media-type", "")
                if iid and href:
                    manifest[iid] = (href, mtype)
            elif tag == "itemref":
                idref = elem.attrib.get("idref")
                if idref:
                    spine_ids.append(idref)

        ordered_files = []
        for idref in spine_ids:
            if idref not in manifest:
                continue
            href, mtype = manifest[idref]
            href = unquote(href.split("#", 1)[0]).replace("\\", "/")
            if mtype and not any(x in mtype.lower() for x in ("html", "xml")):
                continue
            joined = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else posixpath.normpath(href)
            actual = joined if joined in zip_names else zip_lower.get(joined.lower())
            if actual and actual not in ordered_files:
                ordered_files.append(actual)

        parts = []
        for path in ordered_files:
            html_str = _decode_bytes(zf.read(path))
            parser = _HTMLTextExtractor()
            parser.feed(html_str)
            parser.close()
            txt = parser.get_text()
            if txt:
                parts.append(txt)
        return "\n\n".join(parts)


def extract_pdf_text(pdf_path):
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        pages = []
        for page in doc:
            t = page.get_text("text")
            if t and t.strip():
                pages.append(t.strip())
        doc.close()
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(pages)).strip()
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                pages.append(t.strip())
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(pages)).strip()


def extract_docx_text(docx_path):
    from docx import Document
    doc = Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n\n".join(paras)


def extract_txt_text(txt_path):
    with open(txt_path, "rb") as f:
        raw = f.read()
    text = _decode_bytes(raw).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_clean_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".epub":
        return extract_epub_text(file_path)
    if ext == ".pdf":
        return extract_pdf_text(file_path)
    if ext == ".docx":
        return extract_docx_text(file_path)
    if ext == ".txt":
        return extract_txt_text(file_path)
    raise ValueError(f"صيغة غير مدعومة: {ext}")


def parse_filename_metadata(file_path):
    base = os.path.splitext(os.path.basename(file_path))[0].strip()
    m = SERIES_HINT_RE.match(base)
    if m:
        series = m.group("series").strip(" _-.")
        try:
            vol_num = int(m.group(2))
        except ValueError:
            vol_num = 0
        return base, series, vol_num
    return base, "", 0


def compute_text_stats(text):
    words = len(text.split())
    chars = len(text)
    chapters = len(CHAPTER_HEADING_RE.findall(text))
    return words, chars, chapters


def build_scout_sample(text, total_sample_words=4500):
    words = text.split()
    n = len(words)
    if n <= total_sample_words:
        return text
    head_len = int(total_sample_words * 0.40)
    mid_len = int(total_sample_words * 0.30)
    tail_len = total_sample_words - head_len - mid_len

    head = " ".join(words[:head_len])
    mid_start = max(head_len, (n // 2) - (mid_len // 2))
    mid = " ".join(words[mid_start:mid_start + mid_len])
    tail = " ".join(words[-tail_len:])
    return f"[مقطع البداية]\n{head}\n\n[مقطع الوسط]\n{mid}\n\n[مقطع النهاية]\n{tail}"


def split_text_into_chunks(text, max_words_per_chunk=45000):
    total_words = len(text.split())
    if total_words <= max_words_per_chunk:
        return [text]

    # نحاول التقطيع عند حدود الفصول أولاً
    sections = [s.strip() for s in CHAPTER_HEADING_RE.split(text) if s.strip()]
    if len(sections) <= 1:
        sections = [p.strip() for p in text.split("\n\n") if p.strip()]

    # إذا كان أي مقطع لا يزال أكبر من الحد، نفككه إلى فقرات
    normalized_blocks = []
    for sec in sections:
        if len(sec.split()) > max_words_per_chunk:
            paras = [p.strip() for p in sec.split("\n\n") if p.strip()]
            normalized_blocks.extend(paras)
        else:
            normalized_blocks.append(sec)

    chunks = []
    current = []
    current_words = 0
    for blk in normalized_blocks:
        wc = len(blk.split())
        if current and (current_words + wc > max_words_per_chunk):
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(blk)
        current_words += wc

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def scan_inbox_files(inbox_dirs):
    discovered = []
    for root_dir in inbox_dirs:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        for current_root, _, files in os.walk(root_dir):
            for fname in sorted(files):
                if fname.startswith(".") or fname.startswith("~$"):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTS:
                    discovered.append(os.path.join(current_root, fname))
    return discovered


def safe_unique_dest(dest_dir, filename):
    os.makedirs(dest_dir, exist_ok=True)
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def execute_post_complete_cleanup(novel, paths, action, confirm_permanent_delete=False):
    orig_path = novel.get("original_path", "")
    cached_path = novel.get("cached_text_path", "")
    archive_created = ""

    if action == "archive_compressed":
        # نضغط النص الصافي في أرشيف zip خفيف جداً ثم نحذف الأصل الضخم
        if cached_path and os.path.exists(cached_path):
            safe_base = re.sub(r'[\\/*?:"<>|]', "_", os.path.splitext(novel["file_name"])[0])
            zip_name = f"{safe_base}_id{novel['id']}.txt.zip"
            zip_path = os.path.join(paths["archive"], zip_name)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.write(cached_path, arcname=f"{safe_base}.txt")
            # التحقق الفعلي من سلامة الأرشيف قبل لمس الأصل
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad_member = zf.testzip()
                if bad_member is not None:
                    raise IOError(f"فشل التحقق من سلامة الأرشيف المضغوط: {bad_member}")
            archive_created = zip_path
            if orig_path and os.path.exists(orig_path):
                os.remove(orig_path)
            if os.path.exists(cached_path):
                os.remove(cached_path)
        return archive_created

    if action == "move_to_trash":
        if orig_path and os.path.exists(orig_path):
            dest = safe_unique_dest(paths["trash"], os.path.basename(orig_path))
            shutil.move(orig_path, dest)
            archive_created = dest
        if cached_path and os.path.exists(cached_path):
            os.remove(cached_path)
        return archive_created

    if action == "permanent_delete":
        if not confirm_permanent_delete:
            raise PermissionError("الحذف النهائي غير مفعّل بتأكيد الأمان (confirm_permanent_delete=False).")
        if orig_path and os.path.exists(orig_path):
            os.remove(orig_path)
        if cached_path and os.path.exists(cached_path):
            os.remove(cached_path)
        return "DELETED"

    # الوضع الافتراضي الآمن: "keep" (نقل الأصل لمجلد المكتملين)
    if orig_path and os.path.exists(orig_path):
        dest = safe_unique_dest(paths["completed"], os.path.basename(orig_path))
        shutil.move(orig_path, dest)
        archive_created = dest
    return archive_created