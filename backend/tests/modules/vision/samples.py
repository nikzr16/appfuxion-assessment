"""Invoice PDFs and images with tables, built in code (no binaries in the repo).

Text PDFs are drawn with reportlab at known positions so table rows and block boxes are
predictable; "scanned" invoices are Pillow images with no text layer.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 50.0
# Column x positions (left edges) and the right edge of the table.
COLUMNS = (50.0, 290.0, 350.0, 450.0)
TABLE_RIGHT = 545.0
ROW_HEIGHT = 22.0

HEADER = ("Description", "Qty", "Unit Price", "Amount")
MALAY_HEADER = ("Perkara", "Kuantiti", "Harga Seunit", "Jumlah")


@dataclass(frozen=True)
class Item:
    description: str
    quantity: str
    unit_price: str
    amount: str


ITEMS = (
    Item("Widget A", "2", "100.00", "200.00"),
    Item("Installation service", "1", "350.00", "350.00"),
    Item("Cable 5m", "10", "12.50", "125.00"),
)


@dataclass
class InvoiceSpec:
    items: Sequence[Item] = ITEMS
    header: Sequence[str] = HEADER
    ruled: bool = True
    # Rows per page; the table continues on the next page with the header repeated.
    rows_per_page: int | None = None
    # Index of a row whose description cell spans the whole row (a section heading).
    section_row: tuple[int, str] | None = None
    # Item index whose description wraps onto a second line inside the cell.
    wrapped: dict[int, str] = field(default_factory=dict)
    subtotal: str = "675.00"
    tax: str = "54.00"
    total: str = "729.00"
    total_label: str = "Total (RM)"


def _draw_header(pdf: canvas.Canvas) -> None:
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(LEFT, 790, "Acme Trading Sdn Bhd")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(LEFT, 774, "12 Jalan Ampang, 50450 Kuala Lumpur")
    pdf.drawString(LEFT, 760, "SST No: W10-1808-32000123")
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(380, 790, "INVOICE")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(380, 774, "Invoice No: INV-2026-001")
    pdf.drawString(380, 760, "Date: 15/10/2026")
    pdf.drawString(380, 746, "Due Date: 14/11/2026")

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(LEFT, 700, "Bill To:")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(LEFT, 686, "Kedai Maju Enterprise")
    pdf.drawString(LEFT, 672, "8 Jalan Tun Razak, 50400 Kuala Lumpur")


def _row_cells(item: Item) -> tuple[str, str, str, str]:
    return (item.description, item.quantity, item.unit_price, item.amount)


def _draw_table(
    pdf: canvas.Canvas,
    top: float,
    header: Sequence[str],
    rows: Sequence[tuple[str, ...] | str],
    *,
    ruled: bool,
    wrapped: dict[int, str],
    first_index: int,
) -> float:
    """Draw header + rows from ``top`` down; returns the y of the table's bottom edge."""
    y = top
    lines = [y]
    pdf.setFont("Helvetica-Bold", 10)
    for x, text in zip(COLUMNS, header, strict=True):
        pdf.drawString(x + 4, y - 15, text)
    y -= ROW_HEIGHT
    lines.append(y)
    pdf.setFont("Helvetica", 10)
    for offset, row in enumerate(rows):
        index = first_index + offset
        extra = wrapped.get(index)
        height = ROW_HEIGHT * (2 if extra else 1)
        if isinstance(row, str):  # a section heading spanning the row
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(COLUMNS[0] + 4, y - 15, row)
            pdf.setFont("Helvetica", 10)
        else:
            for x, text in zip(COLUMNS, row, strict=True):
                pdf.drawString(x + 4, y - 15, text)
            if extra:
                pdf.drawString(COLUMNS[0] + 4, y - 15 - 12, extra)
        y -= height
        lines.append(y)
    if ruled:
        pdf.setLineWidth(0.6)
        for line_y in lines:
            pdf.line(COLUMNS[0], line_y, TABLE_RIGHT, line_y)
        # Vertical lines; a section row has no inner vertical lines (a merged cell).
        row_tops = lines[:-1]
        row_bottoms = lines[1:]
        for x in (*COLUMNS, TABLE_RIGHT):
            for row_number, (row_top, row_bottom) in enumerate(
                zip(row_tops, row_bottoms, strict=True)
            ):
                spanning = row_number > 0 and isinstance(rows[row_number - 1], str)
                if spanning and x not in (COLUMNS[0], TABLE_RIGHT):
                    continue
                pdf.line(x, row_top, x, row_bottom)
    return y


def _draw_totals(pdf: canvas.Canvas, top: float, spec: InvoiceSpec) -> float:
    y = top - 24
    pdf.setFont("Helvetica", 10)
    for label, value in (("Subtotal", spec.subtotal), ("SST 8%", spec.tax)):
        pdf.drawString(350, y, label)
        pdf.drawRightString(TABLE_RIGHT, y, value)
        y -= 16
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(350, y, spec.total_label)
    pdf.drawRightString(TABLE_RIGHT, y, spec.total)
    return y


def _draw_payment(pdf: canvas.Canvas) -> None:
    pdf.setFont("Helvetica", 9)
    pdf.drawString(LEFT, 120, "Payment Terms: Net 30")
    pdf.drawString(LEFT, 107, "Bank: Maybank 5140 1234 5678")


def invoice_pdf(spec: InvoiceSpec | None = None) -> bytes:
    """A text PDF invoice: header, bill-to, a line-item table, totals and payment details."""
    spec = spec or InvoiceSpec()
    rows: list[tuple[str, ...] | str] = [_row_cells(item) for item in spec.items]
    if spec.section_row is not None:
        position, title = spec.section_row
        rows.insert(position, title)
    per_page = spec.rows_per_page or len(rows)
    chunks = [rows[start : start + per_page] for start in range(0, len(rows), per_page)]

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    first = 0
    bottom = 0.0
    for number, chunk in enumerate(chunks):
        if number == 0:
            _draw_header(pdf)
            top = 640.0
        else:
            top = 800.0
        bottom = _draw_table(
            pdf,
            top,
            spec.header,
            chunk,
            ruled=spec.ruled,
            wrapped=spec.wrapped,
            first_index=first,
        )
        first += len(chunk)
        if number < len(chunks) - 1:
            pdf.showPage()
    _draw_totals(pdf, bottom, spec)
    _draw_payment(pdf)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def long_invoice_spec(count: int = 60) -> InvoiceSpec:
    """Many items over several pages; the table continues with its header repeated."""
    items = [
        Item(
            f"Spare part {n:04d} model X{n % 7}",
            "1",
            f"{n}.00",
            f"{n}.00",
        )
        for n in range(1, count + 1)
    ]
    total = f"{sum(range(1, count + 1))}.00"
    return InvoiceSpec(items=items, rows_per_page=25, subtotal=total, tax="0.00", total=total)


# -- Scanned-style images --------------------------------------------------------------

SCAN_LINES = (
    "Acme Trading Sdn Bhd",
    "Invoice No: INV-2026-001",
    "Description | Qty | Unit Price | Amount",
    "Widget A | 2 | 100.00 | 200.00",
    "Total (RM) 200.00",
)


def scanned_invoice_image(width: int = 800, height: int = 1000) -> Image.Image:
    """White page with invoice lines drawn as pixels (no text layer)."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    y = 40
    for line in SCAN_LINES:
        draw.text((40, y), line, fill="black", font=font)
        y += 50
    return image


def scanned_png() -> bytes:
    buffer = io.BytesIO()
    scanned_invoice_image().save(buffer, format="PNG")
    return buffer.getvalue()


def scanned_pdf(pages: int = 1) -> bytes:
    images = [scanned_invoice_image() for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()
