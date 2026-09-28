import { test, expect } from "@playwright/test";
import { installChromeStub } from "./chrome-stub";

test.describe("side panel dashboard (standalone smoke test)", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(installChromeStub);
  });

  test("renders the overview and lets the user open the job creation wizard", async ({ page }) => {
    await page.goto("/sidepanel/");
    await expect(page.getByText("AI Flow", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("No jobs yet. Create your first job to get started.")).toBeVisible();

    await page.getByRole("button", { name: "+ New job" }).first().click();
    await expect(page.getByRole("heading", { name: "New job" })).toBeVisible();
    await expect(page.getByLabel("Task name")).toBeVisible();
  });

  test("navigates between dashboard sections", async ({ page }) => {
    await page.goto("/sidepanel/");
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

    await page.getByRole("button", { name: "Providers" }).click();
    await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible();
    await expect(page.getByText("Mock Provider (simulation)")).toBeVisible();

    await page.getByRole("button", { name: "Security" }).click();
    await expect(page.getByText("What AI Flow never does")).toBeVisible();
  });
});
