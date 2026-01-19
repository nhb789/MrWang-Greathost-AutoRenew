import os, re, time, random, requests, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区 =================
EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY_URL = os.getenv("PROXY_URL", "")

STATUS_MAP = {
    "Running": ["🟢", "运行中"],
    "Starting": ["🟡", "启动中"],
    "Stopped": ["🔴", "已关机"],
    "Offline": ["⚪", "离线"],
    "Suspended": ["🚫", "已暂停/封禁"]
}

# ================= 工具函数 =================
def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def get_proxy_expected_host():
    if not PROXY_URL: return None
    try: return urlparse(PROXY_URL).hostname
    except: return None

def calculate_hours(date_str):
    try:
        if not date_str: return 0
        expiry = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return max(0, int((expiry - now).total_seconds() / 3600))
    except: return 0

def fetch_api(driver, url, method="GET"):
    """执行 JS 抓取 API 并打印调试信息"""
    script = f"return fetch('{url}', {{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
    res = driver.execute_script(script)
    print(f"📡 API 调用 [{method}] {url}\n📦 原始响应: {json.dumps(res, ensure_ascii=False)}")
    return res

def send_notice(kind, fields):
    titles = {"renew_success":"🎉 <b>续期成功</b>", "maxed_out":"🈵 <b>已达上限</b>", 
              "cooldown":"⏳ <b>还在冷却</b>", "renew_failed":"⚠️ <b>续期未生效</b>", "error":"🚨 <b>脚本报错</b>"}
    body = "\n".join([f"{e} <b>{l}:</b> {v}" for e,l,v in fields])
    msg = f"{titles.get(kind, '‼️ 通知')}\n\n{body}\n📅 <b>时间:</b> {now_shanghai()}"
    if TELEGRAM_BOT_TOKEN:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)

# ================= 主流程 =================
def run_task():
    driver = None
    server_id, server_name = "未知", "未知"
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        driver = webdriver.Chrome(options=opts, seleniumwire_options={'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None)
        wait = WebDriverWait(driver, 25)

        # 1. 登录
        print(f"🔑 正在尝试登录: {EMAIL}...")
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME,"email"))).send_keys(EMAIL)
        driver.find_element(By.NAME,"password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR,"button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        print("✅ 登录成功，进入 Dashboard")

        # 2. 获取 Server 基础信息
        servers = fetch_api(driver, "/api/servers")
        if not servers or not isinstance(servers, list): raise Exception("未能获取服务器列表")
        server_id = servers[0].get('id')
        print(f"🆔 锁定服务器 ID: {server_id}")
        
        # 3. 获取详细状态信息 (包含 Name)
        info = fetch_api(driver, f"/api/servers/{server_id}/information")
        server_name = info.get('name', '未命名')
        real_status = info.get('status', 'Unknown')
        print(f"📋 服务器详情: 名称={server_name} | 状态={real_status}")

        # 4. 合同页预检 (时间 & 冷却按钮)
        driver.get(f"https://greathost.es/contracts/{server_id}")
        time.sleep(2)
        
        contract = fetch_api(driver, f"/api/servers/{server_id}/contract")
        before_h = calculate_hours(contract.get('renewalInfo', {}).get('nextRenewalDate'))
        
        btn = wait.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        btn_text = btn.text.strip()
        print(f"🔘 按钮文本: '{btn_text}' | 当前剩余: {before_h}h")
        
        if "Wait" in btn_text:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn_text)
            wait_time = m.group(1) if m else btn_text
            print(f"⏳ 触发冷却防御: {wait_time}")
            send_notice("cooldown", [("📛","名称",server_name), ("⏳","等待",wait_time), ("📊","当前",f"{before_h}h")])
            return

        # 5. 执行续期动作
        print("🚀 发起续期 POST 请求...")
        res = fetch_api(driver, f"/api/renewal/contracts/{server_id}/renew-free", method="POST")
        
        is_success = res.get('success', False)
        hours_added = res.get('details', {}).get('hoursAdded', 0)
        after_h = calculate_hours(res.get('details', {}).get('nextRenewalDate')) or before_h
        
        icon, status_name = STATUS_MAP.get(real_status.capitalize(), ["🟢", real_status])
        status_disp = f"{icon} {status_name}"

        # 6. 最终判定逻辑 (包含 5 天上限西班牙语处理)
        if is_success and hours_added > 0:
            print(f"🎉 成功增加 {hours_added} 小时")
            send_notice("renew_success", [("📛","名称",server_name), ("⏰","变化",f"{before_h} ➔ {after_h}h"), ("🚀","状态",status_disp)])
        elif "5 d" in str(res.get('message', '')) or (before_h > 110):
            print("🈵 判定为已达上限 (5 days limit)")
            send_notice("maxed_out", [("📛","名称",server_name), ("⏰","余额",f"{after_h}h"), ("🚀","状态",status_disp), ("💡","提示","已达5天上限")])
        else:
            print(f"❌ 续期失败，原因: {res.get('message')}")
            send_notice("renew_failed", [("📛","名称",server_name), ("💡","原因",res.get('message','未知失败'))])

    except Exception as e:
        print(f"🚨 脚本异常: {e}")
        send_notice("error", [("📛","服务器",server_name), ("❌","故障",f"<code>{str(e)[:100]}</code>")])
    finally:
        if driver: driver.quit(); print("🧹 浏览器会话已关闭")

if __name__ == "__main__":
    run_task()
