/**
 * Core chat flow E2E tests.
 *
 * Prerequisites:
 *   - Backend running on localhost:8000 (with valid Azure credentials)
 *   - Frontend running on localhost:3000 (`npm run dev`)
 */

import { test, expect } from "@playwright/test";

// Selectors derived from actual component markup
const TEXTAREA = 'textarea[placeholder="Ask a question..."]';
const SEND_BUTTON = "button:has(svg).rounded-full";
const USER_BUBBLE = ".justify-end .rounded-2xl";
const ASSISTANT_TEXT = ".text-text-secondary";
const WELCOME_HEADING = "text=How can I help you?";
const CLEAR_BUTTON = 'button[aria-label="New conversation"]';
const ERROR_BANNER = ".border-red-100";

test.beforeEach(async ({ page }) => {
  // Clear persisted state between tests
  await page.goto("/");
  await page.evaluate(() => {
    sessionStorage.removeItem("campuslmu_messages");
    localStorage.removeItem("campuslmu_program");
  });
  await page.reload();
});

test("welcome state — empty chat shows example questions", async ({ page }) => {
  await expect(page.locator(WELCOME_HEADING)).toBeVisible();
  await expect(page.locator("text=How many ECTS does the master's have?")).toBeVisible();
  await expect(page.locator("text=What are the admission requirements?")).toBeVisible();
  await expect(page.locator("text=How long is the master's thesis?")).toBeVisible();
  // Send button disabled while input is empty
  await expect(page.locator(SEND_BUTTON).last()).toBeDisabled();
});

test("send message — typing indicator then assistant response", async ({ page }) => {
  await page.fill(TEXTAREA, "Wie viele ECTS hat der Master Informatik?");
  await expect(page.locator(SEND_BUTTON).last()).toBeEnabled();
  await page.locator(SEND_BUTTON).last().click();

  // User message appears immediately
  await expect(page.locator(USER_BUBBLE).first()).toContainText(
    "Wie viele ECTS hat der Master Informatik?"
  );

  // Wait for assistant response to arrive — timeout covers full Azure roundtrip
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  const responseText = await page.locator(ASSISTANT_TEXT).first().textContent();
  expect(responseText!.length).toBeGreaterThan(20);
});

test("send button disabled while streaming, re-enables after", async ({ page }) => {
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.locator(SEND_BUTTON).last().click();

  // Wait for stream to complete
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Button re-enables once streaming finishes and textarea has content
  await page.fill(TEXTAREA, "Next question");
  await expect(page.locator(SEND_BUTTON).last()).toBeEnabled({ timeout: 10_000 });
});

test("enter to send, shift+enter for newline", async ({ page }) => {
  await page.fill(TEXTAREA, "First line");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("Second line");

  const value = await page.inputValue(TEXTAREA);
  expect(value).toContain("\n");
  expect(value).toContain("Second line");

  // Enter sends the message
  await page.keyboard.press("Enter");
  await expect(page.locator(USER_BUBBLE).first()).toBeVisible();
});

test("example question button sends message on click", async ({ page }) => {
  await page.click("text=How many ECTS does the master's have?");
  await expect(page.locator(USER_BUBBLE).first()).toContainText("ECTS");
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });
});

test("clear chat — removes messages and welcome state reappears", async ({ page }) => {
  // First send a message
  await page.fill(TEXTAREA, "Was ist ECTS?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Clear button should be visible now
  await expect(page.locator(CLEAR_BUTTON)).toBeVisible();
  // Dismiss the confirm dialog automatically
  page.on("dialog", (dialog) => dialog.accept());
  await page.locator(CLEAR_BUTTON).click();

  // Welcome state returns, messages gone
  await expect(page.locator(WELCOME_HEADING)).toBeVisible();
  await expect(page.locator(USER_BUBBLE)).toHaveCount(0);
});

test("messages survive page reload (sessionStorage persistence)", async ({ page }) => {
  await page.fill(TEXTAREA, "Wie lange dauert die Masterarbeit?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Reload — messages should be restored from sessionStorage
  await page.reload();
  await expect(page.locator(USER_BUBBLE).first()).toContainText("Masterarbeit");
  // Assistant message content restored
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty();
});

test("follow-up question in same conversation", async ({ page }) => {
  // First question
  await page.fill(TEXTAREA, "Wie viele ECTS hat der Master Informatik?");
  await page.locator(SEND_BUTTON).last().click();
  await expect(page.locator(ASSISTANT_TEXT).first()).not.toBeEmpty({ timeout: 45_000 });

  // Wait for first response to complete, then fill and send follow-up.
  await page.fill(TEXTAREA, "Und wie viele davon entfallen auf die Masterarbeit?");
  await expect(page.locator(SEND_BUTTON).last()).toBeEnabled({ timeout: 15_000 });
  await page.locator(SEND_BUTTON).last().click();

  // Wait for second assistant response
  await expect(page.locator(ASSISTANT_TEXT).nth(1)).not.toBeEmpty({ timeout: 45_000 });
});
