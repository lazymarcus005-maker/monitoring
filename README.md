# Claude Usage Monitor

Web dashboard ที่แสดง token, cost, latency, และ model ของทุก request ที่ส่งไปยัง Anthropic API
พร้อม endpoint สำหรับ push ข้อมูลไปแสดงบน **GeekMagic SmallTV Ultra** เป็นรูป PNG 240×240

---

## หน้าตา

```
┌──────────────────────────────────────┐
│ ▸ Claude Monitor              14:32  │
├──────────────────────────────────────┤
│ Requests           12                │
│ In tokens       4,210                │
│ Out tokens      1,830                │
│ Total cost   $0.00412                │
│ Avg latency      843 ms              │
├──────────────────────────────────────┤
│ Recent                               │
│ 14:31  haiku-4.5      $0.00031       │
│ 14:29  sonnet-4.6     $0.00180       │
│ 14:25  haiku-4.5      $0.00028       │
└──────────────────────────────────────┘
```

Browser dashboard: summary cards + chat UI + history table  
SmallTV Ultra: PNG 240×240 ที่ push ผ่าน HTTP

---

## วิธีติดตั้ง

```bash
git clone https://github.com/lazymarcus005-maker/monitoring.git
cd monitoring

pip install -r requirements.txt

cp .env.example .env
# แก้ไข .env ใส่ API key
```

**.env**
```
ANTHROPIC_API_KEY=sk-ant-...
PORT=5000
SMALLTV_IP=192.168.1.xxx   # optional, สำหรับ SmallTV Ultra
```

```bash
python server.py
```

เปิด browser ที่ `http://localhost:5000`

---

## API Endpoints

| Method | Path | คำอธิบาย |
|--------|------|----------|
| `GET`  | `/` | Web dashboard |
| `POST` | `/api/chat` | ส่งข้อความไปยัง Claude |
| `GET`  | `/api/summary` | สรุปรวม tokens/cost/latency |
| `GET`  | `/api/history` | ประวัติ 100 request ล่าสุด |
| `GET`  | `/api/tv-image` | Preview PNG 240×240 สำหรับ SmallTV |
| `POST` | `/api/tv-push` | Push PNG ไปที่ SmallTV Ultra |

### POST /api/chat

```json
{
  "message": "สวัสดี",
  "model": "claude-haiku-4-5-20251001"
}
```

Response:
```json
{
  "content": "สวัสดีครับ!",
  "usage": {
    "timestamp": "14:32:01",
    "model": "claude-haiku-4-5-20251001",
    "input_tokens": 12,
    "output_tokens": 8,
    "cost_usd": 0.0000418,
    "latency_ms": 731
  }
}
```

---

## Model ที่รองรับ + ราคา

| Model | Input ($/M) | Output ($/M) |
|-------|-------------|--------------|
| claude-haiku-4-5-20251001 | $0.80 | $4.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-opus-4-7 | $15.00 | $75.00 |

> แนะนำให้ใช้ **Haiku** เป็น default — ถูกที่สุดและเร็วพอสำหรับ monitoring

---

## แสดงผลบน GeekMagic SmallTV Ultra

SmallTV Ultra (ESP8266, จอ 240×240px) รับไฟล์ภาพผ่าน HTTP  
Server จะ render usage stats เป็น PNG แล้ว POST ไปที่ endpoint `/doUpload` ของอุปกรณ์

### วิธีใช้

**1. ดู preview PNG ก่อน**
```
GET http://localhost:5000/api/tv-image
```

**2. Push ไปที่ device ครั้งเดียว**
```bash
curl -X POST http://localhost:5000/api/tv-push \
  -H "Content-Type: application/json" \
  -d '{"device_ip": "192.168.1.xxx"}'
```

**3. Push อัตโนมัติทุก N นาที** (cron)

```bash
# push ทุก 5 นาที
*/5 * * * * curl -s -X POST http://localhost:5000/api/tv-push \
  -H "Content-Type: application/json" \
  -d '{"device_ip": "192.168.1.xxx"}'
```

หรือตั้ง `SMALLTV_IP` ใน `.env` แล้วส่งแค่ `{}`:
```bash
curl -X POST http://localhost:5000/api/tv-push -H "Content-Type: application/json" -d '{}'
```

### หา IP ของ SmallTV

1. เปิด Web Console ของ SmallTV ผ่าน browser
2. หรือดูจาก router DHCP table
3. อุปกรณ์จะ broadcast ที่ `http://192.168.4.1` เมื่ออยู่ใน AP mode

---

## โครงสร้างไฟล์

```
monitoring/
├── server.py              # Flask backend
├── templates/
│   └── index.html         # Web dashboard
├── requirements.txt
├── .env.example
└── .gitignore
```
