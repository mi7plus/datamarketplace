<script setup lang="ts">
import PageWrapper from '~/components/layout/PageWrapper.vue'
</script>

<template>
  <PageWrapper class="max-w-3xl mx-auto px-6 py-12">
    <p class="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-6">
      <strong>Draft — for legal review.</strong> This document describes the platform's intended
      data practices. It is not authoritative legal text and must be reviewed by qualified legal
      counsel and a certified DPO before public launch.
    </p>

    <h1 class="text-3xl font-bold mb-2">Privacy Policy</h1>
    <p class="text-gray-400 text-sm mb-8">Last updated: June 2026 (placeholder)</p>

    <div class="prose prose-gray max-w-none space-y-6 text-sm text-gray-700">

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">1. Controller &amp; processor roles</h2>
        <p>
          For account and transaction data, the platform acts as a <strong>data controller</strong>
          under GDPR (Regulation EU 2016/679). For datasets uploaded by providers and delivered
          to requesters, the platform acts as a <strong>data processor</strong> on behalf of the
          provider (who is the controller of that data).
        </p>
        <p class="mt-2 text-amber-600 text-xs">
          [Legal review required — confirm controller/processor split and whether a DPA between
          platform and providers is required.]
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">2. Data we collect</h2>
        <ul class="list-disc list-inside space-y-1 ml-2">
          <li><strong>Account data:</strong> email address, hashed password, role, Stripe Connect account ID.</li>
          <li><strong>Profile data:</strong> name or company name, phone, address (optional).</li>
          <li><strong>Transaction data:</strong> data requests, submissions, ledger entries, reviews.</li>
          <li><strong>Provider warranty records:</strong> timestamped affirmation stored with each submission.</li>
          <li><strong>Usage data:</strong> last login, activity timestamps.</li>
        </ul>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">3. Legal basis for processing</h2>
        <ul class="list-disc list-inside space-y-1 ml-2">
          <li><strong>Contract performance</strong> (Art. 6(1)(b)) — account registration, transaction execution.</li>
          <li><strong>Legitimate interests</strong> (Art. 6(1)(f)) — fraud prevention, platform integrity.</li>
          <li><strong>Legal obligation</strong> (Art. 6(1)(c)) — record-keeping for dispute resolution and tax.</li>
        </ul>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">4. Data retention</h2>
        <p>
          Account data is retained for the life of the account plus 3 years after deletion.
          Transaction records are retained for 7 years for legal and tax purposes.
          Taken-down dataset files are retained for 90 days before deletion.
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">5. Third-party processors</h2>
        <ul class="list-disc list-inside space-y-1 ml-2">
          <li><strong>Stripe</strong> — payment processing and provider payouts. Stripe's privacy policy applies to card and bank data.</li>
          <li><strong>MinIO / S3-compatible storage</strong> — encrypted file storage for uploaded datasets.</li>
        </ul>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">6. Your rights (GDPR)</h2>
        <p>EU residents have the right to: access, rectification, erasure ("right to be forgotten"),
        restriction, portability, and objection. To exercise these rights, contact
        <a href="mailto:privacy@example.com" class="text-blue-600 hover:underline">privacy@example.com</a>.
        <span class="text-amber-600">[Replace with real DPO contact.]</span>
        </p>
      </section>

      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-2">7. Cookies</h2>
        <p>
          The platform uses only functional cookies (session management). No tracking or
          advertising cookies are used.
        </p>
      </section>

    </div>
  </PageWrapper>
</template>
