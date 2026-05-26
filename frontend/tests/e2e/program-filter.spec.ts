/**
 * Program filter and localStorage persistence E2E tests.
 */

import { test, expect } from "@playwright/test";

const TEXTAREA = 'textarea[placeholder="Ask a question..."]';
const SEND_BUTTON = "button:has(svg).rounded-full";
const ASSISTANT_TEXT = ".text-text-secondary";
const PROGRAM_SELECT = 'select[aria-label="Select program"]';
const CLEAR_BUTTON = 'button[aria-label="New conversation"]';

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    sessionStorage.removeItem("campuslmu_messages");
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

  // First option is "All programs"
  const firstOption = await select.locator("option").first().textContent();
  expect(firstOption).toContain("All programs");
});

test("selecting a program filters results", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });

  // Pick Informatik
  await select.selectOption({ label: "Informatik" });

  // Send a question — backend should receive program_name=Informatik
  await page.fill(TEXTAREA, "How many ECTS does the master's have?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Response exists — we can't assert content without knowing the answer,
  // but the stream completed successfully with a program filter applied
  const responseText = await page.locator(ASSISTANT_TEXT).first().textContent();
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

test("resetting program to 'All programs' clears filter", async ({ page }) => {
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
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Dismiss the confirm dialog automatically
  page.on("dialog", (dialog) => dialog.accept());
  await page.locator(CLEAR_BUTTON).click();

  // Messages cleared, but program selection should remain
  await expect(page.locator(ASSISTANT_TEXT)).toHaveCount(0);
  const selectedAfterClear = await page.locator(PROGRAM_SELECT).inputValue();
  expect(selectedAfterClear).toBe("Informatik");
});

test("program selection persists through multiple conversations", async ({ page }) => {
  const select = page.locator(PROGRAM_SELECT);
  await expect(select).toBeVisible({ timeout: 10_000 });
  await select.selectOption({ label: "Informatik" });

  // First conversation
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });
  // Fill next message to verify streaming done (button enables only when not streaming + textarea non-empty)
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await expect(page.locator(SEND_BUTTON).last()).toBeEnabled({ timeout: 10_000 });
  await page.fill(TEXTAREA, "");
  // Dismiss the confirm dialog automatically
  page.on("dialog", (dialog) => dialog.accept());
  await page.locator(CLEAR_BUTTON).click();

  // Program still selected after clear
  expect(await page.locator(PROGRAM_SELECT).inputValue()).toBe("Informatik");

  // Second conversation still uses Informatik
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  expect(await page.locator(PROGRAM_SELECT).inputValue()).toBe("Informatik");
});
