# Third-Party Notices

StudyLoop is MIT licensed (see `LICENSE`). This file records third-party work that
influenced or is included in it, and the terms that work carries.

---

## Matt Pocock — `skills`

**Source:** <https://github.com/mattpocock/skills>
**Licence:** MIT — Copyright (c) 2026 Matt Pocock

### What StudyLoop takes

The **study-plan document shape** is adapted from the `teach` skill
(<https://github.com/mattpocock/skills/tree/main/skills/productivity/teach>).
Three of its ideas shaped StudyLoop's `planning` package:

- **Mission first** — a plan opens with why the learner is doing this, and every
  milestone is justified against that mission rather than against a syllabus.
- **Learning records as ADRs** — what was learned is captured as a dated,
  append-only record with the reasoning attached, in the spirit of an
  architecture decision record, so a plan carries its own history.
- **Primary sources over recalled knowledge** — a plan cites the material it is
  built on and revisits it, rather than trusting what the agent remembers.

StudyLoop diverges deliberately: `teach` uses a multi-file workspace, whereas
StudyLoop collapses a plan into a single Markdown document so it renders as one
page in the web UI and stays diffable in git.

Inline credit also appears at the point of use, in
`agents/shared/study-plan-protocol.md`, `docs/study-plans.md`,
`packages/studyloop/src/studyloop/planning/__init__.py` and
`packages/studyloop/src/studyloop/planning/models.py`.

### What StudyLoop does not take

**No code and no text.** The borrowing above is conceptual — the ideas and the
document shape, independently implemented. This was verified rather than assumed:
an 8-word phrase comparison across 675 StudyLoop files against the `teach`,
`grilling`, `wait-what` and `loop-me` skills found no verbatim overlap in any of
them.

Because no copy or substantial portion of the original is present, MIT's notice
requirement is not triggered by the current state of this repository. This file
exists anyway, for two reasons: attribution for borrowed ideas is right whether or
not a licence compels it, and if any of that material is later adopted verbatim,
the notice it requires is already here rather than being remembered afterwards.

### Licence text

Reproduced so that the terms travel with this repository:

```
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Vendored web assets

`packages/studyloop/src/studyloop/web/static/vendor/` ships 26 third-party
files with no build step: four accessible/dyslexia-friendly font families
(SIL OFL) and eight JavaScript libraries (MIT, BSD, or Apache-2.0/MPL-2.0).
The exact file list, upstream URL, version, and a sha256 per file are checked
by `packages/studyloop/tests/test_vendor_manifest.py` against
`vendor/MANIFEST` (R-75) — this section is the licence record; that file and
test are the provenance record.

### Fonts (four families, SIL Open Font License 1.1)

All four ship under the identical SIL OFL 1.1 text, reproduced once below.
Per-family copyright line (each vendored as one or more `.woff`/`.woff2`
files plus a `.css` `@font-face` sheet under `vendor/css/`):

| Family | Copyright |
|---|---|
| Atkinson Hyperlegible | Copyright 2020 Braille Institute of America, Inc. |
| Inter | Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter) |
| Lexend | Copyright 2018 The Lexend Project Authors (https://github.com/googlefonts/lexend) |
| OpenDyslexic | Copyright (c) 2012–2019 Abbie Gonzalez (https://abbiecod.es), Reserved Font Name "OpenDyslexic" |

<details>
<summary>SIL Open Font License, Version 1.1 (26 February 2007) — full text</summary>

```
-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

</details>

### JavaScript libraries (eight, vendored under `vendor/js/`)

| Library | Version | Licence | Copyright |
|---|---|---|---|
| Alpine.js | 3.14.8 | MIT | Copyright © 2019–2025 Caleb Porzio and contributors |
| htmx (core + `htmx-ext-sse`) | 2.0.4 / 2.2.2 | Zero-Clause BSD (0BSD) | bigskysoftware — no copyright-holder line in the licence text itself, per 0BSD's own form. The `htmx-ext-sse` extension ships from the sibling `bigskysoftware/htmx-extensions` repo, which carries no separate `LICENSE` file; it is treated as the same 0BSD terms as its parent project. |
| marked | 12.0.0 | MIT | Copyright (c) 2018+ MarkedJS; Copyright (c) 2011-2018 Christopher Jeffrey |
| DOMPurify | 3.1.0 | Apache-2.0 OR MPL-2.0 (recipient's choice) | Copyright 2024 Dr.-Ing. Mario Heiderich, Cure53 |
| highlight.js | 11.9.0 | BSD-3-Clause | Copyright (c) 2006 Ivan Sagalaev |
| mermaid | 11.4.1 | MIT | Copyright (c) 2014-2022 Knut Sveidqvist |
| Fuse.js | 7.0.0 | Apache-2.0 | Kiro Risk (Fuse.js author) |
| xterm.js (core + `xterm-addon-fit`, `xterm-addon-webgl`, `xterm-addon-clipboard`) | 6.0.0 / 0.11.0 / 0.19.0 / 0.2.0 | MIT | Copyright (c) 2017-2019 The xterm.js authors; Copyright (c) 2014-2016 SourceLair Private Company; Copyright (c) 2012-2013 Christopher Jeffrey. The three addons ship from the same `xtermjs/xterm.js` monorepo and carry the same licence and copyright holders; upstream does not tag them independently, so their versions here are the vendored files' own version strings, not independently confirmed git tags (see `vendor/MANIFEST` for the sha256 that pins what is actually shipped). |

<details>
<summary>MIT License — full text (applies to Alpine.js, marked, mermaid, xterm.js + addons; each with the copyright line from the table above substituted in)</summary>

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

</details>

<details>
<summary>Zero-Clause BSD (0BSD) — full text (htmx, htmx-ext-sse)</summary>

```
Permission to use, copy, modify, and/or distribute this software for
any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

</details>

<details>
<summary>BSD 3-Clause License — full text (highlight.js)</summary>

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

</details>

DOMPurify (Apache-2.0 OR MPL-2.0) and Fuse.js (Apache-2.0) are not reproduced
in full here — both licences run several hundred lines and are standard,
widely published texts. Apache-2.0: <https://www.apache.org/licenses/LICENSE-2.0>.
MPL-2.0: <https://www.mozilla.org/en-US/MPL/2.0/>. Both are permissive and
neither has a "same license" propagation requirement that reaches
StudyLoop's own MIT-licensed code.

---

## Maintaining this file

Add an entry whenever third-party work is adopted, including when only an idea is
borrowed. If material is taken verbatim, reproduce its licence text as above and
say which files contain it — the point of this file is that someone can answer
"what is in here that isn't ours?" without reading the whole repository.
