/* Authenticated Chromium smoke against private staging. Credential file stays off Git. */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const AxeBuilder = require("@axe-core/playwright").default;
const assert = require("node:assert/strict");

(async () => {
  const credentials = JSON.parse(fs.readFileSync(process.env.QA_CREDENTIAL_FILE, "utf8"));
  const base = credentials.base_url;
  const output = process.env.BROWSER_ARTIFACT_ROOT || "verification/browser";
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", err => errors.push(err.message));
  async function login(email) {
    await page.goto(base);
    await page.getByLabel("Email address").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(credentials.password);
    await page.getByRole("button", { name: "Sign in to SomaLoom" }).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).waitFor();
  }
  await login(credentials.email);
  for (const section of ["library", "curriculum", "generate", "documents", "imports", "telegram", "question-bank", "schools"]) {
    await page.goto(base + "/" + section);
    await page.getByRole("heading", { level: 1 }).waitFor();
    assert(!await page.getByText("Application error:").count());
  }
  await page.goto(base + "/upload");
  const uploadResponse = page.waitForResponse(r => r.url().endsWith("/api/v1/resources/uploads") && r.request().method() === "POST");
  await page.getByLabel("Choose resources").setInputFiles([
    "verification/browser-fixtures/owned.pdf", "verification/browser-fixtures/owned.docx", "verification/browser-fixtures/owned.png"
  ]);
  await page.getByRole("button", { name: "Submit for processing" }).click();
  const uploaded = await uploadResponse;
  assert.equal(uploaded.status(), 201, await uploaded.text());
  const uploadItems = (await uploaded.json()).items;
  await page.goto(base + "/library");
  await page.getByText("owned.pdf", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, "library-desktop.png"), fullPage: true });
  const headers = { Origin: base };
  const imported = await page.request.post(base + "/api/v1/curricula/import", { headers, data: {
    name: "SYNTHETIC browser QA science", country: "Uganda", version: "qa-2026", level: "Primary", grade: "P5", subject: "Science",
    source_uri: "fixture://browser-owned-curriculum", source_license: "CC0-1.0",
    topics: [{ unit: "Water", title: "Filtration", outcomes: [{ code: "QA-WATER", description: "Describe filtration", origin: "enrichment", concepts: ["filtration"] }] }]
  }});
  assert.equal(imported.status(), 201, await imported.text());
  const cid = (await imported.json()).id;
  const topics = await (await page.request.get(base + `/api/v1/curricula/${cid}/topics`)).json();
  const tid = topics.items[0].id;
  const mapping = (await (await page.request.get(base + `/api/v1/topics/${tid}/outcomes`)).json()).items[0];
  assert.equal((await page.request.post(base + `/api/v1/topics/${tid}/mappings/${mapping.id}/review`, { headers, data: { status: "approved" } })).status(), 200);
  await page.goto(base + "/generate");
  await page.getByRole("combobox", { name: /^Curriculum/ }).selectOption(cid);
  await page.getByRole("combobox", { name: /^Class, subject and topic/ }).selectOption(tid);
  // A disabled real provider must return an honest error rather than fake output.
  const generation = page.waitForResponse(r => r.url().endsWith("/api/v1/generations") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Generate draft", exact: true }).click();
  assert.equal((await generation).status(), 503);
  await page.getByRole("alert").filter({ hasText: "provider not configured" }).waitFor();
  await page.goto(base + "/documents");
  await page.getByText("SYNTHETIC QA original teaching document", { exact: true }).click();
  await page.getByLabel("Edit paragraph").waitFor();
  await page.getByLabel("Edit paragraph").fill("Edited original CC0 QA content: filtration can trap particles, but pathogens may remain. Revision " + Date.now());
  await page.getByRole("button", { name: "Save new version", exact: true }).click();
  await page.getByText(/Saved as new version/).waitFor();
  const docId = new URL(page.url()).searchParams.get("document");
  assert(docId);
  const revisions = await (await page.request.get(base + `/api/v1/documents/${docId}/versions`)).json();
  const version = revisions.items[0].id;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(credentials.reviewer_email);
  await page.goto(base + `/review?document=${docId}&version=${version}`);
  await page.getByLabel("Review comments").fill("Synthetic browser QA reviewed for workflow verification only.");
  await page.getByLabel("Source evidence and citations verified").check();
  await page.getByLabel("Mathematics and marking calculations checked").check();
  await page.getByLabel("Visual labels and reproduction rights confirmed").check();
  const reviewed = page.waitForResponse(r => r.url().endsWith(`/versions/${version}/review`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Record version decision" }).click();
  assert.equal((await reviewed).status(), 201);
  await page.getByText(/Version review recorded: approved/).waitFor();
  for (const format of ["pdf", "docx"]) {
    await page.goto(base + "/publish?version=" + version);
    await page.getByRole("combobox", { name: /^File format/ }).selectOption(format);
    const published = page.waitForResponse(r => r.url().endsWith("/api/v1/exports") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Prepare export", exact: true }).click();
    assert.equal((await published).status(), 202);
    const link = page.getByRole("link", { name: "Download authenticated " + format.toUpperCase() });
    await link.waitFor({ timeout: 90000 });
    const downloadEvent = page.waitForEvent("download");
    await link.click();
    const download = await downloadEvent;
    const destination = path.join(output, "reviewed." + format);
    await download.saveAs(destination);
    assert(fs.statSync(destination).size > 1000);
  }
  await page.goto(base + "/editor?document=" + docId);
  await page.locator("math").waitFor();
  await page.screenshot({ path: path.join(output, "editor-desktop.png"), fullPage: true });
  const accessibility = await new AxeBuilder({ page }).analyze();
  const severe = accessibility.violations.filter(v => ["critical", "serious"].includes(v.impact));
  fs.writeFileSync(path.join(output, "accessibility.json"), JSON.stringify(accessibility.violations, null, 2));
  assert.deepEqual(severe.map(v => ({ id: v.id, impact: v.impact })), []);
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    await page.screenshot({ path: path.join(output, `editor-${width}.png`), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  }
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, "result.json"), JSON.stringify({ status: "passed", uploadItems, documentId: docId, versionId: version,
    realProvider: "blocked-unconfigured", viewportWidths: [1440, 390, 768], severeAccessibilityFindings: severe.length }, null, 2));
  await browser.close();
  console.log("PASS: private EC2 browser auth/upload/edit/review/PDF/DOCX, responsive and axe smoke. Real AI correctly unavailable.");
})().catch(err => { console.error(err.message); process.exit(1); });
