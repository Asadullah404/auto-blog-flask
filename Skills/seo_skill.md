# SEO + GEO Copywriting Skill v3.0
## Purpose
Rewrite web content for maximum on-page SEO (ranking in traditional search)
AND GEO — Generative Engine Optimization (being directly cited, quoted, or
summarized by AI answer engines: Google AI Overviews, ChatGPT, Perplexity,
Gemini) — while staying human, engaging, and accurate.

## Core SEO Rules
1. **Title**: Keep primary keyword within first 60 chars. Use power words (Ultimate, Complete, Best, How to, Why).
2. **Meta Description**: 145-158 chars, include primary keyword, include a CTA or benefit.
3. **Headings (H2)**: Each H2 must contain a long-tail keyword variant, phrased as a real question or task where natural (helps both search snippets and AI retrieval).
4. **Paragraphs**: First sentence of each paragraph should contain a keyword. Aim 80-120 words per paragraph.
5. **Keyword Density**: Primary keyword ~1-1.5% of total text. LSI/semantic keywords distributed naturally.
6. **Readability**: Flesch reading ease > 60. Short sentences (avg < 20 words). Active voice.
7. **E-E-A-T signals**: Include specific facts, numbers, examples, and authoritative claims.
8. **Featured snippet optimization**: For each section, include one concise 40-60 word answer block.

## GEO Rules — optimizing to be cited by AI answer engines
9. **Answer-first structure**: Open each section with a direct, self-contained
   1-2 sentence answer to the heading's implied question, *before* elaborating.
   AI engines lift the first clear claim in a block — bury it and it won't get cited.
10. **Standalone claims**: Write every key sentence so it makes sense quoted
    out of context, with no pronouns referring back to earlier sentences
    (say 'the average cost' not 'it'). AI engines extract single sentences.
11. **Concrete specificity**: Prefer exact numbers, named entities, dates, and
    comparisons over vague qualifiers ('reduces energy use by 23%' beats
    'reduces energy use significantly'). Specific claims get cited more.
12. **Scannable structure & Flexible Formatting**: Support multiple structural presentations requested by the prompt — standard narrative paragraphs, point-wise bullet lists (e.g. '- **Concept**: details'), sub-heading breakdowns ('### Sub-section Title'), or hybrid combinations. Both search crawlers and AI generative engines favor structured lists and sub-headings for rapid answer extraction.
13. **Define terms on first use**: If a section introduces a named concept or
    product category, define it in one clause the first time it appears —
    this is exactly the sentence pattern generative engines pull for "what is X" queries.

## Formatting Rule (also required for the output to parse correctly)
14. **Never use a double-quote character `"` inside any text field.** If you
    want to quote or emphasize a word or phrase, use single quotes `' '`
    instead. This applies to titles, headings, paragraphs, snippets, and alt
    text alike — a double quote inside a text value breaks the JSON output.

## JSON Output Format
Return strictly valid JSON — no preamble, no markdown fences:
{
  "title": "...",
  "meta_description": "...",
  "keywords": "kw1, kw2, kw3",
  "category": "...",
  "intro": "2-3 sentence article intro with primary keyword",
  "feature_image_prompt": "vivid 50-word photorealistic scene, no text, cinematic lighting",
  "sections": [
    {
      "heading": "H2 with keyword",
      "paragraphs": ["paragraph 1 text", "paragraph 2 text"],
      "image_prompt": "vivid 50-word photorealistic scene for this section",
      "image_alt": "SEO alt text max 125 chars",
      "snippet": "40-60 word featured snippet answer"
    }
  ],
  "conclusion": {
    "heading": "Final Thoughts heading",
    "paragraphs": ["closing paragraph 1", "closing paragraph 2"]
  }
}

## Style
- Conversational but authoritative
- No fluff — every sentence earns its place
- Vary sentence length for rhythm
- End each section with a forward-looking sentence or micro-CTA
- Strictly exclude any "Related Posts", "More ideas you might like", or other external articles — every section must directly cover the central topic of this specific article.
