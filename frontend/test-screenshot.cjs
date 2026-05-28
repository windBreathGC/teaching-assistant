const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // 1. 首页
  await page.goto('http://localhost:5173');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/c/Projects/Python/teaching-assistant/screenshot-home.png', fullPage: true });
  console.log('Home page screenshot saved');

  // 2. 点击数学进入聊天页
  const mathCard = await page.locator('.subject-card').filter({ hasText: /数学/ });
  if (await mathCard.count() > 0) {
    await mathCard.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: '/c/Projects/Python/teaching-assistant/screenshot-chat.png', fullPage: true });
    console.log('Chat page screenshot saved');
  }

  await browser.close();
  console.log('Done');
})();
