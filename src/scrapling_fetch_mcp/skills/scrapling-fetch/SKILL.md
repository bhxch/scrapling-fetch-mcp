---
name: scrapling-fetch
description: Fetching workflows for the scrapling-fetch-mcp server — search-result harvesting, paginated reading of long pages, format/mode selection, and known site limitations. Use when a task needs web content via the s_fetch_page or s_fetch_pattern tools.
---

# Scrapling Fetch Workflows

How to use the `s_fetch_page` and `s_fetch_pattern` tools effectively.

## Tool selection

- `s_fetch_page`: read a whole page (paginated). Default choice for reading.
- `s_fetch_pattern`: extract regex-matched fragments. Use it to locate specific
  data in a large page, then re-fetch with `start_index` around the match
  positions. Note: `s_fetch_pattern` does NOT support `format="airead"`
  (airead is converted to markdown).

## Search workflow (the main pattern)

1. Fetch a search-engine results page with `format="airead"`, e.g.
   `s_fetch_page(url="https://www.bing.com/search?q=YOUR_QUERY", format="airead")`.
   Works for bing.com, duckduckgo.com, google.com (stealth mode), startpage,
   brave, searx instances.
2. The airead output contains `## Search Results` with `### N. <title>` blocks,
   each ending with `[查看原文](<real-url>)` — the link is already resolved to
   the real destination (Bing `ck/a` base64 and Google `/goto` tokens are
   decoded server-side).
3. Pick URLs from those blocks and fetch each with `s_fetch_page` as usual.
4. Do NOT hand-construct lightweight URLs (`html.duckduckgo.com`,
   `stackprinter.com`, `old.reddit.com`) — the server rewrites known sites
   automatically. Pass the original URL.

## Paginated reading

- The tool reply starts with `METADATA: {json}` on its own line. Check
  `is_truncated`.
- To continue reading: `start_index = start_index + max_length`, keep
  `max_length` unchanged. Repeat until `is_truncated` is false.
- `total_length` tells you how much is left; for long pages prefer scanning a
  pattern with `s_fetch_pattern` first.

## Format and mode decisions

- `format="airead"` by default: content-extraction per site type, big token
  savings. Use `format="markdown"` when you need the full document structure;
  `format="html"` only to debug page structure.
- `mode="basic"` first (fast). If you get a challenge page, 403, 202, or an
  empty shell, retry once with `mode="stealth"`. Only use `mode="max-stealth"`
  for the strongest anti-bot sites.

## Known limitations

- Some sites block plain HTTP clients: zhihu.com (login wall), juejin.cn
  (SPA, empty shell), reddit.com (often an empty shell), DuckDuckGo/Bing under
  heavy request bursts (202 challenge pages). These usually need stealth mode
  or are simply unavailable.
- Consecutive requests to the same search engine can trip rate limits — space
  them out; a 202/17-character "## Search Results" reply means you were
  challenged, back off and retry later.
- The server may return `METADATA` saying `is_truncated: true` — that is
  normal pagination, not an error.
