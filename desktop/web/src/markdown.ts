import { marked } from 'marked';
import DOMPurify from 'dompurify';

export const renderMarkdown = (target: HTMLElement, source: string) => {
  // Model layout markers are metadata, never HTML or visible document content.
  const text = source.replace(/<\|det\|>[\s\S]*?(?:<\|\/det\|>|$)/g, '')
    .replace(/<\|[^>]*\|>/g, '');
  const html = marked.parse(text, {async: false, gfm: true, breaks: false});
  const fragment = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p','br','h1','h2','h3','h4','h5','h6','strong','em','del','blockquote',
      'ul','ol','li','pre','code','hr','table','thead','tbody','tr','th','td','span','sup','sub'],
    ALLOWED_ATTR: [], ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false, RETURN_DOM_FRAGMENT: true,
  });
  target.replaceChildren(fragment);
};
