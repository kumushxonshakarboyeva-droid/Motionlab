import 'dotenv/config';
import express from 'express';
import cors from 'cors';

const app = express();
app.use(cors());
app.use(express.json({ limit: '1mb' }));

const RECRAFT_API_KEY = process.env.RECRAFT_API_KEY;
const RECRAFT_URL = 'https://external.api.recraft.ai/v1/images/generations';

if (!RECRAFT_API_KEY) {
  console.warn('OGOHLANTIRISH: RECRAFT_API_KEY .env faylida topilmadi. /api/generate-letter ishlamaydi.');
}

// Oddiy so'rov cheklovi — bitta IP dan daqiqada ko'p bo'lmagan so'rov (asosiy himoya)
const hits = new Map();
function rateLimited(ip) {
  const now = Date.now();
  const windowMs = 60_000;
  const max = 12;
  const arr = (hits.get(ip) || []).filter(t => now - t < windowMs);
  arr.push(now);
  hits.set(ip, arr);
  return arr.length > max;
}

app.post('/api/generate-letter', async (req, res) => {
  try {
    if (!RECRAFT_API_KEY) {
      return res.status(500).json({ error: 'Serverda RECRAFT_API_KEY sozlanmagan.' });
    }
    const ip = req.headers['x-forwarded-for'] || req.socket.remoteAddress || 'unknown';
    if (rateLimited(String(ip))) {
      return res.status(429).json({ error: 'Juda ko\u2018p so\u2018rov. Birozdan keyin urinib ko\u2018ring.' });
    }

    const { letter, prompt, style } = req.body || {};
    if (!letter && !prompt) {
      return res.status(400).json({ error: 'letter yoki prompt majburiy.' });
    }

    // Foydalanuvchi promptini xavfsiz shaklda harf generatsiyasi so'roviga aylantiramiz
    const basePrompt = prompt && String(prompt).trim()
      ? String(prompt).trim().slice(0, 400)
      : `A single stylish decorative letter "${String(letter).slice(0, 2)}", centered, isolated on plain background, bold clean typography, high detail`;

    const body = {
      prompt: basePrompt,
      style: style || 'digital_illustration',
      model: 'recraftv3',
      size: '1024x1024',
      n: 1,
      response_format: 'url'
    };

    const r = await fetch(RECRAFT_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${RECRAFT_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });

    if (!r.ok) {
      const errText = await r.text();
      console.error('Recraft API xatosi:', r.status, errText);
      return res.status(502).json({ error: 'Recraft API xatosi qaytardi.', status: r.status });
    }

    const data = await r.json();
    const url = data && data.data && data.data[0] && data.data[0].url;
    if (!url) {
      console.error('Kutilmagan javob:', JSON.stringify(data));
      return res.status(502).json({ error: 'Rasm URL topilmadi.' });
    }
    res.json({ url });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: 'Server xatosi.' });
  }
});

app.get('/health', (req, res) => res.json({ ok: true }));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Recraft backend ${PORT}-portda ishga tushdi`));
