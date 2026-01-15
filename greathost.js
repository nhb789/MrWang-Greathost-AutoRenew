const EMAIL = process.env.GREATHOST_EMAIL || '';
const PASSWORD = process.env.GREATHOST_PASSWORD || '';
const CHAT_ID = process.env.CHAT_ID || '';
const BOT_TOKEN = process.env.BOT_TOKEN || '';
const PROXY_URL = (process.env.PROXY_URL || "socks5://admin123:admin321@138.68.253.225:30792").trim();

const { firefox } = require("playwright");
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
    const BILLING_URL = `${GREATHOST_URL}/billing/free-servers`;
    
    let proxyStatusTag = "🌐 直连模式";
    let serverStarted = false;

    // 1. 解析代理（严格拆分，因为 Playwright 代理对象需要分开填）
    let proxyConfig = null;
    if (PROXY_URL) {
        try {
            const cleanUrl = PROXY_URL.startsWith('socks') ? PROXY_URL : `socks5://${PROXY_URL}`;
            const url = new URL(cleanUrl);
            proxyConfig = {
                server: `socks5://${url.host}`,
                username: url.username,
                password: url.password
            };
            proxyStatusTag = `🔒 代理模式 (${url.host})`;
        } catch (e) {
            console.error("❌ 代理格式解析失败");
        }
    }

    let browser;
    try {
        console.log(`🚀 任务启动 | ${proxyStatusTag}`);
        
        // 2. 启动浏览器（不带代理，代理在 Context 层注入最稳）
        browser = await firefox.launch({ headless: true });

        // 3. 创建上下文 - 这是 Playwright Node.js 注入 SOCKS5 认证的官方唯一正确位置
        const context = await browser.newContext({
            proxy: proxyConfig ? proxyConfig : undefined,
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
            viewport: { width: 1280, height: 720 },
            locale: 'es-ES'
        });

        const page = await context.newPage();

        // 4. IP 检测（确保代理真的生效了）
        if (proxyConfig) {
            console.log("🌍 正在验证代理 IP...");
            try {
                await page.goto("https://api.ipify.org?format=json", { timeout: 20000 });
                console.log(`✅ 当前出口 IP: ${await page.innerText('body')}`);
            } catch (e) {
                console.warn("⚠️ IP 检测超时，尝试继续主流程...");
            }
        }

        // --- 5. 登录 (原版逻辑) ---
        await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });
        await page.fill('input[name="email"]', EMAIL);
        await page.fill('input[name="password"]', PASSWORD);
        await Promise.all([
            page.click('button[type="submit"]'),
            page.waitForNavigation({ waitUntil: "networkidle" }),
        ]);
        console.log("✅ 登录成功");

        // --- 6. 开机 (原版逻辑) ---
        await page.goto(HOME_URL, { waitUntil: "networkidle" });
        if (await page.locator('span.badge-danger, .status-offline').first().isVisible()) {
            const startBtn = page.locator('button:has-text("Start"), .btn-start').first();
            if (await startBtn.isVisible()) {
                await startBtn.click();
                serverStarted = true;
                await page.waitForTimeout(3000);
            }
        }

        // --- 7. 续期 (原版逻辑) ---
        await page.goto(BILLING_URL, { waitUntil: "networkidle" });
        await page.getByRole('link', { name: 'View Details' }).first().click();
        await page.waitForNavigation({ waitUntil: "networkidle" });
        
        const serverId = page.url().split('/').pop();
        const beforeHours = parseInt(await page.textContent('#accumulated-time')) || 0;
        const renewBtn = page.locator('#renew-free-server-btn');

        if ((await renewBtn.innerHTML()).includes('Wait')) {
            await sendTelegramMessage(`⏳ 服务器 ${serverId} 还在冷却。`);
            return;
        }

        await page.mouse.wheel(0, 300);
        await page.waitForTimeout(1000);
        await renewBtn.click({ force: true });

        await page.waitForTimeout(15000);
        await page.reload();
        const afterHours = parseInt(await page.textContent('#accumulated-time')) || 0;
        
        await sendTelegramMessage(`🎉 续期成功: ${beforeHours}h -> ${afterHours}h`);

    } catch (err) {
        console.error("❌ 崩溃:", err.message);
        await sendTelegramMessage(`🚨 脚本异常: ${err.message}`);
    } finally {
        if (browser) await browser.close();
    }
})();
