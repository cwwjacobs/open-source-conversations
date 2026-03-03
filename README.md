# Open Source Conversations

A local parser and exporter for ChatGPT and Claude JSON conversation archives.

## What this repo is

Open Source Conversations provides two aligned surfaces over the same normalized conversation model:

- **Browser app** - open `open-source-conversations.html`, drop one or more JSON exports, review the parsed conversations, then export.
- **CLI** - run `open-source-conversations.py` on one or more JSON exports to print stats, list conversations, or write exports.

Both surfaces are meant to support the same providers, the same normalized fields, and the same export formats. The browser parses locally in the page; the CLI runs and writes locally on your machine.

## Supported inputs

### OpenAI / ChatGPT
- JSON exports with `current_node` and `mapping`

### Anthropic / Claude
- JSON exports using `messages` with `role` / `content`
- JSON exports using `chat_messages` with `sender` / `text` / `content`

Claude support is intended to cover both common shapes above so the browser and CLI stay in sync.

## Normalized conversation shape

Each parsed conversation is normalized to:

- `title`
- `provider`
- `created_at`
- `updated_at`
- `messages[]`
  - `author`
  - `role`
  - `content`
  - `timestamp`

## Export formats

Implemented in both browser and CLI:

- Markdown
- Plain text
- HTML
- JSON
- CSV

## Quick start

### Browser
1. Open `open-source-conversations.html` in a browser.
2. Drop your ChatGPT or Claude JSON export(s) on the page, or click to browse.
3. Review the parse overview and conversation list.
4. Choose an export format and download it.

### CLI
```bash
python open-source-conversations.py input.json
```

That prints a parse overview.

Export examples:

```bash
python open-source-conversations.py input.json --format markdown --output ./out
python open-source-conversations.py input.json --format json --output export.json
python open-source-conversations.py input.json --format csv --output export.csv
```

Useful flags:

- `--format markdown|txt|html|json|csv|stats`
- `--list`
- `--provider openai|claude`
- `--code-only`
- `--limit N`

## What it does

- Parses ChatGPT and Claude JSON conversation exports.
- Normalizes them into a shared conversation/message structure.
- Deduplicates conversations by title + created date.
- Shows a neutral parse overview: conversation count, message count, estimated tokens, sources, and a heuristic "with code" count.
- Lists conversations in archival order: updated date descending, then created date, then title.
- Exports the normalized result to Markdown, plain text, HTML, JSON, or CSV.

## What it does not do

- It does not score, rank, or tier conversations.
- It does not send parsed conversation content to a server.
- It does not emit training formats such as JSONL, Alpaca, or ShareGPT.
- It does not do labeling, red-teaming, or fine-tune packaging.

## Privacy and runtime notes

- The browser app parses files locally in the page.
- The CLI runs locally and writes files locally.
- The browser file does not require a remote script or font CDN by default.
- Links in the UI footer are normal user-click links, not background telemetry.

## License

MIT. See `LICENSE.txt`.

## Contact

Questions: cwwjacobs@ixcore.io  
Support: support@ixcore.io  
https://www.ixcore.io
