# Final dependency-security pass

The last hosted CI log reported **15 affected packages: one critical, 12 high, one moderate and one low**. These counts are package-chain findings, not 15 independently proven application exploits. A successful build was not a security pass.

Upgraded the existing dashboard from Next.js/eslint-config-next **16.2.6 to 16.4.0**, refreshed compatible transitive dependencies without a force downgrade, and added a hosted high/critical runtime advisory gate.

Current audit evidence: **zero runtime findings** (`npm audit --omit=dev`) and **five high development-only chain findings**, all rooted in the unpatched braces advisory. Full and runtime outputs are in `docs/test-evidence/dashboard-security-*-audit.json`. No vulnerable development chain was hidden by deleting lint rules or pretending an unsupported override was a patch.

GHSA-vfj7-8cjw-p6xm lists no patched braces version. Keep lint/build inputs trusted and build tooling isolated; do not allow external users to supply glob patterns to it. The affected development chain remains a tracked partial finding, REI-182. This is not an assertion that a public dashboard request can reach the lint parser.

References:

- [Official Next.js September security update](https://nextjs.org/blog/nextjs-security-update-september-22-2026)
- [Official Next.js 16.4.0 release](https://github.com/vercel/next.js/releases/tag/v16.4.0)
- [Reviewed braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
- [Announced October 14 upstream security update](https://nextjs.org/blog/upcoming-nextjs-security-update-october-2026)

The announced future update has not yet published affected ranges or final upgrade instructions; review and apply the released fix when available. Zero current registry findings does not mean future-proof or vulnerability-free.

Nothing deployed. The separate Karpathys/The-Dashboard repository is not modified by this dependency pass.
