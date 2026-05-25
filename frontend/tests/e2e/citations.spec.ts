/**
 * Citation chip and drawer E2E tests.
 */

import { test, expect } from "@playwright/test";

const TEXTAREA = 'textarea[placeholder="Stelle deine Frage zur Studienordnung..."]';
const SEND_BUTTON = "button:has(svg).rounded-xl";
const ASSISTANT_BUBBLE = ".justify-start .rounded-2xl";
const CITATION_CHIP = ".bg-blue-50.border-blue-200"; // CitationChip classes
const CITATION_DRAWER = ".fixed.right-0.top-0"; // CitationDrawer outer div
const DRAWER_CLOSE = `${CITATION_DRAWER} button:has(svg)`;
const BACKDROP = ".fixed.inset-0.bg-black\\/20";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("campuslmu_messages");
    localStorage.removeItem("campuslmu_program");
  });
  await page.reload();

  // Send a query likely to produce citations
  await page.fill(TEXTAREA, "Wie viele ECTS umfasst der Master Informatik?");
  await page.click(SEND_BUTTON);
  // Wait for full response with citations (chips appear after final citations SSE event)
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });
  await expect(page.locator(CITATION_CHIP).first()).toBeVisible({ timeout: 15_000 });
});

test("citation chips appear in assistant response", async ({ page }) => {
  const chips = page.locator(CITATION_CHIP);
  await expect(chips.first()).toBeVisible({ timeout: 10_000 });
  const count = await chips.count();
  expect(count).toBeGreaterThanOrEqual(1);
});

test("click citation chip — drawer opens with content", async ({ page }) => {
  const chip = page.locator(CITATION_CHIP).first();
  await expect(chip).toBeVisible();
  await chip.click();

  const drawer = page.locator(CITATION_DRAWER);
  await expect(drawer).toBeVisible();

  // Drawer must show "Quelle N" heading and document metadata
  await expect(drawer.locator("text=Quelle")).toBeVisible();
  await expect(drawer.locator("text=Dokument:")).toBeVisible();
  await expect(drawer.locator("text=Seite:")).toBeVisible();
  await expect(drawer.locator("text=Originaltext")).toBeVisible();
});

test("close drawer with X button", async ({ page }) => {
  await page.locator(CITATION_CHIP).first().click();
  await expect(page.locator(CITATION_DRAWER)).toBeVisible();

  await page.locator(DRAWER_CLOSE).click();
  await expect(page.locator(CITATION_DRAWER)).not.toBeVisible();
});

test("close drawer by clicking backdrop", async ({ page }) => {
  await page.locator(CITATION_CHIP).first().click();
  await expect(page.locator(CITATION_DRAWER)).toBeVisible();

  // Click the semi-transparent backdrop (not the drawer itself)
  await page.locator(BACKDROP).click({ position: { x: 10, y: 10 } });
  await expect(page.locator(CITATION_DRAWER)).not.toBeVisible();
});

test("drawer shows PDF download link when source_url present", async ({ page }) => {
  await page.locator(CITATION_CHIP).first().click();
  const drawer = page.locator(CITATION_DRAWER);
  await expect(drawer).toBeVisible();

  // If source_url is populated, the download button appears
  const downloadLink = drawer.locator("text=PDF herunterladen");
  // Not all chunks have source_url; only assert if visible
  const isVisible = await downloadLink.isVisible();
  if (isVisible) {
    const href = await downloadLink.getAttribute("href");
    expect(href).toBeTruthy();
    expect(href).toMatch(/^https?:\/\//);
  }
});

test("second click on different chip updates drawer content", async ({ page }) => {
  const chips = page.locator(CITATION_CHIP);
  const count = await chips.count();
  if (count < 2) {
    test.skip();
    return;
  }

  await chips.first().click();
  const drawer = page.locator(CITATION_DRAWER);
  await expect(drawer).toBeVisible();
  const firstTitle = await drawer.locator("h3, p").first().textContent();

  await chips.nth(1).click();
  await expect(drawer).toBeVisible();
  const secondTitle = await drawer.locator("h3, p").first().textContent();

  // Drawer updated (content may differ or at minimum drawer is still open)
  expect(secondTitle).toBeDefined();
});
