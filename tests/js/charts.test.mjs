// The chart maths behind the Statistics report (dist/charts.js). The checks live in scripts/qa-charts.cjs, which has no dependencies and also
// runs on its own (`node scripts/qa-charts.cjs`); this test runs them with the rest of tests/js, so `pytest` covers them as well.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

test('the chart computation checks in scripts/qa-charts.cjs pass', () => {
  const output = execFileSync(process.execPath, [path.join(root, 'scripts', 'qa-charts.cjs')], { cwd: root, encoding: 'utf8' });
  const result = JSON.parse(output.trim().split('\n').at(-1));
  assert.ok(result.passed >= 10, output);
});
