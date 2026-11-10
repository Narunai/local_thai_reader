export const API = 'http://127.0.0.1:8765';
export async function request<T>(token: string, path: string, options: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  if (!token) throw new Error('กรอก Token จากไฟล์ local-tts/.token ในการตั้งค่าก่อน');
  let response: Response;
  try {
    response = await fetch(API + path, { ...options, signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs), headers: {
      Authorization: `Bearer ${token}`, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers
    } });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw Object.assign(new Error('เชื่อมต่อระบบเสียงไม่ได้ · เปิด local-tts/start.ps1 แล้วลองอีกครั้ง'), {transient:true});
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = response.status === 401 ? 'Token ไม่ถูกต้อง · คัดลอกจาก local-tts/.token อีกครั้ง' : path.startsWith('/gemini') && response.status === 404 ? 'Server ยังเป็นรุ่นเก่า · หยุดแล้วรัน local-tts/start.ps1 ใหม่เพื่อใช้ Gemini' : typeof body.detail === 'string' ? body.detail : `ระบบเสียงตอบกลับ ${response.status}`;
    throw Object.assign(new Error(message), {status: response.status});
  }
  return response.json();
}
export async function audioBlob(token: string, path: string, signal: AbortSignal): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(API + path, { headers: {Authorization: `Bearer ${token}`}, signal:AbortSignal.any([signal,AbortSignal.timeout(20000)]) });
  } catch(error) {
    if((error as Error).name==='AbortError') throw error;
    throw Object.assign(new Error('เชื่อมต่อระบบเสียงไม่ได้ · เปิด local-tts/start.ps1 แล้วลองอีกครั้ง'), {transient:true});
  }
  if (!response.ok) throw new Error(`โหลดเสียงไม่สำเร็จ (${response.status})`);
  return response.blob();
}
