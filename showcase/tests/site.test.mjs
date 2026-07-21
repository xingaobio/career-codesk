import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const html = await readFile(resolve(root, "public", "index.html"), "utf8");

test("the public walkthrough is plainly simulated and human-readable", () => {
  assert.match(html, /100% simulated learner records/i);
  assert.match(html, /All profiles are fictional composites/i);
  assert.match(html, /Olivia K\./);
  assert.match(html, /Muhammad R\./);
  assert.doesNotMatch(html, /no MIS connection/i);
  assert.doesNotMatch(html, /UUID/i);
  assert.doesNotMatch(html, /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
});

test("the reviewer journey and evidence sources are present", () => {
  for (const label of ["Triage", "Evidence review", "Capacity plan", "Human decision", "Learner feedback"]) {
    assert.match(html, new RegExp(label, "i"));
  }
  assert.match(html, /www\.aoc\.co\.uk\/about\/college-key-facts/);
  assert.match(html, /gov\.uk\/government\/publications\/navigating-post-16-careers-guidance/);
});

test("the generated worker serves the walkthrough without a backend", async () => {
  const worker = (await import("../dist/server/index.js")).default;
  const response = await worker.fetch(new Request("https://example.test/"), {});
  assert.equal(response.status, 200);
  const rendered = await response.text();
  assert.match(rendered, /Career CoDesk/);
  assert.match(rendered, /https:\/\/example\.test\/og\.png/);
  const health = await worker.fetch(new Request("https://example.test/health"), {});
  assert.deepEqual(await health.json(), { status: "ok", mode: "simulated-reviewer-walkthrough" });
});
