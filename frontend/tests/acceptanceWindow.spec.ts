import { describe, it, expect } from 'vitest'
import { windowRemaining } from '../utils/acceptanceWindow'

const NOW = new Date('2026-06-01T12:00:00Z').getTime()

describe('windowRemaining', () => {
    it('returns null with no confirm_by', () => {
        expect(windowRemaining(null, NOW)).toBeNull()
        expect(windowRemaining(undefined, NOW)).toBeNull()
    })

    it('formats hours + minutes ahead', () => {
        const t = new Date(NOW + (2 * 3600 + 30 * 60) * 1000).toISOString()
        expect(windowRemaining(t, NOW)).toBe('2h 30m left to confirm or dispute')
    })

    it('formats minutes only when under an hour', () => {
        const t = new Date(NOW + 15 * 60 * 1000).toISOString()
        expect(windowRemaining(t, NOW)).toBe('15m left to confirm or dispute')
    })

    it('reports elapsed when past', () => {
        const t = new Date(NOW - 60 * 1000).toISOString()
        expect(windowRemaining(t, NOW)).toBe('window elapsed — auto-release pending')
    })

    it('returns null on an unparseable date', () => {
        expect(windowRemaining('not-a-date', NOW)).toBeNull()
    })
})
