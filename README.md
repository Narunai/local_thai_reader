# เล่านิยาย · Local Thai Reader

Chrome Extension อ่านนิยายไทยด้วยโมเดลเสียงในคอมพิวเตอร์ สำหรับ Windows รองรับ OG Thai, Nekopost และข้อความที่เลือกบนเว็บอื่น มีแผงควบคุมด้านข้าง อ่านตอนถัดไป จดจำตำแหน่ง และปรับคำอ่านได้

โปรเจกต์แยกเป็นสองโฟลเดอร์:

- [`local-tts`](local-tts/README.md): FastAPI และโมเดลเสียง Vachana, Thonburian/F5 และ OmniVoice
- [`extension`](extension/README.md): Chrome Extension Manifest V3 พร้อมไฟล์ `dist` สำหรับ Load unpacked

## ติดตั้งบน Windows

ต้องมี Python 3.10 และ Git หากใช้ F5/OmniVoice ให้ติดตั้ง FFmpeg และไดรเวอร์ NVIDIA ที่รองรับด้วย โมเดล GPU ใช้ environment แยกตามคู่มือ ตัวเลือก Vachana ใช้ CPU ได้

```powershell
git clone https://github.com/Narunai/local_thai_reader.git
cd local_thai_reader
powershell -ExecutionPolicy Bypass -File .\local-tts\setup.ps1
```

เริ่มด้วย Vachana เพื่อดาวน์โหลดเสียงพื้นฐาน จากนั้นเลือกติดตั้งโมเดลเพิ่มเติมได้:

```powershell
# OmniVoice พร้อม environment แยก
powershell -ExecutionPolicy Bypass -File .\local-tts\setup-omnivoice.ps1

# หรือ Thonburian/F5
powershell -ExecutionPolicy Bypass -File .\local-tts\setup.ps1 -Profile thonburian
```

เริ่มเซิร์ฟเวอร์แล้วเปิดหน้าต่างนี้ไว้ระหว่างฟัง:

```powershell
powershell -ExecutionPolicy Bypass -File .\local-tts\start.ps1
```

1. เปิด `chrome://extensions` และเปิด Developer mode
2. กด **Load unpacked** แล้วเลือก `extension/dist` ในโฟลเดอร์ที่ clone มา
3. เปิดเว็บนิยาย แล้วกดไอคอน **เล่านิยาย**
4. เปิดการตั้งค่า ใส่ Token จากไฟล์ `local-tts/.token` แล้วบันทึก
5. เลือกเสียงแล้วกด **อ่านบทนี้**

Token เป็นรหัสจับคู่กับเซิร์ฟเวอร์ ไม่ใช่คำสั่ง PowerShell เซิร์ฟเวอร์ฟังที่ `127.0.0.1:8765` แคชและไฟล์ชั่วคราวใช้ `D:\AI_Cache` เป็นค่าเริ่มต้น ต้องมีไดรฟ์ D และพื้นที่พอสำหรับโมเดล ส่วนโปรไฟล์ Chrome ปกติยังต้องมีพื้นที่ว่างบนไดรฟ์ที่ติดตั้งโปรไฟล์

## คำอ่านและ Gemini

กำหนดพจนานุกรมคำอ่านใน Extension ได้ เช่น `ลอเอล=ลอ เอล` การสร้างเสียงใช้โมเดลบนเครื่องทั้งหมดหลังดาวน์โหลดครบ หากเปิด **Gemini ช่วยเตรียมคำอ่าน** ข้อความนิยายจะถูกส่งไป Google ตามการตั้งค่าและอาจมีค่าใช้จ่าย บริการนี้ปิดเป็นค่าเริ่มต้น

Repository เก็บโค้ดและ Extension ที่ build แล้ว ไฟล์ Token, API key, environment Python, โมเดล, เสียงอ้างอิงจริง และแคชถูกละไว้ การติดตั้งจะสร้างข้อมูลที่จำเป็นบนเครื่องของผู้ใช้ ดูแหล่งที่มาและเงื่อนไขโมเดลใน [`THIRD_PARTY_NOTICES.md`](local-tts/THIRD_PARTY_NOTICES.md)

## พัฒนาและทดสอบ

ใช้ Node.js 24 และ Python environment จากขั้นติดตั้ง:

```powershell
cd extension
npm ci
npm test
npm run build
cd ..\local-tts
.\.venv\Scripts\python.exe -m pytest tests -q
```

Build ใช้ TypeScript และ esbuild สร้างไฟล์ Extension โดยตรง หลังเปลี่ยนโค้ดให้ build ใหม่แล้วกด Reload ใน Chrome ดูคำแนะนำเพิ่มเติมและการทดสอบ Chrome ในคู่มือของแต่ละโฟลเดอร์
