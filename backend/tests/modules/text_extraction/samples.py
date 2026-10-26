"""Byte samples for the text extraction tests, all built in code (no binaries in the repo).

Text PDFs come from reportlab; "scanned" PDFs and images are drawn with Pillow, so they
have no text layer and must go through the (fake) vision model.
"""

import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

INVOICE_LINES = (
    "INVOICE INV-001",
    "Acme Trading Sdn Bhd",
    "Widget A x 2 RM 100.00",
    "Service fee RM 23.45",
    "Total RM 123.45",
)
PASSWORD = "secret"


def _page_lines(page: int, pages: int) -> tuple[str, ...]:
    if pages == 1:
        return INVOICE_LINES
    return (f"{INVOICE_LINES[0]} page {page} of {pages}", *INVOICE_LINES[1:])


def text_pdf(pages: int = 1) -> bytes:
    """A PDF with a real text layer on every page."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for page in range(1, pages + 1):
        y = 780
        for line in _page_lines(page, pages):
            pdf.drawString(72, y, line)
            y -= 24
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def invoice_image(width: int = 800, height: int = 1000) -> Image.Image:
    """White page with the invoice lines drawn as pixels (no text layer)."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    y = 40
    for line in INVOICE_LINES:
        draw.text((40, y), line, fill="black", font=font)
        y += 50
    return image


def scanned_pdf(pages: int = 1) -> bytes:
    """An image-only PDF: no text layer, like a scan."""
    images = [invoice_image() for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def mixed_pdf() -> bytes:
    """Page 1 has a text layer; page 2 is only a picture."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 780, INVOICE_LINES[0] + " page 1 with a real text layer")
    pdf.showPage()
    pdf.drawImage(ImageReader(invoice_image()), 0, 0, width=595, height=700)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def encrypted_pdf() -> bytes:
    """A text PDF that needs a password to open."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, encrypt=PASSWORD)
    pdf.drawString(72, 780, INVOICE_LINES[0])
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def corrupt_pdf() -> bytes:
    return b"%PDF-1.4\n" + b"this is not a pdf body " * 20


def png_invoice(width: int = 800, height: int = 1000) -> bytes:
    buffer = io.BytesIO()
    invoice_image(width, height).save(buffer, format="PNG")
    return buffer.getvalue()


def transparent_png() -> bytes:
    """Black text on a fully transparent background (RGBA)."""
    image = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).text(
        (20, 20), "INVOICE", fill=(0, 0, 0, 255), font=ImageFont.load_default(size=40)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def jpg_invoice(
    width: int = 800, height: int = 1000, *, exif_orientation: int | None = None
) -> bytes:
    """A JPEG; ``exif_orientation`` (e.g. 6) adds the EXIF tag a phone camera would write."""
    buffer = io.BytesIO()
    exif = Image.Exif()
    if exif_orientation is not None:
        exif[0x0112] = exif_orientation
    invoice_image(width, height).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()
