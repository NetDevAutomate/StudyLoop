/** Pure policy tests for Markdown and Mermaid zero-subresource egress. */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  RICH_TEXT_FORBID_ATTRS,
  RICH_TEXT_FORBID_TAGS,
  hardenRichTextTree,
  isSafeCitationHref,
  sanitizeCssValue,
} from '../../src/studyloop/web/static/js/rich-text-policy.js';

const FETCH_TAGS = [
  'img',
  'image',
  'video',
  'audio',
  'source',
  'track',
  'iframe',
  'object',
  'embed',
  'link',
  'meta',
  'base',
  'use',
  'foreignObject',
];

const URL_ATTRS = [
  'src',
  'srcset',
  'poster',
  'background',
  'data',
  'action',
  'formaction',
  'ping',
  'xlink:href',
];

test('pre-insertion policy forbids every automatic-fetch element and attribute', () => {
  for (const tag of FETCH_TAGS) {
    assert.ok(RICH_TEXT_FORBID_TAGS.includes(tag), `missing forbidden tag ${tag}`);
  }
  for (const attr of URL_ATTRS) {
    assert.ok(RICH_TEXT_FORBID_ATTRS.includes(attr), `missing forbidden attr ${attr}`);
  }
});

test('citation href permits deliberate navigation but refuses active/local schemes', () => {
  assert.equal(isSafeCitationHref('https://example.com/course'), true);
  assert.equal(isSafeCitationHref('http://example.com/course'), true);
  assert.equal(isSafeCitationHref('/docs/course'), true);
  assert.equal(isSafeCitationHref('#checkpoint'), true);
  for (const href of [
    'javascript:alert(1)',
    'data:text/html,hello',
    'file:///etc/passwd',
    'blob:https://example.com/id',
    '//attacker.example/path',
  ]) {
    assert.equal(isSafeCitationHref(href), false, href);
  }
});

test('CSS policy removes external url and import but preserves fragment geometry', () => {
  assert.equal(sanitizeCssValue('fill: url(#marker); stroke: #fff'), 'fill: url(#marker); stroke: #fff');
  assert.equal(sanitizeCssValue('background:url(https://evil.invalid/a.png)'), '');
  assert.equal(sanitizeCssValue("@import 'https://evil.invalid/a.css'; color:red"), '');
  assert.equal(sanitizeCssValue('filter:url(//evil.invalid/filter.svg#x)'), '');
});

test('tree hardening removes fetch attributes and hardens the one click-only anchor', () => {
  const anchor = fakeElement('a', {
    href: 'https://example.com/citation',
    ping: 'https://evil.invalid/ping',
    style: 'color: red',
  });
  const svgPath = fakeElement('path', {
    fill: 'url(https://evil.invalid/paint.svg#x)',
    'marker-end': 'url(#arrow)',
  });
  const root = {
    querySelectorAll(selector) {
      if (selector === '*') return [anchor, svgPath];
      return [];
    },
  };

  hardenRichTextTree(root);

  assert.equal(anchor.getAttribute('href'), 'https://example.com/citation');
  assert.equal(anchor.getAttribute('ping'), null);
  assert.equal(anchor.getAttribute('target'), '_blank');
  assert.equal(anchor.getAttribute('rel'), 'noopener noreferrer');
  assert.equal(svgPath.getAttribute('fill'), null);
  assert.equal(svgPath.getAttribute('marker-end'), 'url(#arrow)');
});

test('the shared Markdown and Mermaid render paths invoke the same policy', () => {
  const source = readFileSync(
    new URL('../../src/studyloop/web/static/components.js', import.meta.url),
    'utf8'
  );
  assert.match(source, /StudyLoopRichTextPolicy\.domPurifyOptions/);
  assert.match(source, /StudyLoopRichTextPolicy\.hardenRichTextTree/);
  assert.match(source, /_sanitizeMermaidSvg/);
});

function fakeElement(localName, initial) {
  const values = new Map(Object.entries(initial));
  return {
    localName,
    get attributes() {
      return [...values].map(([name, value]) => ({ name, value }));
    },
    getAttribute(name) {
      return values.has(name) ? values.get(name) : null;
    },
    setAttribute(name, value) {
      values.set(name, String(value));
    },
    removeAttribute(name) {
      values.delete(name);
    },
    remove() {
      values.clear();
    },
  };
}
