import type { Chapter } from './types';

// Chrome serializes this function. All runtime helpers MUST live inside it.
export function extractFromPage(selectionOnly = false): Chapter {
  const ranges: Range[] = [];
  const paragraphs: string[] = [];
  const selection = window.getSelection();
  const isOgThai = location.hostname === 'og-thai.blogspot.com';
  const isNekopost = location.hostname === 'www.nekopost.net' || location.hostname === 'nekopost.net';
  if (selectionOnly) {
    if (!selection || selection.isCollapsed || !selection.toString().trim()) throw new Error('เลือกข้อความในหน้าเว็บก่อน แล้วกดอ่านข้อความที่เลือก');
    const text = selection.toString().trim();
    paragraphs.push(text);
    ranges.push(selection.getRangeAt(0).cloneRange());
  } else {
    if (!isOgThai && !isNekopost) throw new Error('เว็บนี้ใช้การเลือกข้อความแล้วกด “อ่านข้อความที่เลือก”');
    const root = document.querySelector(isNekopost ? '.novel-content' : '.post-body');
    if (!root) throw new Error('ไม่พบเนื้อหานิยายในหน้านี้');
    let nodes: Text[] = [];
    const flush = () => {
      const text = nodes.map(n => n.textContent ?? '').join('').replace(/\s+/g, ' ').trim();
      if (text) {
        paragraphs.push(text);
        const range = document.createRange();
        range.setStart(nodes[0], 0);
        range.setEnd(nodes[nodes.length - 1], nodes[nodes.length - 1].length);
        ranges.push(range);
      }
      nodes = [];
    };
    const walk = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) { nodes.push(node as Text); return; }
      if (!(node instanceof Element)) return;
      if (node.matches('script,style,noscript,iframe,form,button,svg,ins,.adsbygoogle,.comments,.blog-pager,.separator,[hidden],[aria-hidden="true"]')) return;
      if (getComputedStyle(node).display === 'none' || getComputedStyle(node).visibility === 'hidden') return;
      if (node.tagName === 'A' && /^(next|previous|ตอนถัดไป|ตอนก่อนหน้า|สารบัญ|กลับ|หน้าหลัก)/i.test(node.textContent?.trim() ?? '')) return;
      const block = /^(P|DIV|SECTION|BLOCKQUOTE|LI|H[1-6])$/.test(node.tagName);
      if (node.tagName === 'BR') { flush(); return; }
      if (block) flush();
      node.childNodes.forEach(walk);
      if (block) flush();
    };
    walk(root); flush();
  }
  if (!paragraphs.length || paragraphs.join('').length > 200000) throw new Error('เนื้อหาว่างหรือยาวเกิน 200,000 ตัวอักษร');
  (window as any).__novelRanges = ranges;
  if (!(window as any).__novelStyle) {
    const style = document.createElement('style');
    style.textContent = '::highlight(novel-reading){background:#ffe09b;color:#231d15}';
    document.head.append(style);
    (window as any).__novelStyle = true;
  }
  const next = document.querySelector<HTMLAnchorElement>('#Blog1_blog-pager-newer-link, a.newer-link');
  let nextHref = next?.href ?? null;
  if (!nextHref && isNekopost) {
    const select = document.querySelector<HTMLSelectElement>('.reader-page select, select');
    if (select && select.selectedIndex > 0) {
      const nextVal = select.options[select.selectedIndex - 1]?.value;
      if (nextVal) nextHref = new URL(encodeURIComponent(nextVal), location.href).href;
    }
  }
  const titleEl = document.querySelector(isNekopost ? 'article.novel-surface h1, .reader-page h1' : '.post-title');
  return { title: titleEl?.textContent?.trim() || document.title,
    url: location.href, paragraphs, nextUrl: selectionOnly ? null : nextHref, selection: selectionOnly };
}

export function highlightParagraph(index: number, scroll: boolean, expectedUrl: string) {
  if (location.href !== expectedUrl) return;
  const css = CSS as any;
  css.highlights?.delete('novel-reading');
  const range: Range | undefined = (window as any).__novelRanges?.[index];
  if (!range || !range.startContainer.isConnected) return;
  if ((window as any).Highlight) css.highlights?.set('novel-reading', new (window as any).Highlight(range));
  if (scroll) range.startContainer.parentElement?.scrollIntoView({behavior: 'smooth', block: 'center'});
}
