export interface Submission {
    id: string
    requestId: string
    providerName: string
    dataType: string
    coverage: number
    price: number
    message?: string
    status: 'pending' | 'accepted' | 'rejected'
}