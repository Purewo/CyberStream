// Isolated browser fallback: chrome-devtools MCP's profile is occupied.
// Android UI emulation below tests React branching, not the native bridge.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.argv[2]);
(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 412, height: 915 }, isMobile: true, deviceScaleFactor: 1 });
  await context.addInitScript(() => { window.androidBridge = {}; });
  const page = await context.newPage();
  const errors = [], failed = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if(response.status() >= 400) { const u = new URL(response.url()); failed.push({ status: response.status(), path: u.pathname }); } });
  page.on('requestfailed', request => { const u = new URL(request.url()); failed.push({ path: u.pathname, error: request.failure()?.errorText }); });
  try {
    await page.goto('http://127.0.0.1:41732/?force_login=1', { waitUntil: 'networkidle', timeout: 30000 });
    await page.screenshot({ path: path.join(__dirname, 'login-phone.png'), fullPage: true });
    console.log('LOGIN', await page.getByText('欢迎登录', { exact: true }).count());
    await page.goto('http://127.0.0.1:41732/', { waitUntil: 'networkidle', timeout: 30000 });
    await page.screenshot({ path: path.join(__dirname, 'home-phone.png'), fullPage: true });
    console.log('HOME loaded', (await page.locator('body').innerText()).includes('星际穿越'));
    const menu = page.locator('nav .lucide-user').first();
    if (await menu.count()) {
      await menu.click();
      await page.getByText('系统配置', { exact: true }).first().click();
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(__dirname, 'profile-phone.png'), fullPage: true });
      const text = await page.locator('body').innerText();
      console.log('SETTINGS', text.includes('Android 恢复测试版的后端 HTTPS API 地址'));
      const backend = page.locator('input').filter({ visible: true }).first();
      console.log('BACKEND', await backend.inputValue(), 'editable', await backend.isEditable());
      await backend.fill('https://pioneer.fan:884/api/');
      await page.getByRole('button', { name: '保存', exact: true }).first().click();
      await page.waitForTimeout(1200);
      console.log('SAVED_BACKEND', await page.evaluate(() => localStorage.getItem('cyberstream:android:api-base')));
    }
    fs.writeFileSync(path.join(__dirname, 'browser-verification.json'), JSON.stringify({ kind: 'isolated-playwright-android-ui-emulation', nativeBridgeTested: false, errors, failed }, null, 2));
    console.log('ERRORS', JSON.stringify({ errors, failed }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
