import io
import os
import base64
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any

import requests
import pypdfium2 as pdfium


class ParsedDocument:
    """
    Minimal stand-in for the docling document object.

    Only exposes what the downstream pipeline actually consumes:
    ``export_to_markdown``. Pages are kept separately so that the chunker can
    fall back to page boundaries.
    """

    def __init__(self, pages: List[str]):
        self.pages = pages

    def export_to_markdown(
        self,
        page_break_placeholder: str = "",
        image_placeholder: str = "",
    ) -> str:
        """
        Join per-page text into a single document.

        ``image_placeholder`` is accepted for API compatibility but never
        emitted: the remote parser returns a flat text stream with no image
        positions, so there is nothing to anchor a placeholder to.
        """
        separator = f"\n{page_break_placeholder}\n" if page_break_placeholder else "\n\n"
        return separator.join(self.pages)


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
            Tuple containing (parsed_document, list_of_image_paths). The image
            list is always empty: the remote parser returns text only, with no
            figure coordinates to crop from.
        """
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        doc_filename = Path(document_path).stem
        pdf = pdfium.PdfDocument(document_path)
        total_pages = len(pdf)
        self.logger.info(f"   Rendering and parsing {total_pages} pages via {self.model_name}")

        pages: List[str] = []
        failed_pages: List[int] = []

        for page_index in range(total_pages):
            page_no = page_index + 1
            pil_image = pdf[page_index].render(scale=image_resolution_scale).to_pil()

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

        return ParsedDocument(pages), []
