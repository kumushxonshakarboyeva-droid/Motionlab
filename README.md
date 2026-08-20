# MotionLab — Recraft AI Backend

Bu kichik backend Font mini-ilovasidagi "AI" tugmasini haqiqiy ishlaydigan qiladi.
Vazifasi: **Recraft API kalitini yashirin saqlash** va frontenddan kelgan so'rovni
Recraft'ga yo'naltirish.

## 1. O'rnatish (local test uchun)

```bash
npm install
cp .env.example .env
# .env faylini oching va RECRAFT_API_KEY qatoriga o'z kalitingizni yozing
npm start
```

Server `http://localhost:3000` da ishga tushadi.
Tekshirish: `curl http://localhost:3000/health` → `{"ok":true}` qaytarishi kerak.

## 2. API kalitini qayerdan olish

1. https://www.recraft.ai ga kiring, hisobingizga login qiling
2. Profil sahifasiga o'ting → API bo'limi → **Generate** tugmasini bosing
   (balansingizda kredit bo'lishi kerak)
3. Chiqqan tokenni `.env` faylidagi `RECRAFT_API_KEY` ga qo'ying

**MUHIM:** Bu kalitni hech qachon frontend (HTML/JS) fayliga yozmang — faqat
shu backendning `.env` faylida saqlanadi.

## 3. Deploy qilish (bepul variantlar)

Eng oson yo'l — **Render.com** yoki **Railway.app**:

1. Bu papkani (yoki butun loyihani) GitHub'ga yuklang
2. Render/Railway'da "New Web Service" → repo'ni tanlang
3. Build command: `npm install`, Start command: `npm start`
4. Environment Variables bo'limiga `RECRAFT_API_KEY` ni qo'shing
5. Deploy tugagach sizga shunday URL beriladi:
   `https://sizning-servis-nomi.onrender.com`

## 4. Frontendni ulash

`motionlab-font-preview.html` faylida quyidagi qatorni toping:

```js
const RECRAFT_BACKEND_URL = 'https://YOUR-BACKEND-URL.example.com/api/generate-letter';
```

va `YOUR-BACKEND-URL.example.com` o'rniga yuqorida olgan haqiqiy backend
manzilingizni yozing (masalan `sizning-servis-nomi.onrender.com`).

## 5. Endpoint

`POST /api/generate-letter`

So'rov tanasi (JSON):
```json
{ "letter": "G‘", "prompt": "glossy 3D chrome style", "style": "digital_illustration" }
```
- `letter` — ixtiyoriy, harf/belgi (agar `prompt` berilmasa, avtomatik prompt tuziladi)
- `prompt` — ixtiyoriy, foydalanuvchi yozgan uslub tavsifi
- `style` — ixtiyoriy, Recraft uslub kodi (masalan `digital_illustration`,
  `vector_illustration`, `realistic_image`)

Javob:
```json
{ "url": "https://...recraft-generated-image.png" }
```

## 6. Xarajat haqida eslatma

Recraft har bir generatsiya uchun kredit sarflaydi (kuniga 30 ta bepul kredit
bor). Backend ichida oddiy so'rov cheklovi (rate limit) o'rnatilgan —
bitta foydalanuvchidan daqiqasiga 12 tadan ortiq so'rovga ruxsat bermaydi,
lekin ishlab chiqarishda (production) buni Redis kabi vositalar bilan
kuchaytirish tavsiya etiladi.
