"""Builds the sample documents in this folder. Every company, address and number is made up.

Run from the repository root (reportlab is a backend dev dependency):

    uv run --project backend python samples/make_samples.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
BILL_TO = ("Bill To:", "Contoh Retail Sdn Bhd", "1 Jalan Contoh, 50000 Kuala Lumpur")
WIDTH, HEIGHT = A4


def _header(pdf, vendor, address, tax_line, info):
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(50, HEIGHT - 60, "INVOICE")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, HEIGHT - 90, vendor)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, HEIGHT - 105, address)
    if tax_line:
        pdf.drawString(50, HEIGHT - 120, tax_line)
    y = HEIGHT - 150
    for line in info:
        pdf.drawString(50, y, line)
        y -= 15
    y -= 10
    for i, line in enumerate(BILL_TO):
        pdf.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 10)
        pdf.drawString(50, y, line)
        y -= 15
    return y - 15


def _ruled_table(pdf, y, header, rows, currency):
    cols = (50, 300, 360, 460, 545)
    lines = [header, *[(d, str(q), f"{currency} {p}", f"{currency} {a}") for d, q, p, a in rows]]
    top = y + 14
    for i, row in enumerate(lines):
        pdf.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 10)
        pdf.drawString(cols[0] + 4, y, row[0])
        for x, cell in zip(cols[2:], row[1:], strict=True):
            pdf.drawRightString(x - 4, y, cell)
        y -= 20
    bottom = y + 14
    for row_y in [top - 20 * i for i in range(len(lines) + 1)]:
        pdf.line(cols[0], row_y, cols[-1], row_y)
    for x in cols:
        if x != 300:
            pdf.line(x, top, x, bottom)
    return y - 10


def _totals(pdf, y, totals, bold_last=True):
    for i, (label, value) in enumerate(totals):
        last = bold_last and i == len(totals) - 1
        pdf.setFont("Helvetica-Bold" if last else "Helvetica", 10)
        pdf.drawString(360, y, label)
        pdf.drawRightString(541, y, value)
        y -= 16
    return y


def lumen_invoice():
    """A clean MYR invoice with a ruled table: validation passes."""
    pdf = canvas.Canvas(str(OUT / "lumen-office-INV-2026-0418.pdf"), pagesize=A4)
    y = _header(
        pdf,
        "Lumen Office Supplies Sdn Bhd",
        "22 Jalan Industri 3, 47100 Puchong, Selangor",
        "SST Reg No: W10-2601-32000001",
        (
            "Invoice No: INV-2026-0418",
            "Invoice Date: 14 October 2026",
            "Due Date: 13 November 2026",
            "Terms: Net 30",
        ),
    )
    y = _ruled_table(
        pdf,
        y,
        ("Description", "Qty", "Unit Price", "Amount"),
        [
            ("A4 copier paper 80gsm (box of 5 reams)", 10, "92.00", "920.00"),
            ("Toner cartridge, black", 3, "310.50", "931.50"),
            ("Desk organiser set", 5, "48.90", "244.50"),
        ],
        "RM",
    )
    _totals(
        pdf, y, [("Subtotal", "RM 2,096.00"), ("SST 8%", "RM 167.68"), ("TOTAL", "RM 2,263.68")]
    )
    pdf.save()


def damai_unruled():
    """A Malay invoice with an unruled table and DD/MM/YYYY dates: tables found by code."""
    pdf = canvas.Canvas(str(OUT / "damai-perabot-unruled-malay.pdf"), pagesize=A4)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, HEIGHT - 60, "Syarikat Perabot Damai Sdn Bhd")
    pdf.drawRightString(545, HEIGHT - 60, "INVOIS")
    pdf.setFont("Helvetica", 10)
    left = ("8 Jalan Kenari 2, 81300 Skudai, Johor", "SST No: J31-2601-32000002")
    right = ("No. Invois: DPD-2026-0077", "Tarikh: 20/10/2026", "Tarikh Akhir: 19/11/2026")
    for i, line in enumerate(left):
        pdf.drawString(50, HEIGHT - 78 - 15 * i, line)
    for i, line in enumerate(right):
        pdf.drawRightString(545, HEIGHT - 78 - 15 * i, line)
    y = HEIGHT - 150
    for i, line in enumerate(("Kepada:", *BILL_TO[1:])):
        pdf.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 10)
        pdf.drawString(50, y, line)
        y -= 15
    y -= 20
    cols = (50, 360, 460, 545)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(cols[0], y, "Perkara")
    for x, title in zip(cols[1:], ("Kuantiti", "Harga Seunit", "Jumlah"), strict=True):
        pdf.drawRightString(x, y, title)
    pdf.setFont("Helvetica", 10)
    rows = [
        ("Kerusi pejabat", "4", "180.00", "720.00"),
        ("Meja tulis kayu", "2", "450.00", "900.00"),
        ("Penghantaran", "1", "120.00", "120.00"),
    ]
    for row in rows:
        y -= 20
        pdf.drawString(cols[0], y, row[0])
        for x, cell in zip(cols[1:], row[1:], strict=True):
            pdf.drawRightString(x, y, cell)
        if row[0] == "Penghantaran":
            y -= 14
            pdf.drawString(cols[0], y, "dan pemasangan")
    y -= 30
    _totals(pdf, y, [("Subtotal", "1,740.00"), ("SST 8%", "139.20"), ("Total (RM)", "1,879.20")])
    pdf.drawString(50, 120, "Terma Pembayaran: Net 30")
    pdf.save()


def harbourline_usd():
    """A USD invoice: the Validation Agent converts the total to BASE_CURRENCY (MYR)."""
    pdf = canvas.Canvas(str(OUT / "harbourline-cloud-USD-HC-2291.pdf"), pagesize=A4)
    y = _header(
        pdf,
        "Harbourline Cloud Pte Ltd",
        "71 Harbour Point Road, Singapore 098000",
        None,
        (
            "Invoice No: HC-2291",
            "Invoice Date: 01 October 2026",
            "Due Date: 31 October 2026",
            "Currency: USD",
        ),
    )
    y = _ruled_table(
        pdf,
        y,
        ("Description", "Qty", "Unit Price", "Amount"),
        [
            ("Managed database (October)", 1, "640.00", "640.00"),
            ("Object storage, 2 TB", 2, "45.00", "90.00"),
            ("Support plan", 1, "250.00", "250.00"),
        ],
        "USD",
    )
    _totals(pdf, y, [("Subtotal", "USD 980.00"), ("TOTAL", "USD 980.00")])
    pdf.save()


def brightpath_faulty():
    """Deliberately wrong: the total does not add up and the due date is before the invoice date."""
    pdf = canvas.Canvas(str(OUT / "brightpath-logistics-with-errors.pdf"), pagesize=A4)
    y = _header(
        pdf,
        "Brightpath Logistics Sdn Bhd",
        "5 Lebuh Pantai, 10300 George Town, Penang",
        "SST Reg No: P11-2601-32000003",
        (
            "Invoice No: BPL-55120",
            "Invoice Date: 22 October 2026",
            "Due Date: 22 September 2026",
            "Terms: Net 30",
        ),
    )
    y = _ruled_table(
        pdf,
        y,
        ("Description", "Qty", "Unit Price", "Amount"),
        [
            ("Express delivery KL - Penang", 3, "180.00", "540.00"),
            ("Pallet storage (per week)", 6, "75.00", "450.00"),
        ],
        "RM",
    )
    _totals(pdf, y, [("Subtotal", "RM 990.00"), ("SST 8%", "RM 79.20"), ("TOTAL", "RM 1,089.20")])
    pdf.save()


def kopi_receipt():
    """A receipt as a slightly tilted image (no text layer): read by the vision model."""
    image = Image.new("RGB", (620, 1000), "white")
    draw = ImageDraw.Draw(image)
    big, font = ImageFont.load_default(size=34), ImageFont.load_default(size=26)
    lines = [
        ("KOPI CONTOH CAFE", big, "c"),
        ("12 Jalan Bunga Raya, 75100 Melaka", font, "c"),
        ("SST No: M10-2601-32000004", font, "c"),
        ("", font, "l"),
        ("Receipt: R-104233", font, "l"),
        ("Date: 25/10/2026  14:32", font, "l"),
        ("--------------------------------", font, "l"),
        ("Kopi O x2", font, "RM 6.40"),
        ("Roti bakar x1", font, "RM 4.50"),
        ("Nasi lemak x1", font, "RM 8.90"),
        ("--------------------------------", font, "l"),
        ("Subtotal", font, "RM 19.80"),
        ("SST 6%", font, "RM 1.19"),
        ("TOTAL", big, "RM 20.99"),
        ("", font, "l"),
        ("Paid: Cash RM 50.00", font, "l"),
        ("Change: RM 29.01", font, "l"),
        ("", font, "l"),
        ("Terima kasih!", font, "c"),
    ]
    y = 50
    for text, f, align in lines:
        if align == "c":
            draw.text((310, y), text, fill="black", font=f, anchor="ma")
        else:
            draw.text((40, y), text, fill="black", font=f)
            if align != "l":
                draw.text((580, y), align, fill="black", font=f, anchor="ra")
        y += 48 if f is big else 40
    image.rotate(1.5, expand=True, fillcolor="white").save(OUT / "kopi-contoh-receipt.png")


if __name__ == "__main__":
    lumen_invoice()
    damai_unruled()
    harbourline_usd()
    brightpath_faulty()
    kopi_receipt()
    print("Samples written to", OUT)
