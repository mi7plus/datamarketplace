import { describe, it, expect } from 'vitest'
import { statusTone, statusLabel, STATUS_TONES, DEFAULT_TONE } from '../utils/statusTone'

describe('statusTone', () => {
    it('maps every known status to a non-default tone', () => {
        for (const key of Object.keys(STATUS_TONES)) {
            expect(statusTone(key)).toBe(STATUS_TONES[key])
        }
    })

    it('is case-insensitive', () => {
        expect(statusTone('PAID')).toBe(statusTone('paid'))
        expect(statusTone('Partially_Fulfilled')).toBe(STATUS_TONES.partially_fulfilled)
    })

    it('falls back to the default tone for unknown / empty', () => {
        expect(statusTone('nonsense')).toBe(DEFAULT_TONE)
        expect(statusTone(null)).toBe(DEFAULT_TONE)
        expect(statusTone(undefined)).toBe(DEFAULT_TONE)
    })

    it('uses calm amber for disputes/takedown (non-alarming)', () => {
        expect(statusTone('disputed')).toContain('amber')
        expect(statusTone('taken_down')).toContain('amber')
        expect(statusTone('quarantined')).toContain('amber')
    })

    it('uses accent for settlement states', () => {
        for (const s of ['paid', 'released', 'completed', 'accepted']) {
            expect(statusTone(s)).toContain('accent')
        }
    })
})

describe('statusLabel', () => {
    it('humanizes snake_case', () => {
        expect(statusLabel('partially_accepted')).toBe('partially accepted')
        expect(statusLabel(null)).toBe('')
    })
})
