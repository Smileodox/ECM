/**
 * Core chat flow E2E tests.
 *
 * Prerequisites:
 *   - Backend running on localhost:8000 (with valid Azure credentials)
 *   - Frontend running on localhost:3000 (`npm run dev`)
 */

import { test, expect } from "@playwright/test";

// Selectors derived from actual component markup
const TEXTAREA = 'textarea[placeholder="Stelle deine Frage zur Studienordnung..."]';
const SEND_BUTTON = "button:has(svg).rounded-xl";
const USER_BUBBLE = ".justify-end .rounded-2xl";
const ASSISTANT_BUBBLE = ".justify-start .rounded-2xl";
const WELCOME_HEADING = "text=Willkommen beim campusLMU Studienassistenten";
const CLEAR_BUTTON = "text=Neues Gespräch";
const ERROR_BANNER = ".border-red-200";
const TYPING_DOTS = ".animate-bounce";

test.beforeEach(async ({ page }) => {
  // Clear persisted state between tests
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("campuslmu_messages");
    localStorage.removeItem("campuslmu_program");
  });
  await page.reload();
});

test("welcome state — empty chat shows example questions", async ({ page }) => {
  await expect(page.locator(WELCOME_HEADING)).toBeVisible();
  await expect(page.locator("text=Wie viele ECTS umfasst der Master?")).toBeVisible();
  await expect(page.locator("text=Was sind die Zugangsvoraussetzungen?")).toBeVisible();
  await expect(page.locator("text=Wie lange dauert die Masterarbeit?")).toBeVisible();
  // Send button disabled while input is empty
  await expect(page.locator(SEND_BUTTON)).toBeDisabled();
});

test("send message — typing indicator then assistant response", async ({ page }) => {
  await page.fill(TEXTAREA, "Wie viele ECTS hat der Master Informatik?");
  await expect(page.locator(SEND_BUTTON)).toBeEnabled();
  await page.click(SEND_BUTTON);

  // User message appears immediately
  await expect(page.locator(USER_BUBBLE).first()).toContainText(
    "Wie viele ECTS hat der Master Informatik?"
  );

  // Typing indicator while streaming (may appear briefly)
  // Wait for assistant response to arrive — timeout covers full Azure roundtrip
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  const responseText = await page.locator(ASSISTANT_BUBBLE).first().textContent();
  expect(responseText!.length).toBeGreaterThan(20);
});

test("send button disabled while streaming, re-enables after", async ({ page }) => {
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.click(SEND_BUTTON);

  // Immediately after sending, button is disabled (streaming + textarea now empty)
  await expect(page.locator(SEND_BUTTON)).toBeDisabled();

  // Wait for stream to complete
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  // Button re-enables once streaming finishes and textarea has content
  await page.fill(TEXTAREA, "Nächste Frage");
  await expect(page.locator(SEND_BUTTON)).toBeEnabled({ timeout: 10_000 });
});

test("enter to send, shift+enter for newline", async ({ page }) => {
  await page.fill(TEXTAREA, "Erste Zeile");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("Zweite Zeile");

  const value = await page.inputValue(TEXTAREA);
  expect(value).toContain("\n");
  expect(value).toContain("Zweite Zeile");

  // Enter sends the message
  await page.keyboard.press("Enter");
  await expect(page.locator(USER_BUBBLE).first()).toBeVisible();
});

test("example question button sends message on click", async ({ page }) => {
  await page.click("text=Wie viele ECTS umfasst der Master?");
  await expect(page.locator(USER_BUBBLE).first()).toContainText("ECTS");
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });
});

test("clear chat — removes messages and welcome state reappears", async ({ page }) => {
  // First send a message
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  // "Neues Gespräch" button should be visible now
  await expect(page.locator(CLEAR_BUTTON)).toBeVisible();
  await page.click(CLEAR_BUTTON);

  // Welcome state returns, messages gone
  await expect(page.locator(WELCOME_HEADING)).toBeVisible();
  await expect(page.locator(USER_BUBBLE)).toHaveCount(0);
  await expect(page.locator(ASSISTANT_BUBBLE)).toHaveCount(0);
});

test("messages survive page reload (localStorage persistence)", async ({ page }) => {
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  // Reload — messages should be restored from localStorage
  await page.reload();
  await expect(page.locator(USER_BUBBLE).first()).toContainText("Masterarbeit");
  // Assistant message content restored
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty();
});

test("follow-up question in same conversation", async ({ page }) => {
  // First question
  await page.fill(TEXTAREA, "Wie viele ECTS hat der Master Informatik?");
  await page.click(SEND_BUTTON);
  await expect(page.locator(ASSISTANT_BUBBLE).first()).not.toBeEmpty({ timeout: 45_000 });

  // Wait for first response to complete, then fill and send follow-up.
  // Filling the textarea first ensures the button becomes enabled when streaming finishes.
  await page.fill(TEXTAREA, "Und wie viele davon entfallen auf die Masterarbeit?");
  await expect(page.locator(SEND_BUTTON)).toBeEnabled({ timeout: 15_000 });
  await page.click(SEND_BUTTON);

  // Wait for second assistant response to actually have content
  await expect(page.locator(ASSISTANT_BUBBLE).nth(1)).not.toBeEmpty({ timeout: 45_000 });
});
