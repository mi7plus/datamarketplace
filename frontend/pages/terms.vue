<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper class="max-w-3xl mx-auto px-6 py-12">
    <p class="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-6">
      <strong>Draft — for legal review.</strong> This document describes the platform's intended
      operating model. It is not authoritative legal text and must be reviewed by qualified legal
      counsel before the platform accepts real payments.
    </p>

    <h1 class="text-3xl font-bold mb-2">Terms of Service</h1>
    <p class="text-gray-400 text-sm mb-8">Last updated: June 2026 (placeholder)</p>

    <div class="prose prose-gray max-w-none space-y-6 text-sm text-gray-700">

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">1. Platform role</h2>
        <p>
          This platform acts as an intermediary marketplace — a <strong>data processor</strong>
          facilitating transactions between data requesters (buyers) and data providers (sellers).
          It does not itself collect, own, or sell data. Each dataset transaction is a bilateral
          agreement between the requester and provider; the platform provides the infrastructure
          and payment escrow.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">2. Provider obligations</h2>
        <p>By submitting a dataset, providers warrant that they:</p>
        <ul class="list-disc list-inside space-y-1 ml-2">
          <li>Have the legal right to sell or share the data.</li>
          <li>Are not violating any contract, copyright, or intellectual-property restriction.</li>
          <li>Have ensured the data contains no unconsented personal data, or that any personal
              data has been properly anonymised or pseudonymised in compliance with applicable law
              including the EU General Data Protection Regulation (GDPR).</li>
        </ul>
        <p class="mt-2">
          These warranties are affirmed at submission time and stored with the record. False
          warranties may result in account termination and legal liability.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">3. Requester obligations</h2>
        <p>
          Requesters may only use delivered datasets in accordance with the license attached to
          each request. Redistribution, resale, or use outside the stated license terms is
          prohibited without written consent from the provider.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">4. Payment & escrow</h2>
        <p>
          Budget is held in escrow on request funding and released to the provider only after
          the requester accepts a submission. Unspent escrow is refunded on request expiry or
          closure. Payments are processed via Stripe; the platform does not store card or bank
          details.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">5. Takedowns</h2>
        <p>
          The platform may remove any dataset alleged to infringe intellectual property rights
          or contain unlawfully processed personal data, and will revoke any outstanding download
          access. The underlying file is preserved for a minimum of 90 days to support legal
          proceedings before deletion.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">6. Disputes</h2>
        <p>
          Buyers may open a dispute within the acceptance window. Disputes are reviewed manually
          by platform admins. Resolution (payment release or refund) is final. The platform is
          not liable for losses arising from data quality beyond the remedies provided by the
          dispute process.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">7. Governing law</h2>
        <p>
          These terms are governed by the laws of Romania / the European Union. Disputes that
          cannot be resolved through the platform's dispute process shall be subject to the
          exclusive jurisdiction of the courts of [city], Romania.
          <span class="text-amber-600">[Legal review required — confirm jurisdiction.]</span>
        </p>
      </section>

    </div>
  </PageWrapper>
</template>
