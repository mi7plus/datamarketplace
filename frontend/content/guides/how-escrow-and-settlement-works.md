---
title: How escrow & settlement works
description: Funded → held → accept → release. You only pay for matching records, and you verify before any money moves.
order: 2
audience: all
---

Rowbound is a money product, so settlement is built like one: the buyer's budget is proven up front, and the supplier is protected against delivering for free.

## The lifecycle

1. **Funded** — when you open a request you fund `price × quantity` into escrow. The money is **held**, not paid.
2. **Submitted & validated** — suppliers submit data; every row is validated against your schema and unique key at ingest.
3. **Accepted** — you accept a submission. Allocation caps it at your remaining demand and excludes any record already accepted (dedup).
4. **Acceptance window** — the submission sits in `ACCEPTED` while escrow stays **held**. You can download and inspect the **full file** and open a dispute before any release.
5. **Released** — you confirm (or the window elapses with no dispute) and escrow is **released** to the supplier, per accepted record.
6. **Refunded** — anything you didn't accept is refunded.

## Why this is safe for both sides

- **Buyers** never pay on faith — you verify the real file during the window, and you only pay for records that pass validation.
- **Suppliers** never deliver into a void — the budget is escrowed before they lift a finger, and release is automatic if the buyer goes quiet.

Every released record carries its **source, license and (where personal) consent basis** in a manifest that travels with the download.
