"""
รันบนเครื่อง host (ไม่ใช่ใน Docker) เพื่อ login claude.ai ครั้งเดียว
แล้วบันทึก session ไว้ใน claude_auth.json

  pip install playwright
  playwright install chromium
  python setup_auth.py
"""
from playwright.sync_api import sync_playwright

AUTH_FILE = "claude_auth.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://claude.ai/login")

    print("=" * 50)
    print("Login claude.ai ใน browser ที่เปิดขึ้นมา")
    print("เมื่อ login สำเร็จแล้ว กลับมากด Enter ที่นี่")
    print("=" * 50)
    input()

    ctx.storage_state(path=AUTH_FILE)
    browser.close()

print(f"บันทึก session ไว้ใน {AUTH_FILE} แล้ว")
print("คัดลอกไฟล์นี้ไปไว้ใน folder เดียวกับ docker-compose.yml")
