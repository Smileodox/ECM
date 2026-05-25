/**
 * Program filter and localStorage persistence E2E tests.
 */

import { test, expect } from "@playwright/test";

const TEXTAREA = 'textarea[placeholder="Stelle deine Frage zur Studienordnung..."]';
const SEND_BUTTON = "button:has(svg).rounded-xl";
const ASSISTANT_BUBBLE = ".justify-start .rounded-2xl";
const PROGRAM_SELECT = "select.border-gray-200";
const CLEAR_BUTTON = "text=Neues Gespräch";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("campuslmu_messages");
    localStorage.removeItem("campuslmu_program");
  });
  await page.reload();
});

test("program dropdown loads and shows options", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  // Programs load asynchronously; wait up to 10s
  await expect(select).toBeVisible({ timeout: 10_000 });

  const optionCount = await select.locator("option").count();
  expect(optionCount).toBeGreaterThan(10); // far more than 10 programs in the index

  // First option is "Alle Studiengänge"
  const firstOption = await select.locator("option").first().textContent();
  expect(firstOption).toContain("Alle Studiengänge");
});

test("selecting a program filters results", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });

  // Pick Informatik
  await select.selectOption({ label: "Informatik" });

  // Send a question — backend should receive program_name=Informatik
  await page.fill(TEXTAREA, "Wie viele ECTS hat der Master?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  // Response exists — we can't assert content without knowing the answer,
  // but the stream completed successfully with a program filter applied
  const responseText = await page.locator(ASSISTANT_BUBBLE).first().textContent();
  expect(responseText!.length).toBeGreaterThan(10);
});

test("selected program survives page reload", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });
  await select.selectOption({ label: "Informatik" });

  await page.reload();

  // After reload, select should show Informatik
  const selected = await page.locator(PROGRAM_SELECT).inputValue();
  expect(selected).toBe("Informatik");
});

test("resetting program to 'Alle Studiengänge' clears filter", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });
  await select.selectOption({ label: "Informatik" });

  // Reset
  await select.selectOption({ value: "" });

  await page.reload();
  const selected = await page.locator(PROGRAM_SELECT).inputValue();
  expect(selected).toBe("");
});

test("clear chat resets messages but keeps program selection", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });
  await select.selectOption({ label: "Informatik" });

  // Send a message to make clear button appear
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  await page.click(CLEAR_BUTTON);

  // Messages cleared, but program selection should remain
  await expect(page.locator(ASSISTANT_BUBBLE)).toHaveCount(0);
  const selectedAfterClear = await page.locator(PROGRAM_SELECT).inputValue();
  expect(selectedAfterClear).toBe("Informatik");
});

test("program selection persists through multiple conversations", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });
  await select.selectOption({ label: "Informatik" });

  // First conversation
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });
  // Fill next message to verify streaming done (button enables only when not streaming + textarea non-empty)
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await expect(page.locator(SEND_BUTTON)).toBeEnabled({ timeout: 10_000 });
  await page.fill(TEXTAREA, "");
  await page.click(CLEAR_BUTTON);

  // Program still selected after clear
  expect(await page.locator(PROGRAM_SELECT).inputValue()).toBe("Informatik");

  // Second conversation still uses Informatik
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  expect(await page.locator(PROGRAM_SELECT).inputValue()).toBe("Informatik");
});
