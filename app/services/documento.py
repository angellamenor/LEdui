"""
Exports a transformation to a native Word document (.docx).

The adapted task statement arrives as simple HTML (h1-h3, p, ol, ul, li, strong, em, br),
so it is converted with a small parser instead of embedding HTML.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from io import BytesIO

from docx import Document
from docx.shared import Cm, Pt, RGBColor

from app.i18n import language_name, nivel_label, t
from app.models import TransformacionEnunciado

PRIMARY = RGBColor(0x2B, 0x7A, 0x78)


class _HtmlToDocx(HTMLParser):
    """Convert the HTML subset produced by the model into python-docx paragraphs."""

    def __init__(self, document: Document, heading_offset: int = 1):
        super().__init__(convert_charrefs=True)
        self.doc = document
        self.offset = heading_offset
        self.paragraph = None
        self.bold = 0
        self.italic = 0
        self.lists: list[str] = []

    def _ensure_paragraph(self, style: str | None = None):
        if self.paragraph is None:
            self.paragraph = self.doc.add_paragraph(style=style)
        return self.paragraph

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            level = min(int(tag[1]) + self.offset, 9)
            self.paragraph = self.doc.add_heading(level=level)
        elif tag == "p":
            self.paragraph = self.doc.add_paragraph()
        elif tag in ("ol", "ul"):
            self.lists.append(tag)
        elif tag == "li":
            style = "List Number" if self.lists and self.lists[-1] == "ol" else "List Bullet"
            self.paragraph = self.doc.add_paragraph(style=style)
        elif tag in ("strong", "b"):
            self.bold += 1
        elif tag in ("em", "i"):
            self.italic += 1
        elif tag == "br" and self.paragraph is not None:
            self.paragraph.add_run().add_break()

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "p", "li"):
            self.paragraph = None
        elif tag in ("ol", "ul") and self.lists:
            self.lists.pop()
        elif tag in ("strong", "b"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("em", "i"):
            self.italic = max(0, self.italic - 1)

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data)
        if not text.strip() and self.paragraph is None:
            return
        run = self._ensure_paragraph().add_run(text)
        run.bold = self.bold > 0 or None
        run.italic = self.italic > 0 or None


def _markdown_bold_paragraphs(document: Document, text: str):
    """Paragraphs separated by blank lines, with markdown-style **bold**."""
    for block in re.split(r"\n\s*\n", text.strip()):
        p = document.add_paragraph()
        for i, piece in enumerate(re.split(r"\*\*(.+?)\*\*", block)):
            if piece:
                p.add_run(piece.replace("\n", " ")).bold = (i % 2 == 1) or None


def _add_image(document: Document, data: bytes | None):
    if data:
        document.add_picture(BytesIO(data), width=Cm(16))


def generar_docx(trans: TransformacionEnunciado) -> bytes:
    lang = trans.idioma or "es"
    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Cm(2)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    title = doc.add_heading(t("doc.titulo", lang), level=0)
    for run in title.runs:
        run.font.color.rgb = PRIMARY

    meta = [
        (t("doc.id", lang), f"#{trans.id}"),
        (t("doc.usuario", lang), trans.user.email if trans.user else "-"),
        (t("doc.nivel", lang), nivel_label(trans.nivel, lang)),
        (t("doc.idioma", lang), language_name(lang)),
        (t("doc.fecha", lang), trans.created_at.strftime("%d/%m/%Y %H:%M") if trans.created_at else "-"),
    ]
    for label, value in meta:
        p = doc.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        p.add_run(str(value))

    if trans.enunciado_adaptado:
        doc.add_heading(t("doc.enunciado_adaptado", lang), level=1)
        _HtmlToDocx(doc, heading_offset=1).feed(trans.enunciado_adaptado)

    if trans.indicaciones_docentes:
        doc.add_heading(t("doc.indicaciones", lang), level=1)
        _markdown_bold_paragraphs(doc, trans.indicaciones_docentes)

    if trans.pictogramas and trans.pictogramas.exito:
        doc.add_heading(t("doc.pictogramas", lang), level=1)
        _add_image(doc, trans.pictogramas.imagen_pictogramas)
        if trans.pictogramas.explicacion_habilidades:
            doc.add_heading(t("doc.explicacion_habilidades", lang), level=2)
            _markdown_bold_paragraphs(doc, trans.pictogramas.explicacion_habilidades)

    imagenes = [i for i in sorted(trans.imagenes_contexto or [], key=lambda x: x.orden or 0) if i.imagen_data]
    if imagenes:
        doc.add_heading(t("doc.imagenes_contexto", lang), level=1)
        for n, img in enumerate(imagenes, start=1):
            doc.add_heading(t("doc.imagen", lang, n=n), level=2)
            _add_image(doc, img.imagen_data)
            if img.texto_explicativo:
                p = doc.add_paragraph()
                p.add_run(t("doc.por_que_imagen", lang) + " ").bold = True
                p.add_run(img.texto_explicativo)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
