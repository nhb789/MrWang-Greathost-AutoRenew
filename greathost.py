import time
import os
import json
import requests
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 环境变量获取 =================
EMAIL = os.getenv("GREATHOST_EMAIL") or ""
PASSWORD = os.getenv("GREATHOST_PASSWORD") or ""
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or ""
# 代理地址 (已确认此格式在 Python 下完美运行)
PROXY_URL = "socks5://admin123:admin321@138.68.253.225:30792"

# URL 定义
GREATHOST_URL = "https://greathost.es"
LOGIN_URL = f"{GREATHOST_URL}/login"
HOME_URL = f"{GREATHOST_URL}/dashboard"
BILLING_URL = f"{GREATHOST_URL}/billing/free-servers"

def send_telegram(message):
    """复刻 JS 版的 HTML 报表发送功能"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram 发送失败: {e}")

def get_browser():
    """初始化浏览器，配置 selenium-wire 中转代理"""
    sw_options = {
        'proxy': {
            'http': PROXY_URL,
            'https': PROXY_URL,
            'no_proxy': 'localhost,127.0.0.1'
        }
    }
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options, seleniumwire_options=sw_options)

def run_task():
    driver = None
    server_started = False
    proxy_tag = f"🔒 代理模式 (138.68.253.225)"
    
    try:
        driver = get_browser()
        wait = WebDriverWait(driver, 30)

        # --- 1. 代理 IP 检测 ---
        print(f"🚀 任务启动 | {proxy_tag}")
        driver.get("https://api.ipify.org?format=json")
        print(f"✅ 当前出口 IP: {json.loads(driver.find_element(By.TAG_NAME, 'body').text)['ip']}")

        # --- 2. 登录流程 ---
        print("🔑 [Step 2] 正在执行登录...")
        driver.get(LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        print("✅ 登录成功！")

        # --- 3. 自动开机检查 (逻辑搬回) ---
        print("📊 [Step 3] 检查服务器实时状态...")
        driver.get(HOME_URL)
        time.sleep(3)
        offlines = driver.find_elements(By.CSS_SELECTOR, "span.badge-danger, .status-offline")
        if offlines:
            print("⚠️ 检测到服务器离线，发送启动指令...")
            try:
                start_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Start')]")
                start_btn.click()
                server_started = True
                time.sleep(5)
            except: pass

        # --- 4. 续期流程 (强力点击版) ---
        print("🔍 [Step 4] 进入 Billing 页面...")
        driver.get(BILLING_URL)
        time.sleep(5) # 给页面充足加载时间

        # 搬回 JS 里的 View Details 点击逻辑
        print("🖱️ 尝试点击 View Details...")
        # 补丁：如果常规点击不行，就用 JS 强制点
        detail_link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'View Details')]")))
        driver.execute_script("arguments[0].click();", detail_link)
        
        wait.until(EC.url_contains("/free-servers/"))
        server_id = driver.current_url.split('/')[-1]
        
        # 获取续期前时长
        time_el = wait.until(EC.presence_of_element_located((By.ID, "accumulated-time")))
        before_hours = int("".join(filter(str.isdigit, time_el.text)) or 0)

        # 搬回报表函数逻辑
        def get_html_report(icon, title, hours, detail):
            return (f"{icon} <b>GreatHost {title}</b>\n\n"
                    f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                    f"⏰ <b>当前时长:</b> {hours}h\n"
                    f"🚀 <b>开机状态:</b> {'✅ 已触发启动' if server_started else '正常'}\n"
                    f"🌐 <b>出口IP:</b> <code>138.68.253.225</code>\n"
                    f"💡 <b>详情:</b> {detail}")

        # 检查是否在冷却
        renew_btn = driver.find_element(By.ID, "renew-free-server-btn")
        if "Wait" in renew_btn.get_attribute('innerHTML'):
            wait_text = renew_btn.text
            print(f"⏳ 还在冷却中: {wait_text}")
            send_telegram(get_html_report('⏳', '续期跳过', before_hours, f"冷却中 ({wait_text})"))
            return

        # --- 5. 执行续期 ---
        print("⚡ [Step 5] 执行续期点击...")
        driver.execute_script("window.scrollBy(0, 400);")
        time.sleep(2)
        driver.execute_script("arguments[0].click();", renew_btn)

        # --- 6. 最终校验 ---
        print("⏳ 等待 20 秒数据同步...")
        time.sleep(20)
        driver.refresh()
        
        after_hours_el = wait.until(EC.presence_of_element_located((By.ID, "accumulated-time")))
        after_hours = int("".join(filter(str.isdigit(after_hours_el.text)) or 0))

        if after_hours > before_hours:
            send_telegram(get_html_report('🎉', '续期成功', after_hours, f"时长从 {before_hours}h 增加"))
        else:
            send_telegram(get_html_report('✅', '检查完成', after_hours, "时长充足，暂无需更新"))

    except Exception as e:
        print(f"❌ 脚本崩溃: {e}")
        # 如果崩溃，尝试截图（Artifacts里看）
        try: driver.save_screenshot("crash_debug.png")
        except: pass
        send_telegram(f"🚨 <b>GreatHost 脚本异常</b>\n错误: <code>{str(e)}</code>")
    finally:
        if driver:
            driver.quit()
            print("🧹 浏览器已关闭")

if __name__ == "__main__":
    run_task()
