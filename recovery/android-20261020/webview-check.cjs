const { chromium } = require(process.argv[2]);
const fs = require('node:fs'), path = require('node:path');
(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:41733');
  try {
    const page = browser.contexts()[0].pages()[0];
    const evidence = await page.evaluate(async () => {
      const response = await fetch('https://pioneer.fan:884/api/v1/auth/me', { credentials: 'include' });
      return {
        origin: location.origin,
        platform: window.Capacitor.getPlatform(),
        nativePlayerAvailable: window.Capacitor.isPluginAvailable('CyberPlayer'),
        authHttpStatus: response.status,
        catalogVisible: document.body.innerText.includes('星际穿越'),
      };
    });
    fs.writeFileSync(path.join(__dirname, 'webview-verification.json'), JSON.stringify(evidence, null, 2));
    console.log(evidence);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
