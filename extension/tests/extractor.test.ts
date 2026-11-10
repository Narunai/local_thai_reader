// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://og-thai.blogspot.com/2022/04/1221.html"}
import { beforeEach, describe, expect, it } from 'vitest';
import { extractFromPage } from '../src/extractor';
import { nextChapterUrl } from '../src/types';

beforeEach(() => {
  document.body.innerHTML = `<nav>เมนู</nav><h3 class="post-title">จ้าวแห่งยุทธภัณฑ์ 1,221</h3>
  <div class="post-body"><div><span>กริดเปิดประตู</span><br><span>ลอเอลกล่าวว่า <b>“ยินดีต้อนรับ”</b></span><br><br>
  <p>ราคา 1,221 บาท และ English</p><ins>โฆษณา</ins><script>อันตราย</script><div hidden>ซ่อน</div><a href="/">ตอนถัดไป</a></div></div>
  <a class="newer-link" id="Blog1_blog-pager-newer-link" href="/2022/04/1222.html">Next</a><div class="comments">ขอบคุณมาก</div>`;
});
describe('OG Thai extraction', () => {
  it('preserves inline fiction in order while excluding navigation and comments', () => {
    const result = extractFromPage();
    expect(result.title).toBe('จ้าวแห่งยุทธภัณฑ์ 1,221');
    expect(result.paragraphs).toEqual(['กริดเปิดประตู', 'ลอเอลกล่าวว่า “ยินดีต้อนรับ”', 'ราคา 1,221 บาท และ English']);
    expect(result.nextUrl).toBe('https://og-thai.blogspot.com/2022/04/1222.html');
    expect((window as any).__novelRanges).toHaveLength(3);
  });
  it('reads only a selected text range on other sites', () => {
    const text = document.querySelector('b')!.firstChild!;
    const range = document.createRange(); range.selectNodeContents(text);
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
    const result = extractFromPage(true);
    expect(result.paragraphs).toEqual(['“ยินดีต้อนรับ”']);
    expect(result.nextUrl).toBeNull();
  });
  it('rejects an empty selection', () => {
    window.getSelection()!.removeAllRanges();
    expect(() => extractFromPage(true)).toThrow('เลือกข้อความ');
  });
});
describe('chapter navigation', () => {
  const current = 'https://og-thai.blogspot.com/2022/04/1221.html';
  it('accepts the actual next link', () => expect(nextChapterUrl(current, '/2022/04/1222.html', [])).toContain('1222.html'));
  it.each([current, current + '#x', 'javascript:alert(1)', 'https://example.com/1222', 'http://og-thai.blogspot.com/1222'])('blocks unsafe or repeated link %s', candidate => {
    expect(nextChapterUrl(current, candidate, [])).toBeNull();
  });
  it('prevents a chapter loop', () => expect(nextChapterUrl(current, '/2022/04/1222.html', ['https://og-thai.blogspot.com/2022/04/1222.html'])).toBeNull());
  it('supports nekopost next chapter URLs', () => {
    expect(nextChapterUrl('https://www.nekopost.net/novel/18215/1', 'https://www.nekopost.net/novel/18215/2', [])).toBe('https://www.nekopost.net/novel/18215/2');
  });
});
