---
title: Partial fulfilment & cross-mode
description: One funded request, filled from many sources — catalog, collected, and commissioned — deduped into one clean dataset.
order: 6
audience: all
---

Most requests don't have a single supplier with exactly the right data. Rowbound is built so they don't need one.

## Partial fulfilment

A request can be filled by **multiple submissions over time**. Each is capped at the **remaining** demand and deduplicated against everything already accepted, so the request fills up record by record without ever exceeding your target or paying twice.

## Cross-mode fulfilment

The same request can draw from all three supply modes at once:

- **Existing catalog rows** — instant, cheapest; applied first.
- **Freshly collected rows** — field data gathered to order.
- **Commissioned rows** — requested submissions from competing suppliers.

Records from every source are **entity-resolved on your declared unique key** (normalized so trivial near-duplicates collapse), deduplicated against each other, capped at your target, and settled per accepted record — through **one escrow**.

## Why no incumbent does this

A catalog sells whole files. A managed vendor delivers one stream. Neither fills a single funded request from a **deduplicated blend** of all three supply modes. That allocation-plus-dedup logic is the part competitors can't copy by listing more datasets.

Start with [How to write a good data request](/guides/how-to-write-a-good-data-request) — a real unique key is what makes cross-mode possible.
