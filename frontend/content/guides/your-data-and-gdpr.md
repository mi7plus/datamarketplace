---
title: Your data & GDPR
description: How Rowbound handles personal data — consent capture, PII screening, takedown, and the controller/processor split.
order: 5
audience: all
---

> This guide explains how the platform is designed to handle personal data. It is not legal advice — for your obligations, consult qualified counsel.

## Roles

For account and transaction data, Rowbound acts as a **data controller**. For datasets that move between suppliers and buyers, the platform acts as a **processor** on behalf of the supplier, who is the controller of that data.

## Controls built in

- **PII screening at ingest** — uploads are scanned for emails, phone numbers, national IDs and payment cards. High-risk datasets are **quarantined** for review before they can be delivered.
- **Consent & lawful basis for collected data** — field collection captures a consent basis and lawful basis **per record**, retained for audit.
- **Takedown & revocation** — an admin (or a reporter) can flag a dataset; it's made unreachable and outstanding download links are revoked.
- **Per-record provenance** — license and source travel with every delivered record.

## Supplier warranties

When you list or submit data you affirm you have the right to sell or share it and that it contains no unconsented personal data (or has been properly anonymised). These warranties are recorded with the submission.

See also: [Licensing & provenance](/guides/licensing-and-provenance).
