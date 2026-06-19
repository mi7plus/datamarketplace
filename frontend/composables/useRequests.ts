import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/useApi'

export interface SpecColumn {
    name: string
    type: 'string' | 'integer' | 'float' | 'boolean' | 'date' | 'datetime'
    required: boolean
}

export interface RequestSpec {
    columns: SpecColumn[]
    unique_key?: string[]
}

export interface DataRequest {
    id: string
    title: string
    description?: string
    unit?: string
    amount_required?: number
    pricing_mode: string
    price_per_unit?: number
    budget?: number
    required_format?: string
    spec?: RequestSpec
    deadline?: string
    status: string
    accepted_total?: number
    requester_id?: string
}

export const useRequests = () => {
    const requests = ref<DataRequest[]>([])
    const loading = ref(false)
    const error = ref<string | null>(null)
    const api = useApi()

    const fetchRequests = async () => {
        loading.value = true
        error.value = null
        try {
            requests.value = await api.get('/requests/')
        } catch (e: any) {
            error.value = e.message
        } finally {
            loading.value = false
        }
    }

    const fetchRequest = async (id: string): Promise<DataRequest | null> => {
        try {
            return await api.get(`/requests/${id}`)
        } catch (e: any) {
            error.value = e.message
            return null
        }
    }

    onMounted(fetchRequests)

    return { requests, loading, error, fetchRequests, fetchRequest }
}
