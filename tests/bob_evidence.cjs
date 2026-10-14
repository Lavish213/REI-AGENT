const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('../dashboard/node_modules/typescript');
const source = ts.transpileModule(fs.readFileSync('dashboard/lib/bob-evidence.ts', 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const scope = {exports: {}}; vm.runInNewContext(source, scope);
const view = scope.exports.bobEvidence, now = Date.now();
const brief = {schema_version: '2.0', lead_id: 'lead', ready_for_call: false, created_at: new Date(now-1000).toISOString(), expires_at: new Date(now+1000).toISOString(), evidence: {valuation: {lead_id: 'lead', status: 'ready_advisory', method: 'evidence_adjusted_sales_comparison', purpose: 'after_repair', quote_authorized: false, offer_authorized: false, as_of: new Date(now).toISOString().slice(0,10), supported_low_cents: 40000000, point_cents: 45000000, supported_high_cents: 50000000, comparable_count: 3}}};
assert.equal(view(brief, 'lead', now).pricing.point, 45000000);
assert.equal(view(brief, 'other', now), null);
assert.equal(view(brief, 'lead', now+2000), null);
for (const amount of [null, true, NaN, Infinity, -1, 1.2, 1e15]) {const bad=structuredClone(brief);bad.evidence.valuation.point_cents=amount;assert.equal(view(bad,'lead',now).pricing,null)}
const authorized=structuredClone(brief);authorized.evidence.valuation.quote_authorized=true;assert.equal(view(authorized,'lead',now).pricing,null);
console.log('11 Bob dashboard evidence assertions passed');
