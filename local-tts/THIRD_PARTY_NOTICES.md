# โมเดลและส่วนประกอบภายนอก

ตรวจสอบจากแหล่งต้นฉบับวันที่ 9 พฤศจิกายน 2026 โมเดลใช้ส่วนตัวบนเครื่องนี้ ดาวน์โหลดแยกจากโค้ด Extension และบันทึก revision + SHA-256 ใน `models/<profile>/manifest.json`

| ส่วนประกอบ | แหล่งต้นฉบับ | เงื่อนไขที่ผู้เผยแพร่ระบุ |
|---|---|---|
| VachanaTTS weights | https://huggingface.co/VIZINTZOR/VachanaTTS | MIT ใน Model Card |
| VachanaTTS Python | https://github.com/VYNCX/VachanaTTS2 | เก็บ notice ของแพ็กเกจที่ติดตั้งไว้; มีโค้ด Piper และ Thai G2P ที่ upstream อ้างถึง |
| Thonburian weights | https://huggingface.co/biodatlab/ThonburianTTS | CC BY-NC-SA 4.0 |
| Thonburian inference code | https://github.com/biodatlab/thonburian-tts | MIT; LICENSE-MIT อยู่ใน vendor checkout |
| OpenJaiTTS-v1.0 weights | https://huggingface.co/JTS-AI/OpenJaiTTS-v1.0 | CC BY-NC 4.0; ต้องได้รับสิทธิ์และเข้าสู่ระบบก่อนดาวน์โหลด |
| F5-TTS code | https://github.com/SWivid/F5-TTS | MIT |
| Vocos | https://huggingface.co/charactr/vocos-mel-24khz | MIT |

เสียงอ้างอิงเริ่มต้นของโปรเจกต์สร้างในเครื่องจาก `VachanaTTS th_f_1` และข้อความที่แต่งสำหรับการทดสอบ เก็บคำถอดเสียง แหล่งที่มา และคำอธิบายใน `voices/reference.json` จึงไม่มีการนำเสียงบุคคลอื่นจากภายนอกเข้ามา โมเดล F5 อาจถ่ายทอดข้อจำกัดของเสียงสังเคราะห์ต้นแบบ ต้องฟังเทียบก่อนเลือกใช้

คะแนนและผลทดสอบของ JaiTTS-v1.0 ในงานวิจัยไม่ใช่ผลของ OpenJaiTTS-v1.0 และไม่ถูกนำมาใช้เป็นผลทดสอบในโปรเจกต์นี้
# OmniVoice

- Source: https://github.com/k2-fsa/OmniVoice, pinned commit `08be0b4ccbac3e13e374e86fbfead4b4cac343e2`, Apache-2.0 code.
- Weights: https://huggingface.co/k2-fsa/OmniVoice, revision `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`, model card states CC-BY-NC. Retain attribution; noncommercial personal use in this project.
- Bundled Higgs audio tokenizer notice is downloaded at `models/omnivoice/audio_tokenizer/LICENSE` with its README.
- Reference audio: existing locally synthesized Vachana `th_f_1`, described in `voices/reference.json`. No human narrator recording was imported for this integration.
