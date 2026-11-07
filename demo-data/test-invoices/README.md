# Sample invoices for trying "upload"

Both files are the same **fictional** invoice (Northbank Foodservice NB-7731, $407.75). Neither is in the
demo inbox, so uploading one sends it to the AI reader (needs `OPENROUTER_API_KEY`); the reading is then
cached by file hash.

| File | What it is |
|---|---|
| `test_invoice_northbank_NB-7731.png` | The clean document |
| `test_invoice_northbank_NB-7731_phone_photo.jpg` | **Synthetic** phone photo, generated from the PNG (tilt, keystone, uneven light, slight blur), to try a messier input |

A correct reading: chicken thigh 2 × $109.90 (+15% vs. the saved $95.60), pork shoulder $92.40 (+3%),
Thai basil $24.75 (+10%), fish sauce 3 × $14.00 (1 gal = 128 fl oz, unchanged), baguettes 2 × $14.40
(unchanged); lines add up to the printed $407.75.
