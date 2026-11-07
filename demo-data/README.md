# Night Shift demo data (all fictional)

Restaurant: **Pho Nightingale (fictional)**. Suppliers, prices and orders are invented for the demo.

## Files
| File | What it is |
|---|---|
| `settings.json` | Owner settings: DoorDash commission 25%, packaging $0.50/order, target delivery margin 38% |
| `ingredients.csv` | 15 ingredients: invoice alias, pack size, base unit, last pack price, yield % |
| `recipes.csv` | Quantity of each ingredient per serving, 5 dishes |
| `menu.csv` | In-store and DoorDash prices |
| `price_history.csv` | 4 prior weekly deliveries (all at last price) |
| `doordash_orders.csv` | 90 days of daily DoorDash orders per dish (weekend bump) for the volume forecast |
| `inbox/*.png` | Tonight's 3 supplier invoices (2026-11-06), the "new mail" Night Shift processes |
| `invoices_extracted_fallback.json` | Ground-truth extraction of those invoices; use if the vision API fails |
| `expected_results.json` | What the app must compute; use it to test |
| `make_demo_data.py` | Regenerates everything |

## Formula
`left per order = DoorDash price - DoorDash price x commission - packaging - ingredient cost`
`ingredient cost = sum(qty x pack_price / pack_size / yield)`. Labor and overhead excluded.

## The scenario the data produces
| Dish | What happens | Expected status |
|---|---|---|
| Brisket Pho | Brisket $119.80 -> $134.20 per 20 lb case (+12%). Cost/bowl $5.14 -> $5.51. Left/order $5.99 = 37.4% | **Below your target margin** (38%) |
| Chicken Pho | Bean sprouts +5% | Cost increased; no action needed |
| Banh Mi, Bun Cha | Nothing changed | OK |
| Spring Rolls | Invoice says "RICE PAPER 22CM 1 CS" with no pack count | **Needs review** (hold recommendation) |

**Proposal (Brisket Pho):** DoorDash price $15.99 -> $16.99. Left/order $5.99 -> $6.74 (39.7%), +$0.75/order after the 25% commission. Forecast 225 orders/month (last 28 days) -> about **+$169/month**.

## Sad paths to demo
1. **Unclear pack size:** "RICE PAPER 22CM 1 CS" has no pack count. Spring Rolls shows *Needs review*, the recommendation is withheld, the owner confirms the new case is "10 packs x 50 sheets" (500 sheets, a smaller case than before), the per-sheet cost recalculates to the same $0.076, and Spring Rolls returns to OK at $1.72 ingredient cost, and the correction is logged.
2. **Duplicate invoice:** `inbox/FWD_scan_rivermark_RM-20419.png` is the same invoice (same supplier + invoice number RM-20419) forwarded again. It must be detected and skipped, not counted twice; the log shows "Duplicate of RM-20419, skipped".
