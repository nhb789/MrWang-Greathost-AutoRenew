const EMAIL = process.env.GREATHOST_EMAIL || 'zhangbin0301@qq.com';
const PASSWORD = process.env.GREATHOST_PASSWORD || '987277984';
const CHAT_ID = process.env.CHAT_ID || '558914831';
const BOT_TOKEN = process.env.BOT_TOKEN || '5824972634:AAGJG-FBAgPljwpnlnD8Lk5Pm2r1QbSk1AI';

const { chromium } = require("playwright");
const https = require('https');

async function sendTelegramMessage(message) {
  return new Promise((resolve) => {
    const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
    const data = JSON.stringify({ chat_id: CHAT_ID, text: message, parse_mode: 'HTML' });
    const options = { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } };
    const req = https.request(url, options, (res) => {
      res.on('data', () => {});
      res.on('end', () => resolve());
    });
    req.on('error', () => resolve());
    req.write(data);
    req.end();
  });
}

(async () => {
  const GREATHOST_URL = "https://greathost.es";
  const LOGIN_URL = `${GREATHOST_URL}/login`;
  const HOME_URL = `${GREATHOST_URL}/dashboard`;

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    // === 1. 登录 ===
    console.log("🔑 打开登录页：", LOGIN_URL);
    await page.goto(LOGIN_URL, { waitUntil: "networkidle" });
    await page.fill('input[name="email"]', EMAIL);
    await page.fill('input[name="password"]', PASSWORD);
    await Promise.all([
      page.click('button[type="submit"]'),
      page.waitForNavigation({ waitUntil: "networkidle" }),
    ]);
    console.log("✅ 登录成功！");
    await page.waitForTimeout(2000);

    // === 2. 状态检查与自动开机 ===
    console.log("📊 检查服务器实时状态...");
    const statusText = await page.locator('.server-status, #server-status-detail, .status-badge').first().textContent().catch(() => 'unknown');
    const statusLower = statusText.toLowerCase();
    
    let serverStarted = false;
    if (statusLower.includes('offline') || statusLower.includes('stop') || statusLower.includes('离线')) {
      console.log("⚡ 服务器离线，尝试启动...");
      const startBtn = page.locator('.server-actions button, .server-main-action button').first(); 
      await startBtn.click();
      await page.waitForTimeout(3000); 
      serverStarted = true;
      console.log("✅ 启动命令已发送");
    }

    // === 3. 点击 Billing 图标进入账单页 ===
    console.log("🔍 点击 Billing 图标...");
    const billingBtn = page.locator('.btn-billing-compact').first();
    const href = await billingBtn.getAttribute('href');
 

    await Promise.all([
      billingBtn.click(),
      page.waitForNavigation({ waitUntil: "networkidle" })
    ]);
    
    console.log("⏳ 已进入 Billing，等待3秒...");
    await page.waitForTimeout(3000);

    // === 4. 点击 View Details 进入详情页 ===
    console.log("🔍 点击 View Details...");
    await Promise.all([
      page.getByRole('link', { name: 'View Details' }).first().click(),
      page.waitForNavigation({ waitUntil: "networkidle" })
    ]);
    
    console.log("⏳ 已进入详情页，等待3秒...");
    await page.waitForTimeout(3000);

       // 提前提取 ID，防止页面跳转后丢失上下文
    const serverId = page.url().split('/').pop() || 'unknown';
    console.log(`🆔 解析到 Server ID: ${serverId}`);

    
// === 4. 关键：等待异步数据从 "Loading..." 变为真实数值 ===
    console.log("⏳ 等待合约数据加载...");
    const nextRenewalDate = page.locator('#next-renewal-date');
    // 等待文字不再是 "Loading..."，最多等 10 秒
    await nextRenewalDate.waitFor({ state: 'visible' });
    await page.waitForFunction(
      selector => {
        const el = document.querySelector(selector);
        return el && el.textContent !== 'Loading...' && el.textContent.trim() !== '';
      },
      '#next-renewal-date',
      { timeout: 10000 }
    ).catch(() => console.log("⚠️ 数据加载超时，尝试继续执行"));

    // === 5. 检查续期按钮文字 (处理 Wait 逻辑) ===
    // 你的截图显示按钮文字是动态的，可能包含 "Wait" 或 "Renew"
    const renewBtn = page.locator('button:has-text("Renew"), button:has-text("Wait"), button:has-text("续期")').first();
    const btnText = (await renewBtn.textContent() || "").trim();
    
    // 获取续期前的累计时间
    const beforeHoursText = await page.locator('div:has-text("Accumulated time") + div').first().textContent();
    const beforeHours = parseInt(beforeHoursText.replace(/[^0-9]/g, '')) || 0;

    console.log(`📊 按钮文案: "${btnText}" | 累计时间: ${beforeHours}h`);

    // 如果按钮显示 Wait，发送通知并直接结束
    if (btnText.includes('Wait')) {
      const msg = `ℹ️ <b>GreatHost 尚未到续期时间</b>\n🆔 ID: <code>${serverId}</code>\n⏳ 状态: ${btnText}\n⏰ 累计: ${beforeHours}h`;
      await sendTelegramMessage(msg);
      return;
    }

    // === 6. 执行点击与二次验证 ===
    console.log("⚡ 触发续期按钮...");
    await renewBtn.click();
    
    // 点击后强制等待并刷新，防止前端“虚假增加”
    await page.waitForTimeout(8000); 
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(3000);

    const afterHoursText = await page.locator('div:has-text("Accumulated time") + div').first().textContent();
    const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;

    // === 7. 结果判定 ===
    if (afterHours > beforeHours) {
      const msg = `🎉 <b>GreatHost 续期成功</b>\n🆔 ID: <code>${serverId}</code>\n⏰ 时间: ${beforeHours} ➔ ${afterHours}h`;
      await sendTelegramMessage(msg);
      console.log("🎉 任务完成");
    } else {
      const msg = `⚠️ <b>GreatHost 续期未生效</b>\n🆔 ID: <code>${serverId}</code>\n⏰ 时间仍为: ${beforeHours}h\n💡 提示: 请检查账号是否有足够金币或手动操作一次。`;
      await sendTelegramMessage(msg);
      console.log("⚠️ 续期未生效");
    }

  } catch (err) {
    console.error("❌ 运行时出错:", err.message);
    await sendTelegramMessage(`🚨 <b>GreatHost 脚本报错</b>\n<code>${err.message}</code>`);
  } finally {
    await browser.close();
  }
})();
