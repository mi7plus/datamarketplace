// Single source of truth for status → pill classes (used by StatusPill).
// Pure + framework-free so it's unit-testable and reused consistently.
// Accent for active/settlement, ink for neutral structure, amber-but-calm for disputes.

export const STATUS_TONES: Record<string, string> = {
    // request states
    draft: 'bg-slate-100 text-slate-600',
    open: 'bg-ink/10 text-ink',
    partially_fulfilled: 'bg-accent/15 text-accent-deep',
    completed: 'bg-accent/20 text-accent-deep',
    fulfilled: 'bg-accent/20 text-accent-deep',
    review: 'bg-slate-100 text-slate-700',
    expired: 'bg-slate-200 text-slate-600',
    // submission states
    pending: 'bg-slate-100 text-slate-600',
    validated: 'bg-ink/10 text-ink',
    accepted: 'bg-accent/15 text-accent-deep',
    partially_accepted: 'bg-accent/15 text-accent-deep',
    paid: 'bg-accent/20 text-accent-deep',
    rejected: 'bg-slate-200 text-slate-600',
    rejected_invalid: 'bg-slate-200 text-slate-600',
    disputed: 'bg-amber-100 text-amber-800',
    // escrow / catalog
    held: 'bg-ink/10 text-ink',
    released: 'bg-accent/20 text-accent-deep',
    refunded: 'bg-slate-100 text-slate-600',
    sold_out: 'bg-slate-200 text-slate-600',
    taken_down: 'bg-amber-100 text-amber-800',
    quarantined: 'bg-amber-100 text-amber-800',
    catalog: 'bg-accent/15 text-accent-deep',
    collect: 'bg-accent/15 text-accent-deep',
    request: 'bg-ink/10 text-ink',
}

export const DEFAULT_TONE = 'bg-slate-100 text-slate-600'

export function statusTone(status?: string | null): string {
    return STATUS_TONES[(status ?? '').toLowerCase()] ?? DEFAULT_TONE
}

export function statusLabel(status?: string | null): string {
    return (status ?? '').replace(/_/g, ' ')
}
