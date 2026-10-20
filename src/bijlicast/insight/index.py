"""Document index for the Insight Agent: trusted documents -> page-anchored chunks ->
hybrid retrieval (BM25 keywords + multilingual sentence embeddings in FAISS).

* Citations are "DOC-ID p.N (section)" so anyone can open the PDF at that page.
* Table-heavy chunks (annex tables) are dropped: the agent never quotes numbers from PDFs;
  its numbers come from gold tables.
* The index is cached against each document's SHA-256 and rebuilt only when one changes
  (optimization log: a full PDF parse takes ~1.6 min with pypdf, 5.6 min with pdfplumber).
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

from .. import manifest as mf
from ..config import DOCS_DIR, INDEX_DIR, REPORTS_DIR, ROOT, sources

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_CHARS, OVERLAP = 1100, 150
MAX_DIGIT_RATIO = 0.25
HEADING = re.compile(r"^\s*((?:\d+\.){1,3}\d*|CHAPTER\s+\d+|Chapter\s+\d+)\s+([A-Z][A-Za-z ,&\-()/']{5,90})\s*$")

# Project documentation is indexed too (for "how was this computed?" questions), clearly labelled.
PROJECT_DOCS = [
    ("DOC-BC-PROBLEM", "BijliCast problem analysis", DOCS_DIR / "problem_analysis.md"),
    ("DOC-BC-BASELINE", "BijliCast baseline declaration", DOCS_DIR / "baseline_declaration.md"),
    ("DOC-BC-MODEL", "BijliCast model report", REPORTS_DIR / "model_report.md"),
]


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "td", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip() + " ")


def html_text(path: Path) -> str:
    p = _Text()
    p.feed(path.read_text(encoding="utf-8", errors="ignore"))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(p.parts).splitlines()]
    return "\n".join(ln for ln in lines if ln)


def pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader
    return [(pg.extract_text() or "") for pg in PdfReader(str(path)).pages]


def _windows(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        cut = max(text.rfind(". ", start + size // 2, end), text.rfind("\n", start + size // 2, end))
        end = cut + 1 if cut > 0 and end < len(text) else end
        out.append(text[start:end].strip())
        start = max(end - overlap, start + 1) if end < len(text) else len(text)
    return out


def _digit_ratio(s: str) -> float:
    chars = [c for c in s if not c.isspace()]
    return sum(c.isdigit() for c in chars) / max(len(chars), 1)


def _is_toc(s: str) -> bool:
    """Table-of-contents / list-of-tables pages: many lines ending in a page number or dot leaders."""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) < 4:
        return False
    hits = sum(bool(re.search(r"(\.{3,}|\s)\d{1,3}$", ln)) for ln in lines)
    return hits / len(lines) > 0.4


def _clean(s: str) -> str:
    return (s.replace("�", "'").replace("’", "'").replace("‘", "'")
            .replace("“", '"').replace("”", '"').replace("T able", "Table"))


def build_chunks() -> pd.DataFrame:
    entries = mf.load()
    docs = {d["id"]: d for d in sources().get("documents", [])}
    rows = []
    for doc_id, meta in docs.items():
        e = entries.get(doc_id)
        if e is None or not (ROOT / e.local_path).exists():
            continue
        path = ROOT / e.local_path
        is_pdf = meta["kind"] == "pdf"
        pages = pdf_pages(path) if is_pdf else [html_text(path)]
        section = ""
        for pno, text in enumerate(pages, start=1):
            text = _clean(text)
            if is_pdf and _is_toc(text):
                continue
            # every heading on the page with its character offset; a chunk takes the last heading before
            # its middle (pages often hold several sections)
            heads, pos = [], 0
            for line in text.splitlines(keepends=True):
                m = HEADING.match(line.strip())
                if m and _digit_ratio(line) < 0.2:
                    heads.append((pos, f"{m.group(1)} {m.group(2).strip()}"))
                pos += len(line)
            norm = re.sub(r"[ \t]+", " ", text)
            # web pages mix prose with fee tables: small windows, no digit filter
            for w in (_windows(text) if is_pdf else _windows(text, size=450, overlap=80)):
                start = norm.find(w[:60])
                mid = (start if start >= 0 else 0) + len(w) // 2
                before = [h for p, h in heads if p <= mid]
                section = before[-1] if before else section
                if len(w) < 120 or (is_pdf and _digit_ratio(w) > MAX_DIGIT_RATIO):
                    continue
                rows.append({"doc_id": doc_id, "title": meta["title"], "publisher": meta["publisher"],
                             "page": pno if meta["kind"] == "pdf" else None, "section": section,
                             "url": meta["url"], "text": w, "kind": "official", "doc_sha256": e.sha256})
    for doc_id, title, path in PROJECT_DOCS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for block in re.split(r"\n(?=#{1,3} )", text):
            head = block.splitlines()[0].lstrip("# ").strip() if block.strip() else ""
            for w in _windows(block):
                if len(w) >= 80:
                    rows.append({"doc_id": doc_id, "title": title, "publisher": "BijliCast team (this project)",
                                 "page": None, "section": head, "url": path.relative_to(ROOT).as_posix(),
                                 "text": w, "kind": "project", "doc_sha256": mf.sha256_file(path)})
    df = pd.DataFrame(rows)
    df.insert(0, "chunk_id", [f"{r.doc_id}#{i:04d}" for i, r in enumerate(df.itertuples())])
    return df


def _indexed_text(chunks: pd.DataFrame) -> list[str]:
    """What retrieval sees: section heading + chunk text (headings carry strong topical signal)."""
    return [(f"{s}. {t}" if s else t) for s, t in zip(chunks["section"].fillna(""), chunks["text"])]


def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL)


def build(force: bool = False) -> dict:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = INDEX_DIR / "meta.json"
    entries = mf.load()
    current = {d["id"]: entries[d["id"]].sha256 for d in sources().get("documents", []) if d["id"] in entries}
    current.update({d: mf.sha256_file(p) for d, _, p in PROJECT_DOCS if p.exists()})
    if not force and meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if old.get("doc_sha256") == current and (INDEX_DIR / "chunks.parquet").exists():
            return {"status": "cached", "chunks": old["n_chunks"]}
    t0 = time.time()
    chunks = build_chunks()
    t_parse = time.time() - t0
    emb_status = "none"
    try:
        import faiss
        model = _embedder()
        vec = model.encode(_indexed_text(chunks), batch_size=64, normalize_embeddings=True,
                           show_progress_bar=False).astype("float32")
        index = faiss.IndexFlatIP(vec.shape[1])
        index.add(vec)
        faiss.write_index(index, str(INDEX_DIR / "faiss.index"))
        emb_status = EMBED_MODEL
    except Exception as exc:  # offline or missing model: BM25-only retrieval still works
        emb_status = f"unavailable ({type(exc).__name__})"
    chunks.to_parquet(INDEX_DIR / "chunks.parquet", index=False)
    meta = {"doc_sha256": current, "n_chunks": int(len(chunks)), "embeddings": emb_status,
            "parse_s": round(t_parse, 1), "total_s": round(time.time() - t0, 1),
            "per_doc": chunks.groupby("doc_id").size().to_dict()}
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"status": "built", **meta}


_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


def tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(s) if len(t) > 1]


class Retriever:
    """Hybrid retriever: 0.5 x normalised BM25 + 0.5 x cosine similarity."""

    def __init__(self):
        from rank_bm25 import BM25Okapi
        self.chunks = pd.read_parquet(INDEX_DIR / "chunks.parquet")
        self.bm25 = BM25Okapi([tokenize(t) for t in _indexed_text(self.chunks)])
        self.index, self.model = None, None
        fp = INDEX_DIR / "faiss.index"
        if fp.exists():
            try:
                import faiss
                self.index = faiss.read_index(str(fp))
                self.model = _embedder()
            except Exception:
                self.index = None

    def search(self, query: str, k: int = 4, kinds=("official", "project"), doc_ids=None) -> pd.DataFrame:
        mask = self.chunks["kind"].isin(kinds).to_numpy().copy()
        if doc_ids:
            mask = mask & self.chunks["doc_id"].isin(doc_ids).to_numpy()
        bm = np.asarray(self.bm25.get_scores(tokenize(query)), dtype=float)
        bm_n = bm / bm.max() if bm.max() > 0 else bm
        dense = np.zeros(len(self.chunks))
        if self.index is not None:
            q = self.model.encode([query], normalize_embeddings=True).astype("float32")
            sims, ids = self.index.search(q, len(self.chunks))
            dense[ids[0]] = sims[0]
        score = 0.5 * bm_n + 0.5 * np.clip(dense, 0, None)
        score[~mask] = -1
        top = np.argsort(-score)[:k]
        res = self.chunks.iloc[top].copy()
        res["score"], res["dense"], res["bm25"] = score[top], dense[top], bm_n[top]
        return res[res["score"] > 0]


if __name__ == "__main__":
    print(json.dumps(build(force=True), indent=1))
