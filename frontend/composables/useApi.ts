// composables/useApi.js
export const useApi = () => {
    const base = import.meta.env.NUXT_PUBLIC_API_BASE;

    const get = async (url) => {
        const res = await fetch(`${base}${url}`);
        return res.json();
    };

    return { get };
};