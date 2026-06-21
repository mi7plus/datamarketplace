---
title: How to write a good data request
description: Schema, unique key, quantity, license and budget — the five things that make a request fillable and fairly priced.
order: 1
audience: buyers
---

A good request tells suppliers exactly what "done" looks like and what you'll pay for it. Five fields do most of the work.

## 1. Schema

List the columns you need with a **type** for each (`string`, `integer`, `float`, `boolean`, `date`, `datetime`) and mark which are **required**. Suppliers validate every row against this at ingest — rows that don't conform aren't counted, so a precise schema raises quality and avoids disputes.

## 2. Unique key

Declare the column(s) that identify one record (e.g. `id`, or `address` for a property dataset). The unique key powers **deduplication**: no record is paid for twice, even when your request is filled from several suppliers or modes. Without a key, cross-source fulfilment is disabled.

## 3. Quantity

Set `amount_required` — your target number of records. Allocation is **capped at this number**: over-delivery is trimmed and you never pay for more than you asked for.

## 4. License

Attach the license the data must carry. It travels with every delivered record, so you have provenance for compliance from day one.

## 5. Budget & price per record

You fund `price_per_unit × amount_required` into **escrow** up front. Money is held, not spent — you pay only for matching records that you accept. Anything unspent is refunded.

> Tip: a tight schema + a real unique key is the single biggest lever on fill rate and price fairness.
