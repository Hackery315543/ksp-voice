import os
import json
import time
import asyncio
import sqlite3
from flask import Flask, request, jsonify
import requests
import edge_tts

app = Flask(__name__)

# --- အခြေခံ အချက်အလက်များ ---
TOKEN = "9087005587:AAEEIiq_B5xxrzFgYYM6P_WdC5RNDwXFtps"
ADMIN_ID = "1638781080"
PAY_PHONE = "09409700002"
VOICE_COST = 100

WEBAPP_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ksp-voice.onrender.com").rstrip("/") + "/"
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
DB_PATH = "/tmp/users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS processed_tx
                 (msg_id TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

def get_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, 0)", (str(user_id),))
        conn.commit()
        bal = 0
    else:
        bal = row[0]
    conn.close()
    return bal

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (str(user_id),))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (int(amount), str(user_id)))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (str(user_id),))
    new_bal = c.fetchone()[0]
    conn.close()
    return new_bal

def is_tx_processed(msg_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT msg_id FROM processed_tx WHERE msg_id = ?", (str(msg_id),))
    exists = c.fetchone() is not None
    if not exists:
        c.execute("INSERT INTO processed_tx (msg_id) VALUES (?)", (str(msg_id),))
        conn.commit()
    conn.close()
    return exists

async def create_edge_audio(text, voice, rate, pitch, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)

VOICE_STYLES = {
    "football": ("my-MM-ThihaNeural", "+15%", "+0Hz"),
    "story": ("my-MM-ThihaNeural", "-5%", "+0Hz"),
    "comedy": ("my-MM-ThihaNeural", "+10%", "+5Hz"),
    "female": ("my-MM-NilarNeural", "+0%", "+0Hz")
}

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="my">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>KSP AI Voice Studio</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        :root {
            --bg-color: #0f0f13;
            --card-bg: #1c1c24;
            --accent: #a855f7;
            --blue: #2563eb;
            --green: #22c55e;
            --text-main: #ffffff;
            --text-muted: #9ca3af;
        }
        * { box-sizing: border-box; }
        body { background-color: var(--bg-color); color: var(--text-main); font-family: sans-serif; margin: 0; padding: 15px; padding-bottom: 95px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .points-badge { background-color: #1e293b; border: 1px solid #334155; padding: 6px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; color: #4ade80; display: flex; align-items: center; gap: 6px; cursor: pointer; }
        .plus-btn { background: var(--green); color: #000; border-radius: 50%; width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; }
        .section { background-color: var(--card-bg); border-radius: 12px; padding: 14px; margin-bottom: 14px; }
        .section-title { font-size: 13px; color: var(--text-muted); margin-bottom: 10px; display: block; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .voice-btn { display: flex; align-items: center; gap: 8px; background-color: #2a2a35; padding: 10px; border-radius: 8px; font-size: 12px; border: 1px solid #3f3f4e; cursor: pointer; }
        .voice-btn.active { border-color: var(--accent); background-color: rgba(168, 85, 247, 0.18); }
        .voice-icon { font-size: 18px; }
        .text-area { width: 100%; height: 110px; background: #0f172a; color: #fff; border: 1px solid #3f3f4e; border-radius: 10px; padding: 12px; font-size: 14px; resize: none; font-family: sans-serif; }
        .main-btn { background: linear-gradient(90deg, #8a2be2, #4facfe); color: white; border: none; padding: 14px; border-radius: 12px; font-size: 15px; font-weight: bold; width: 100%; cursor: pointer; margin-top: 6px; }
        .plan-card { background-color: var(--card-bg); border: 2px solid #2e2e3a; border-radius: 14px; padding: 14px; margin-bottom: 12px; cursor: pointer; }
        .plan-card.selected { border-color: #3b82f6; background-color: #172033; }
        .plan-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
        .plan-name { font-size: 16px; font-weight: bold; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .badge-pop { background: #1e293b; color: #f8fafc; font-size: 10px; padding: 2px 7px; border-radius: 10px; border: 1px solid #475569; }
        .badge-bonus { background: rgba(34, 197, 94, 0.15); color: #4ade80; font-size: 11px; padding: 2px 7px; border-radius: 10px; font-weight: bold; }
        .plan-price { text-align: right; }
        .price-mmk { font-size: 16px; font-weight: bold; color: #fff; }
        .price-thb { font-size: 11px; color: var(--text-muted); }
        .plan-stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
        .stat-box { background: rgba(255,255,255,0.04); padding: 8px 6px; border-radius: 8px; font-size: 11px; color: var(--text-muted); }
        .stat-val { font-size: 13px; font-weight: bold; color: #fff; margin: 2px 0; }
        .stat-val.green { color: #4ade80; }
        .pay-box { background: #172033; border: 1px solid #3b82f6; border-radius: 12px; padding: 14px; margin-top: 10px; display: none; }
        .copy-row { display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 10px; border-radius: 8px; margin: 8px 0; }
        .copy-btn { background: var(--blue); color: white; border: none; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; }
        .file-input { width: 100%; background: #0f172a; color: #fff; padding: 10px; border-radius: 8px; border: 1px dashed #64748b; margin: 10px 0; }
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: #16161d; border-top: 1px solid #2a2a35; display: flex; justify-content: space-around; padding: 10px 0; z-index: 100; }
        .nav-item { text-align: center; color: var(--text-muted); font-size: 12px; cursor: pointer; flex: 1; }
        .nav-item.active { color: var(--accent); font-weight: bold; }
        .tab-page { display: none; }
        .tab-page.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h3 style="margin:0;">KSP Studio</h3>
            <span style="font-size: 11px; color: var(--text-muted);">Movie Recap AI Voice</span>
        </div>
        <div class="points-badge" onclick="switchTab('plans')">
            <span id="userBalance">0 ကျပ်</span>
            <span class="plus-btn">+</span>
        </div>
    </div>

    <div id="tab-studio" class="tab-page active">
        <div class="section">
            <span class="section-title">✍️ မြန်မာစာသား ရိုက်ထည့်ပါ (စာ -> အသံ)</span>
            <textarea id="scriptText" class="text-area" placeholder="ဥပမာ - ဒီနေ့ ကြည့်ရမယ့် ဇာတ်လမ်းလေးက တကယ်ကောင်းပါတယ်နော်..."></textarea>
            <div style="font-size:11px; color:var(--text-muted); margin-top:6px;">💡 အသံတစ်ခါထုတ်လျှင် 100 ကျပ် ဖြတ်ပြီး Telegram Chat ထဲသို့ ပို့ပေးပါမည်။</div>
        </div>

        <div class="section">
            <span class="section-title">🎙️ အသံစတိုင် ရွေးချယ်ပါ</span>
            <div class="grid-2" id="voiceGroup">
                <div class="voice-btn active" onclick="selectVoice(this, 'football')"><span class="voice-icon">⚽</span><div>ဘောလုံးသတင်း<br><small style="color:var(--text-muted);">Thiha (Fast)</small></div></div>
                <div class="voice-btn" onclick="selectVoice(this, 'story')"><span class="voice-icon">📖</span><div>ပုံပြင်ပြောသူ<br><small style="color:var(--text-muted);">Thiha (Calm)</small></div></div>
                <div class="voice-btn" onclick="selectVoice(this, 'comedy')"><span class="voice-icon">😂</span><div>ဟာသပြောသူ<br><small style="color:var(--text-muted);">Thiha (Fun)</small></div></div>
                <div class="voice-btn" onclick="selectVoice(this, 'female')"><span class="voice-icon">👩</span><div>အမျိုးသမီး<br><small style="color:var(--text-muted);">Nilar (Female)</small></div></div>
            </div>
        </div>

        <button class="main-btn" id="genVoiceBtn" onclick="generateVoice()">🎙️ မြန်မာအသံ ထုတ်မယ် (100 ကျပ်)</button>
    </div>

    <div id="tab-plans" class="tab-page">
        <span class="section-title" style="font-size:14px; color:#fff;">၁. Package ရွေးပါ</span>

        <div class="plan-card selected" onclick="selectPlan(this, 'Starter', 10000, 10000)">
            <div class="plan-top">
                <div class="plan-name">🔵 Starter</div>
                <div class="plan-price"><div class="price-mmk">10,000 ကျပ်</div><div class="price-thb">≈ 80 บาท</div></div>
            </div>
            <div class="plan-stats">
                <div class="stat-box">ရမယ့် Credit<div class="stat-val green">10,000 ကျပ်</div></div>
                <div class="stat-box">5 မိနစ် video<div class="stat-val">≈ 29</div>တစ်ပုဒ် ~340 ကျပ်</div>
                <div class="stat-box">10 မိနစ် video<div class="stat-val">≈ 15</div>တစ်ပုဒ် ~630 ကျပ်</div>
            </div>
        </div>

        <div class="plan-card" onclick="selectPlan(this, 'Standard', 30000, 34500)">
            <div class="plan-top">
                <div class="plan-name">Standard <span class="badge-pop">လူကြိုက်အများဆုံး</span> <span class="badge-bonus">+15% Bonus</span></div>
                <div class="plan-price"><div class="price-mmk">30,000 ကျပ်</div><div class="price-thb">≈ 240 บาท</div></div>
            </div>
            <div class="plan-stats">
                <div class="stat-box">ရမယ့် Credit<div class="stat-val green">34,500 ကျပ်</div></div>
                <div class="stat-box">5 မိနစ် video<div class="stat-val">≈ 101</div>တစ်ပုဒ် ~295 ကျပ်</div>
                <div class="stat-box">10 မိနစ် video<div class="stat-val">≈ 54</div>တစ်ပုဒ် ~550 ကျပ်</div>
            </div>
        </div>

        <div class="plan-card" onclick="selectPlan(this, 'Pro', 50000, 60000)">
            <div class="plan-top">
                <div class="plan-name">Pro <span class="badge-bonus">+20% Bonus</span></div>
                <div class="plan-price"><div class="price-mmk">50,000 ကျပ်</div><div class="price-thb">≈ 400 บาท</div></div>
            </div>
            <div class="plan-stats">
                <div class="stat-box">ရမယ့် Credit<div class="stat-val green">60,000 ကျပ်</div></div>
                <div class="stat-box">5 မိနစ် video<div class="stat-val">≈ 176</div>တစ်ပုဒ် ~285 ကျပ်</div>
                <div class="stat-box">10 မိနစ် video<div class="stat-val">≈ 95</div>တစ်ပုဒ် ~525 ကျပ်</div>
            </div>
        </div>

        <button class="main-btn" id="continuePayBtn" onclick="showPayBox()">ဆက်မယ် (Starter · 10,000 ကျပ်)</button>

        <div class="pay-box" id="payBox">
            <h4 style="margin:0 0 8px 0;">💳 ငွေလွှဲရန် (WavePay / KBZPay)</h4>
            <div style="font-size:13px; color:#cbd5e1;" id="selectedPlanInfo"></div>
            <div class="copy-row">
                <div>
                    <div style="font-weight:bold; font-size:15px;">09409700002</div>
                    <div style="font-size:11px; color:var(--text-muted);">WavePay / KBZPay (Kaung San Phyo)</div>
                </div>
                <button class="copy-btn" onclick="copyPhone()">Copy</button>
            </div>
            <label style="font-size:12px; color:#cbd5e1;">ငွေလွှဲပြေစာ (Screenshot) ပုံတင်ပါ:</label>
            <input type="file" id="slipFile" class="file-input" accept="image/*">
            <button class="main-btn" id="submitSlipBtn" style="background:var(--green); color:#000;" onclick="submitPayment()">✅ ပြေစာတင်မည်</button>
        </div>
    </div>

    <div class="bottom-nav">
        <div class="nav-item active" id="nav-studio" onclick="switchTab('studio')">🎙️<br>Studio</div>
        <div class="nav-item" id="nav-plans" onclick="switchTab('plans')">💳<br>ငွေဖြည့်</div>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();

        const user = tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : {id: "0", first_name: "Guest"};
        let currentPlan = {name: "Starter", price: 10000, credit: 10000};
        let selectedVoice = "football";

        function loadBalance() {
            if (user.id !== "0") {
                fetch('/api/balance?user_id=' + user.id)
                    .then(r => r.json())
                    .then(d => {
                        document.getElementById('userBalance').innerText = d.balance.toLocaleString() + " ကျပ်";
                    });
            }
        }
        loadBalance();

        function switchTab(tab) {
            document.querySelectorAll('.tab-page').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-' + tab).classList.add('active');
            document.getElementById('nav-' + tab).classList.add('active');
        }

        function selectVoice(el, voiceKey) {
            document.getElementById('voiceGroup').querySelectorAll('.active').forEach(item => item.classList.remove('active'));
            el.classList.add('active');
            selectedVoice = voiceKey;
        }

        function selectPlan(el, name, price, credit) {
            document.querySelectorAll('.plan-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            currentPlan = {name, price, credit};
            document.getElementById('continuePayBtn').innerText = `ဆက်မယ် (${name} · ${price.toLocaleString()} ကျပ်)`;
            document.getElementById('payBox').style.display = 'none';
        }

        function showPayBox() {
            document.getElementById('selectedPlanInfo').innerText = `ရွေးထားသော Package: ${currentPlan.name} (${currentPlan.price.toLocaleString()} ကျပ် → Credit ${currentPlan.credit.toLocaleString()} ကျပ်)`;
            document.getElementById('payBox').style.display = 'block';
            window.scrollTo(0, document.body.scrollHeight);
        }

        function copyPhone() {
            navigator.clipboard.writeText("09409700002");
            tg.showAlert("ဖုန်းနံပါတ် 09409700002 ကို Copy ကူးပြီးပါပြီ။");
        }

        function generateVoice() {
            const text = document.getElementById('scriptText').value.trim();
            if (!text) {
                tg.showAlert("မြန်မာစာသား အရင်ရိုက်ထည့်ပေးပါ။");
                return;
            }
            const btn = document.getElementById('genVoiceBtn');
            btn.innerText = "⏳ အသံထုတ်နေပါသည်...";
            btn.disabled = true;

            fetch('/api/generate_voice', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: user.id, text: text, voice: selectedVoice })
            })
            .then(r => r.json())
            .then(d => {
                btn.innerText = "🎙️ မြန်မာအသံ ထုတ်မယ် (100 ကျပ်)";
                btn.disabled = false;
                if (d.ok) {
                    loadBalance();
                    tg.showAlert("✅ အသံဖိုင် ထုတ်ပြီးပါပြီ! Telegram Chat ထဲမှာ သွားနားထောင်နိုင်ပါပြီ။");
                } else {
                    tg.showAlert("❌ " + d.error);
                }
            })
            .catch(err => {
                btn.innerText = "🎙️ မြန်မာအသံ ထုတ်မယ် (100 ကျပ်)";
                btn.disabled = false;
                tg.showAlert("ချိတ်ဆက်မှု အမှားဖြစ်သွားပါသည်။");
            });
        }

        function submitPayment() {
            const fileInput = document.getElementById('slipFile');
            if (!fileInput.files.length) {
                tg.showAlert("ငွေလွှဲပြေစာ (Screenshot) ပုံကို အရင်ရွေးပေးပါ။");
                return;
            }
            const btn = document.getElementById('submitSlipBtn');
            btn.innerText = "ပို့နေပါသည်...";
            btn.disabled = true;

            const formData = new FormData();
            formData.append("slip", fileInput.files[0]);
            formData.append("user_id", user.id);
            formData.append("user_name", user.first_name || "User");
            formData.append("plan_name", currentPlan.name);
            formData.append("price", currentPlan.price);
            formData.append("credit", currentPlan.credit);

            fetch('/api/submit_payment', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(d => {
                    btn.innerText = "✅ ပြေစာတင်မည်";
                    btn.disabled = false;
                    if (d.ok) {
                        tg.showAlert("ပြေစာပို့ပြီးပါပြီ! Admin စစ်ဆေးအတည်ပြုပြီးတာနဲ့ Credit ဝင်လာပါမယ်။");
                        document.getElementById('payBox').style.display = 'none';
                        fileInput.value = "";
                    } else {
                        tg.showAlert("အမှားဖြစ်သွားပါသည်: " + d.error);
                    }
                })
                .catch(err => {
                    btn.innerText = "✅ ပြေစာတင်မည်";
                    btn.disabled = false;
                    tg.showAlert("ချိတ်ဆက်မှု အမှားဖြစ်သွားပါသည်။");
                });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return HTML_CONTENT

@app.route('/api/balance')
def api_balance():
    user_id = request.args.get('user_id', '0')
    return jsonify({"balance": get_balance(user_id)})

@app.route('/api/generate_voice', methods=['POST'])
def api_generate_voice():
    tmp_path = None
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', '0'))
        text = data.get('text', '').strip()
        voice_key = data.get('voice', 'football')

        if not text:
            return jsonify({"ok": False, "error": "စာသားမပါဝင်ပါ။"})

        bal = get_balance(user_id)
        if bal < VOICE_COST:
            return jsonify({"ok": False, "error": f"လက်ကျန်ငွေ မလုံလောက်ပါ (အနည်းဆုံး {VOICE_COST} ကျပ် လိုအပ်ပါသည်)။ ငွေဖြည့်ပေးပါ။"})

        voice, rate, pitch = VOICE_STYLES.get(voice_key, VOICE_STYLES["football"])
        tmp_path = f"/tmp/voice_{user_id}_{int(time.time())}.mp3"
        asyncio.run(create_edge_audio(text, voice, rate, pitch, tmp_path))

        with open(tmp_path, 'rb') as f:
            files = {'audio': ('KSP_AI_Voice.mp3', f, 'audio/mpeg')}
            payload = {
                'chat_id': user_id,
                'title': 'KSP AI Voice',
                'performer': 'Movie Myanmar AI',
                'caption': f"🎙️ KSP - AI Voice Generator\n💰 ဖြတ်ငွေ: {VOICE_COST} ကျပ်"
            }
            res = requests.post(f"{TELEGRAM_API}/sendAudio", data=payload, files=files)

        if res.ok:
            update_balance(user_id, -VOICE_COST)
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": "Telegram သို့ အသံပို့၍မရပါ။"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.route('/api/submit_payment', methods=['POST'])
def submit_payment():
    try:
        slip = request.files['slip']
        user_id = request.form.get('user_id')
        user_name = request.form.get('user_name')
        plan_name = request.form.get('plan_name')
        price = request.form.get('price')
        credit = request.form.get('credit')

        caption = (
            f"🔔 <b>ငွေဖြည့်ပြေစာအသစ် ရောက်ရှိပါသည်!</b>\n\n"
            f"👤 User: {user_name} (<code>{user_id}</code>)\n"
            f"📦 Plan: {plan_name} ({int(price):,} ကျပ်)\n"
            f"💰 ထည့်ပေးရမည့် Credit: {int(credit):,} ကျပ်"
        )

        reply_markup = {
            "inline_keyboard": [[
                {"text": f"✅ Approve (+{int(credit):,})", "callback_data": f"approve_{user_id}_{credit}_{plan_name}"},
                {"text": "❌ Reject", "callback_data": f"reject_{user_id}_{plan_name}"}
            ]]
        }

        files = {'photo': (slip.filename, slip.read(), slip.content_type)}
        data = {
            'chat_id': ADMIN_ID,
            'caption': caption,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(reply_markup)
        }
        res = requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files)
        return jsonify({"ok": res.ok, "error": "" if res.ok else res.text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return "OK", 200

    if "message" in update and "text" in update["message"]:
        if update["message"]["text"] == "/start":
            chat_id = update["message"]["chat"]["id"]
            get_balance(chat_id)
            send_welcome(chat_id)

    elif "callback_query" in update:
        cb = update["callback_query"]
        data = cb["data"]
        cb_id = cb["id"]
        msg_id = cb["message"]["message_id"]
        chat_id = cb["message"]["chat"]["id"]
        old_caption = cb["message"].get("caption", "")

        if is_tx_processed(msg_id):
            requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "လုပ်ဆောင်ပြီးသား ဖြစ်ပါသည်။"})
            return "OK", 200

        if data.startswith("approve_"):
            _, target_uid, credit, plan_name = data.split("_", 3)
            new_bal = update_balance(target_uid, int(credit))
            requests.post(f"{TELEGRAM_API}/editMessageCaption", json={
                "chat_id": chat_id, "message_id": msg_id,
                "caption": old_caption + "\n\n✅ <b>အတည်ပြုပြီး (Approved)</b>", "parse_mode": "HTML"
            })
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": target_uid,
                "text": f"✅ ငွေပေးချေမှု အတည်ပြုပြီးပါပြီ!\n\n📦 {plan_name} — Credit {int(credit):,} ကျပ် ဝင်ပါပြီ။\n💰 လက်ကျန်ငွေ: {new_bal:,} ကျပ်\n\nကျေးဇူးတင်ပါတယ် 🙏"
            })
            requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Approved!"})

        elif data.startswith("reject_"):
            _, target_uid, plan_name = data.split("_", 2)
            requests.post(f"{TELEGRAM_API}/editMessageCaption", json={
                "chat_id": chat_id, "message_id": msg_id,
                "caption": old_caption + "\n\n❌ <b>ပယ်ဖျက်ပြီး (Rejected)</b>", "parse_mode": "HTML"
            })
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": target_uid,
                "text": f"❌ {plan_name} အတွက် ငွေလွှဲပြေစာကို အတည်မပြုနိုင်ပါ။ ကျေးဇူးပြု၍ Admin (@MM2DKSP) သို့ ဆက်သွယ်ပါ။"
            })
            requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Rejected!"})

    return "OK", 200

def send_welcome(chat_id):
    payload = {
        "chat_id": chat_id,
        "text": "မင်္ဂလာပါ! KSP AI Voice Generator မှ ကြိုဆိုပါတယ်။ 🎬\n\nအောက်ပါ 'Open Studio' ကို နှိပ်ပြီး စတင်လိုက်ပါ။",
        "reply_markup": {
            "inline_keyboard": [[{"text": "🎙️ Open Studio", "web_app": {"url": WEBAPP_URL}}]]
        }
    }
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)

@app.route('/set_webhook')
def set_webhook():
    webhook_url = f"{WEBAPP_URL}{TOKEN}"
    res = requests.get(f"{TELEGRAM_API}/setWebhook?url={webhook_url}")
    return f"Webhook setup result: {res.text}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
