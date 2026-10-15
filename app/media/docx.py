"""Bounded Word text extraction; never extract archive paths or execute document content."""

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAX_BYTES = 10 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024
MAX_PARTS = 200
MAX_CHARS = 24000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
STORY = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml")


class DocxReviewRequired(Exception):
    """Content-free review reason."""


class _NoDTD(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise DocxReviewRequired("Word document contains unsupported XML declarations")


def _xml(data: bytes) -> ET.Element:
    return ET.fromstring(data, parser=ET.XMLParser(target=_NoDTD()))


def extract(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES:
        raise DocxReviewRequired("Word document exceeds the 10 MB analysis limit")
    with zipfile.ZipFile(path) as archive:
        parts = archive.infolist()
        names = [p.filename for p in parts]
        if (
            len(parts) > MAX_PARTS
            or len(set(names)) != len(names)
            or sum(p.file_size for p in parts) > MAX_EXPANDED
            or any(p.flag_bits & 1 for p in parts)
        ):
            raise DocxReviewRequired(
                "Word archive is encrypted, ambiguous or exceeds analysis limits"
            )
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise DocxReviewRequired("Only PDF and DOCX documents are supported for text analysis")
        types = _xml(archive.read("[Content_Types].xml"))
        if not any(
            el.tag == CT + "Override"
            and el.get("PartName") == "/word/document.xml"
            and el.get("ContentType") == MAIN_TYPE
            for el in types
        ):
            raise DocxReviewRequired("Only PDF and DOCX documents are supported for text analysis")
        # Unknown parts, embedded objects and custom XML may contain unexamined content.
        metadata = {
            "[Content_Types].xml",
            "_rels/.rels",
            "docProps/core.xml",
            "docProps/app.xml",
            "word/styles.xml",
            "word/stylesWithEffects.xml",
            "word/settings.xml",
            "word/fontTable.xml",
            "word/webSettings.xml",
            "word/numbering.xml",
            "word/theme/theme1.xml",
        }
        incomplete = any(
            name not in metadata and not STORY.fullmatch(name) and not name.endswith(".rels")
            for name in names
            if not name.endswith("/")
        )
        texts: list[str] = []
        count = 0
        stories = 0
        for part in parts:
            name = part.filename
            if not STORY.fullmatch(name):
                continue
            root = _xml(archive.read(part))
            if name == "word/document.xml" and (
                root.tag != W + "document" or root.find(W + "body") is None
            ):
                raise DocxReviewRequired(
                    "Word document structure is unreadable; manual review required"
                )
            stories += 1
            for el in root.iter():
                if (el.text or "").strip() and el.tag not in {W + "t", W + "delText"}:
                    incomplete = True
                if (el.tail or "").strip():
                    incomplete = True
                if el.tag in {W + "t", W + "delText"}:
                    text = el.text or ""
                    texts.append(text)
                    count += len(text)
                    if "\ufffd" in text or "\x00" in text:
                        incomplete = True
                elif el.tag in {W + "p", W + "tab", W + "br", W + "cr"}:
                    texts.append("\n")
                    count += 1
                # Formatting is ignored; all non-Word content (e.g. DrawingML,
                # equations, VML, alternate content) and dynamic fields need review.
                if not el.tag.startswith(W) or el.tag in {
                    W + "drawing",
                    W + "pict",
                    W + "object",
                    W + "altChunk",
                    W + "fldSimple",
                    W + "fldChar",
                    W + "instrText",
                    W + "sym",
                    W + "numPr",
                    W + "subDoc",
                    W + "contentPart",
                }:
                    incomplete = True
                if count > MAX_CHARS:
                    raise DocxReviewRequired(
                        "Word document exceeds the 24000-character analysis limit"
                    )
        text = "".join(texts).strip()
        return {"text": text, "parts": stories, "complete": bool(text) and not incomplete}
