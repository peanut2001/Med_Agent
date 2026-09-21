import io
import os
import base64
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any

import requests
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

# Figures are filtered on their rendered size on the page, not their pixel
# size: thumbnails, author headshots and journal logos are often embedded at
# high resolution but drawn tiny, so pixel size does not separate them.
MIN_PICTURE_POINTS = float(os.getenv("DOC_PARSER_MIN_PICTURE_POINTS", "150"))


class ParsedDocument:
    """
    Minimal stand-in for the docling document object.

    Only exposes what the downstream pipeline actually consumes:
    ``export_to_markdown``. Pages are kept separately so that the chunker can
    fall back to page boundaries.
    """

    def __init__(self, pages: List[str], page_image_counts: List[int] = None):
        self.pages = pages
        # How many extracted figures belong to each page. The remote parser
        # returns a flat text stream with no figure coordinates, so a page's
        # placeholders are appended at the end of that page's text — the
        # summaries land on the right page, just not at the exact paragraph.
        self.page_image_counts = page_image_counts or [0] * len(pages)

    def export_to_markdown(
        self,
        page_break_placeholder: str = "",
        image_placeholder: str = "",
    ) -> str:
        """
        Join per-page text into a single document.

        When ``image_placeholder`` is given, one placeholder per extracted
        figure is appended to its page, in extraction order. The downstream
        content processor swaps each placeholder for the figure's summary.
        """
        separator = f"\n{page_break_placeholder}\n" if page_break_placeholder else "\n\n"
        if not image_placeholder:
            return separator.join(self.pages)

        rendered = []
        for page_text, image_count in zip(self.pages, self.page_image_counts):
            if image_count:
                page_text = page_text + "\n\n" + "\n".join([image_placeholder] * image_count)
            rendered.append(page_text)
        return separator.join(rendered)


class MedicalDocParser:
    """
    Parses medical research documents by rendering each page and sending it to a
    remote document-parsing model (OpenAI-compatible endpoint).
    """

    def __init__(self, config=None):
        self.logger = logging.getLogger(__name__)

        # Fall back to env vars so the parser stays usable standalone.
        if config is not None:
            self.model_name = config.rag.doc_parser_model
            self.api_base = config.rag.doc_parser_api_base.rstrip("/")
            self.api_key = config.rag.doc_parser_api_key
            self.timeout = config.rag.doc_parser_timeout
            self.max_tokens = config.rag.doc_parser_max_tokens
        else:
            self.model_name = os.getenv("DOC_PARSER_MODEL_NAME", "mineru2.5-pro-2605-1.2b")
            self.api_base = (os.getenv("DOC_PARSER_API_BASE") or os.getenv("EMBEDDING_API_BASE", "")).rstrip("/")
            self.api_key = os.getenv("DOC_PARSER_API_KEY") or os.getenv("EMBEDDING_API_KEY", "")
            self.timeout = int(os.getenv("DOC_PARSER_TIMEOUT", "180"))
            self.max_tokens = int(os.getenv("DOC_PARSER_MAX_TOKENS", "4096"))

        self.endpoint = f"{self.api_base}/chat/completions"
        self.logger.info(f"Medical Document Parser initialized! (remote model: {self.model_name})")

    def _parse_page_image(self, png_bytes: bytes) -> str:
        """Send one rendered page to the remote parser and return its text."""
        b64 = base64.b64encode(png_bytes).decode()
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                            {"type": "text", "text": "Document Parsing:"},
                        ],
                    }
                ],
                # The model's context window is 8192 total, so the output cap
                # must leave room for the image tokens.
                "max_tokens": self.max_tokens,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _extract_page_pictures(
        self, page, doc_filename: str, output_dir_path: Path, start_index: int
    ) -> List[str]:
        """Save a page's embedded figures and return their data URLs.

        Files are named ``<doc>-picture-<n>.png`` because that is the name the
        reranker builds when it turns a ``picture_counter_<n>`` marker back
        into a reference link.
        """
        data_urls: List[str] = []
        index = start_index
        for obj in page.get_objects():
            if obj.type != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                continue
            try:
                left, bottom, right, top = obj.get_pos()
            except Exception as exc:
                self.logger.warning(f"   Skipped an image with no position: {exc}")
                continue
            if min(abs(right - left), abs(top - bottom)) < MIN_PICTURE_POINTS:
                continue
            try:
                pil_image = obj.get_bitmap().to_pil()
            except Exception as exc:
                self.logger.warning(f"   Skipped an unreadable embedded image: {exc}")
                continue
            if pil_image.mode not in ("RGB", "L"):
                pil_image = pil_image.convert("RGB")

            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            png_bytes = buffer.getvalue()
            (output_dir_path / f"{doc_filename}-picture-{index}.png").write_bytes(png_bytes)
            data_urls.append(
                "data:image/png;base64," + base64.b64encode(png_bytes).decode()
            )
            index += 1
        return data_urls

    def parse_document(
            self,
            document_path: str,
            output_dir: str,
            image_resolution_scale: float = 2.0,
            do_ocr: bool = True,
            do_tables: bool = True,
            do_formulas: bool = True,
            do_picture_desc: bool = False
        ) -> Tuple[Any, List[str]]:
        """
        Render each page and parse it with the remote model.

        Args:
            document_path: Path to the document to parse
            output_dir: Directory to save rendered page images
            image_resolution_scale: Resolution scale for rendered pages
            do_ocr, do_tables, do_formulas, do_picture_desc: kept for API
                compatibility with the previous local pipeline; the remote model
                handles all of these internally and they are ignored.

        Returns:
            Tuple containing (parsed_document, list_of_image_data_urls). The
            figures are embedded bitmaps extracted from the PDF itself, since
            the remote parser returns text only with no figure coordinates.
        """
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        doc_filename = Path(document_path).stem
        pdf = pdfium.PdfDocument(document_path)
        total_pages = len(pdf)
        self.logger.info(f"   Rendering and parsing {total_pages} pages via {self.model_name}")

        pages: List[str] = []
        failed_pages: List[int] = []
        page_image_counts: List[int] = []
        image_data_urls: List[str] = []

        for page_index in range(total_pages):
            page_no = page_index + 1
            page = pdf[page_index]

            # Extract this page's figures before parsing its text, so the
            # placeholder count matches what gets appended to the page.
            page_pictures = self._extract_page_pictures(
                page, doc_filename, output_dir_path, len(image_data_urls)
            )
            image_data_urls.extend(page_pictures)
            page_image_counts.append(len(page_pictures))

            pil_image = page.render(scale=image_resolution_scale).to_pil()

            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            png_bytes = buffer.getvalue()

            # Keep the page image on disk, mirroring the previous behaviour.
            page_image_filename = output_dir_path / f"{doc_filename}-{page_no}.png"
            with page_image_filename.open("wb") as fp:
                fp.write(png_bytes)

            try:
                pages.append(self._parse_page_image(png_bytes))
            except Exception as e:
                # One bad page should not lose the rest of the document.
                self.logger.error(f"   Failed to parse page {page_no}/{total_pages}: {e}")
                failed_pages.append(page_no)
                pages.append("")

            if page_no % 10 == 0 or page_no == total_pages:
                self.logger.info(f"   Parsed {page_no}/{total_pages} pages")

        if failed_pages:
            self.logger.warning(f"   {len(failed_pages)} page(s) failed to parse: {failed_pages}")

        self.logger.info(f"   Extracted {len(image_data_urls)} figures")
        return ParsedDocument(pages, page_image_counts), image_data_urls
