"""Draws sample_invoice.png, a simple supplier invoice with the brisket increase.

Run directly (python make_invoice.py) or let app.py create it on first launch.
"""

from PIL import Image, ImageDraw, ImageFont

from data import SAMPLE_INVOICE

NAVY = (11, 31, 58)
AMBER = (242, 165, 65)
GRAY = (110, 110, 110)
LINE = (210, 210, 210)


def _font(size, bold=False):
    candidates = (["Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
                  else ["Arial.ttf", "DejaVuSans.ttf"])
    for name in candidates + ["/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_invoice(path="sample_invoice.png"):
    width, height = 1000, 820
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    # Header band
    d.rectangle([0, 0, width, 110], fill=NAVY)
    d.text((40, 28), SAMPLE_INVOICE["supplier"], font=_font(30, bold=True), fill="white")
    d.text((40, 70), "1420 Industrial Way, Oakland CA  ·  (510) 555-0142",
           font=_font(16), fill=(200, 210, 225))
    d.text((width - 210, 40), "INVOICE", font=_font(34, bold=True), fill=AMBER)

    # Invoice meta
    meta = _font(18)
    d.text((40, 135), "Bill to: Pho Real, 88 Grand Ave", font=meta, fill=NAVY)
    d.text((40, 162), f"Invoice #: {SAMPLE_INVOICE['invoice_no']}", font=meta, fill=NAVY)
    d.text((width - 300, 135), f"Date: {SAMPLE_INVOICE['date']}", font=meta, fill=NAVY)
    d.text((width - 300, 162), "Terms: Net 15", font=meta, fill=NAVY)

    # Table
    cols = [40, 520, 640, 720, 860]  # description, qty, unit, unit price, total
    y = 215
    head = _font(17, bold=True)
    for x, label in zip(cols, ["Description", "Qty", "Unit", "Unit price", "Amount"]):
        d.text((x, y), label, font=head, fill=NAVY)
    y += 32
    d.line([40, y, width - 40, y], fill=NAVY, width=2)

    row_font = _font(18)
    subtotal = 0
    for _key, desc, qty, unit, price in SAMPLE_INVOICE["lines"]:
        y += 14
        amount = qty * price
        subtotal += amount
        d.text((cols[0], y), desc, font=row_font, fill="black")
        d.text((cols[1], y), str(qty), font=row_font, fill="black")
        d.text((cols[2], y), unit, font=row_font, fill="black")
        d.text((cols[3], y), f"${price:,.2f}", font=row_font, fill="black")
        d.text((cols[4], y), f"${amount:,.2f}", font=row_font, fill="black")
        y += 34
        d.line([40, y, width - 40, y], fill=LINE, width=1)

    # Totals
    y += 25
    tax = 0.0  # wholesale food: no sales tax
    for label, value in [("Subtotal", subtotal), ("Tax", tax), ("Total due", subtotal + tax)]:
        bold = label == "Total due"
        d.text((cols[3] - 40, y), label, font=_font(19, bold=bold), fill=NAVY)
        d.text((cols[4], y), f"${value:,.2f}", font=_font(19, bold=bold), fill=NAVY)
        y += 32

    d.text((40, height - 60),
           "Note: brisket pricing updated effective this delivery due to market conditions.",
           font=_font(15), fill=GRAY)
    img.save(path)
    return path


if __name__ == "__main__":
    print("Wrote", make_invoice())
