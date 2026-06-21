// Pure formatter for the acceptance-window countdown shown on a submission.
// Given an ISO `confirm_by`, returns a human string or null when there's none.

export function windowRemaining(confirmBy?: string | null, now: number = Date.now()): string | null {
    if (!confirmBy) return null
    const ms = new Date(confirmBy).getTime() - now
    if (Number.isNaN(ms)) return null
    if (ms <= 0) return 'window elapsed — auto-release pending'
    const h = Math.floor(ms / 3.6e6)
    const m = Math.floor((ms % 3.6e6) / 6e4)
    return (h > 0 ? `${h}h ${m}m` : `${m}m`) + ' left to confirm or dispute'
}
