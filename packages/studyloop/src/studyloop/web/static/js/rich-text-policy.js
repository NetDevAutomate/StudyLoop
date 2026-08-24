/** Shared no-subresource-egress policy for Markdown and Mermaid output. */

export const RICH_TEXT_FORBID_TAGS = Object.freeze([
  'script',
  'iframe',
  'object',
  'embed',
  'form',
  'img',
  'image',
  'video',
  'audio',
  'source',
  'track',
  'link',
  'meta',
  'base',
  'use',
  'foreignObject',
]);

export const RICH_TEXT_FORBID_ATTRS = Object.freeze([
  'src',
  'srcset',
  'poster',
  'background',
  'data',
  'action',
  'formaction',
  'ping',
  'xlink:href',
]);

const EVENT_ATTRIBUTE = /^on/i;
const CSS_URL = /url\(\s*(['"]?)(.*?)\1\s*\)/gi;
const CSS_IMPORT = /@import\b/i;
const SAFE_HTTP = /^https?:\/\//i;
const UNSAFE_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

export const domPurifyOptions = Object.freeze({
  FORBID_TAGS: [...RICH_TEXT_FORBID_TAGS, 'style'],
  FORBID_ATTR: [...RICH_TEXT_FORBID_ATTRS],
  ALLOW_DATA_ATTR: false,
});

export const mermaidDomPurifyOptions = Object.freeze({
  FORBID_TAGS: [...RICH_TEXT_FORBID_TAGS],
  FORBID_ATTR: [...RICH_TEXT_FORBID_ATTRS],
  ALLOW_DATA_ATTR: false,
  USE_PROFILES: { svg: true, svgFilters: true },
});

export function isSafeCitationHref(value) {
  const href = String(value || '').trim();
  if (!href) return false;
  if (href.startsWith('//')) return false;
  if (SAFE_HTTP.test(href)) return true;
  if (UNSAFE_SCHEME.test(href)) return false;
  return href.startsWith('/') || href.startsWith('#') || href.startsWith('./') || href.startsWith('../');
}

/** Keep Mermaid's local marker references while rejecting network CSS. */
export function sanitizeCssValue(value) {
  const css = String(value || '');
  if (CSS_IMPORT.test(css)) return '';
  let unsafe = false;
  css.replace(CSS_URL, (_match, _quote, target) => {
    if (!String(target || '').trim().startsWith('#')) unsafe = true;
    return _match;
  });
  return unsafe ? '' : css;
}

function forbiddenSelector() {
  return RICH_TEXT_FORBID_TAGS.map((tag) => tag.replace(/[A-Z]/g, (c) => `\\${c}`)).join(',');
}

/**
 * Structural pass run while the DOM is detached. It is intentionally shared by
 * marked output and generated Mermaid SVG so neither path can drift weaker.
 */
export function hardenRichTextTree(root, options = {}) {
  if (!root?.querySelectorAll) return root;
  root.querySelectorAll(forbiddenSelector()).forEach((element) => element.remove());

  for (const element of root.querySelectorAll('*')) {
    const name = String(element.localName || '').toLowerCase();
    if (name === 'style') {
      if (!options.allowSvgStyle) {
        element.remove();
      } else {
        const safe = sanitizeCssValue(element.textContent || '');
        if (safe) element.textContent = safe;
        else element.remove();
      }
      continue;
    }

    for (const attribute of Array.from(element.attributes || [])) {
      const attr = String(attribute.name || '').toLowerCase();
      const value = String(attribute.value || '');
      if (EVENT_ATTRIBUTE.test(attr) || RICH_TEXT_FORBID_ATTRS.includes(attr)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (attr === 'href') {
        if (name !== 'a' || !isSafeCitationHref(value)) {
          element.removeAttribute(attribute.name);
        }
        continue;
      }
      if (attr === 'style' || /url\s*\(/i.test(value) || CSS_IMPORT.test(value)) {
        const safe = sanitizeCssValue(value);
        if (safe) element.setAttribute(attribute.name, safe);
        else element.removeAttribute(attribute.name);
      }
    }

    if (name === 'a' && element.getAttribute('href')) {
      element.setAttribute('target', '_blank');
      element.setAttribute('rel', 'noopener noreferrer');
      element.removeAttribute('download');
    }
  }
  return root;
}
