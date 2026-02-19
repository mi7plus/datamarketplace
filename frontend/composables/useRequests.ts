export const useRequests = () => {
    const requests = [
        {
            id: '1',
            title: 'Street Images for Autonomous Driving',
            description: 'Urban street-level images captured during daytime.',
            budget: 5000,
            coverage: 60,
        },
        {
            id: '2',
            title: 'Customer Support Chat Logs',
            description: 'Anonymized chat transcripts in English.',
            budget: 2000,
            coverage: 30,
        },
        {
            id: '3',
            title: 'Retail Transaction Data',
            description: 'CSV data of POS transactions over 2 years.',
            budget: 3500,
            coverage: 100,
        },
    ]

    return { requests }
}