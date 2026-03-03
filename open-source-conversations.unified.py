#!/usr/bin/env python3
"""
open-source-conversations v1.0.0 — Local parser and exporter for OpenAI and Anthropic conversation archives.
By ixCore.io | https://www.ixcore.io
License: MIT
Support: support@ixcore.io | Questions: cwwjacobs@ixcore.io

Parses ChatGPT and Claude JSON exports. Exports to Markdown, Plain Text, HTML, JSON, CSV.
All processing is local. No telemetry.

Usage:
  python open-source-conversations.py <export.json> [options]

Examples:
  python open-source-conversations.py chatgpt_export.json --format markdown --output ./out
  python open-source-conversations.py claude_export.json --format csv
  python open-source-conversations.py export.json --stats
  python open-source-conversations.py export.json --format json
"""

import json
import csv
import sys
import os
import re
import math
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

VERSION = "1.0.0"

# ═══════════════════════════════════════════════════════════════
#  Parser Core — ChatGPT & Claude JSON exports
# ═══════════════════════════════════════════════════════════════


def detect_provider(data):
    """Detect whether the export is from OpenAI (ChatGPT) or Anthropic (Claude)."""
    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            if "current_node" in first and "mapping" in first:
                return "openai"
            if ("messages" in first or "chat_messages" in first) and (
                "uuid" in first or "name" in first or "created_at" in first or "updated_at" in first
            ):
                return "claude"
    return None


def safe_ts(ts):
    """Convert a timestamp to ISO format safely."""
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return str(ts)
    except Exception:
        return ""


def parse_openai(data):
    """Parse a ChatGPT JSON export into normalized conversations."""
    conversations = []
    for conv in data:
        msgs = []
        mapping = conv.get("mapping", {})
        node = conv.get("current_node")
        chain = []
        visited = set()

        while node and node not in visited and len(chain) < 100000:
            visited.add(node)
            chain.append(node)
            parent = mapping.get(node, {}).get("parent")
            node = parent

        chain.reverse()

        for node_id in chain:
            entry = mapping.get(node_id, {})
            msg = entry.get("message")
            if not msg:
                continue

            content_obj = msg.get("content", {})
            if content_obj.get("content_type") != "text":
                continue

            parts = content_obj.get("parts", [])
            if not parts or not any(parts):
                continue

            role = msg.get("author", {}).get("role", "unknown")

            # Skip system messages unless explicitly user-created
            if role == "system":
                metadata = msg.get("metadata", {})
                if not metadata.get("is_user_system_message"):
                    continue

            content = "\n".join(str(p) for p in parts if p)
            author = "ChatGPT" if role == "assistant" else "User" if role == "user" else role

            msgs.append({
                "author": author,
                "role": role,
                "content": content,
                "timestamp": safe_ts(msg.get("create_time")),
            })

        conversations.append({
            "title": conv.get("title", "Untitled"),
            "provider": "openai",
            "created_at": safe_ts(conv.get("create_time")),
            "updated_at": safe_ts(conv.get("update_time")),
            "messages": msgs,
        })

    return conversations


def parse_claude(data):
    """Parse Claude JSON exports into normalized conversations.

    Supports both common shapes seen in exports:
    - conv["messages"] with message["role"] / message["content"]
    - conv["chat_messages"] with message["sender"] / message["text"] / message["content"]
    """
    conversations = []
    for conv in data:
        msgs = []
        raw_messages = conv.get("messages") or conv.get("chat_messages") or []

        for m in raw_messages:
            content = m.get("text")
            if not content:
                content = m.get("content", "")

            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                content = "\n".join(p for p in parts if p)
            elif not isinstance(content, str):
                content = str(content)

            role = m.get("role")
            if not role:
                sender = m.get("sender")
                role = "assistant" if sender == "assistant" else "user" if sender == "human" else sender or "unknown"

            author = "Claude" if role == "assistant" else "User" if role == "user" else role

            msgs.append({
                "author": author,
                "role": role,
                "content": content,
                "timestamp": m.get("created_at", ""),
            })

        conversations.append({
            "title": conv.get("name", "Untitled"),
            "provider": "claude",
            "created_at": conv.get("created_at", ""),
            "updated_at": conv.get("updated_at", ""),
            "messages": msgs,
        })

    return conversations


def parse_export(raw_text):
    """Parse a JSON export string, auto-detecting provider."""
    data = json.loads(raw_text)
    provider = detect_provider(data)

    if provider == "openai":
        return parse_openai(data)
    elif provider == "claude":
        return parse_claude(data)
    else:
        raise ValueError(
            "Unrecognized format. Supports ChatGPT & Claude JSON exports."
        )


# ═══════════════════════════════════════════════════════════════
#  Token Estimation & Code Detection (heuristic)
# ═══════════════════════════════════════════════════════════════


def estimate_tokens(text):
    """Rough GPT tokenizer estimate: ~4 chars per token."""
    return max(1, math.ceil(len(text) / 4))


def estimate_conv_tokens(conv):
    """Estimate total tokens in a conversation including overhead."""
    return sum(estimate_tokens(m.get("content", "")) + 4 for m in conv.get("messages", []))


CODE_INDICATORS = [
    re.compile(r"```[\w]*\n"),
    re.compile(r"\b(def |class |function |const |let |var |import |from |return |if \(|for \(|while \()"),
    re.compile(r"[{};]\s*\n"),
    re.compile(r"\b(print|console\.log|println|echo)\s*\("),
    re.compile(r"\b(def|fn|func|sub|proc)\s+\w+\s*\("),
    re.compile(r"(=>|->)\s*[{(]"),
    re.compile(r"^\s*(pip install|npm install|apt install|brew install|cargo add)", re.MULTILINE),
    re.compile(r"^\s*(import \w|from \w+ import|require\(|using |#include)", re.MULTILINE),
]


def has_code(text):
    """Returns True if text contains code (2+ indicator matches)."""
    hits = 0
    for pattern in CODE_INDICATORS:
        if pattern.search(text):
            hits += 1
            if hits >= 2:
                return True
    return False


def conv_has_code(conv):
    """Returns True if any message in the conversation contains code."""
    return any(has_code(m.get("content", "")) for m in conv.get("messages", []))


# ═══════════════════════════════════════════════════════════════
#  Export Formats
# ═══════════════════════════════════════════════════════════════


def to_markdown(conv):
    """Export a single conversation as Markdown."""
    lines = [
        f"# {conv['title']}",
        "",
        f"**Provider**: {conv['provider']}  ",
        f"**Messages**: {len(conv['messages'])}  ",
        "",
    ]

    for i, msg in enumerate(conv["messages"]):
        lines.append(f"## {i + 1}. {msg['author']}")
        lines.append("")
        for line in msg["content"].split("\n"):
            lines.append(f"> {line}")
        lines.append("")

    return "\n".join(lines)


def to_txt(conv):
    """Export a single conversation as plain text."""
    sep = "=" * 60
    lines = [
        sep,
        conv["title"],
        f"Provider: {conv['provider']} | Messages: {len(conv['messages'])}",
        sep,
        "",
    ]

    for msg in conv["messages"]:
        lines.append(f"[{msg['author']}]")
        lines.append(msg["content"])
        lines.append("")

    return "\n".join(lines)


def to_html_single(conv):
    """Export a single conversation as a standalone HTML page."""

    def esc(text):
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        f"<title>{esc(conv['title'])}</title>",
        "<style>",
        "body{font-family:sans-serif;max-width:800px;margin:0 auto;padding:20px;line-height:1.6;background:#0d0d12;color:#e0ded9}",
        "h1{color:#d4a853;margin-bottom:4px} .meta{font-size:12px;color:#787982;margin-bottom:20px}",
        ".msg{margin:16px 0;padding:12px;border-left:4px solid #4a9ee8;background:#0f1117;border-radius:0 6px 6px 0}",
        ".msg.user{border-left-color:#3dd68c} .author{font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.04em}",
        ".author.user{color:#3dd68c} .author.assistant{color:#d4a853}",
        ".content{margin-top:8px;white-space:pre-wrap;word-break:break-word}",
        "pre{background:#171a24;color:#c5c8d6;padding:10px;border-radius:4px;overflow-x:auto;font-family:monospace;font-size:12px}",
        "code{background:#171a24;padding:1px 4px;border-radius:3px;font-family:monospace;font-size:.9em}",
        "</style></head><body>",
        f"<h1>{esc(conv['title'])}</h1>",
        f'<div class="meta">{conv["provider"]} &middot; {len(conv["messages"])} messages</div>',
    ]

    for msg in conv["messages"]:
        cls = "user" if msg["role"] == "user" else "assistant"
        content = esc(msg["content"])
        # Basic code block rendering
        content = re.sub(
            r"```(\w*)\n([\s\S]*?)```",
            lambda m: f"<pre>{m.group(2)}</pre>",
            content,
        )
        content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
        parts.append(
            f'<div class="msg {cls}"><div class="author {cls}">{esc(msg["author"])}</div>'
            f'<div class="content">{content}</div></div>'
        )

    parts.append("</body></html>")
    return "".join(parts)


def to_json_export(convs):
    """Export conversations as normalized JSON."""
    return json.dumps(
        [
            {
                "title": c["title"],
                "provider": c["provider"],
                "created_at": c.get("created_at", ""),
                "messages": [
                    {
                        "author": m["author"],
                        "role": m["role"],
                        "content": m["content"],
                        "timestamp": m.get("timestamp", ""),
                    }
                    for m in c["messages"]
                ],
            }
            for c in convs
        ],
        indent=2,
        ensure_ascii=False,
    )


def to_csv_export(convs, filepath):
    """Export conversations as a flat CSV table."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "provider", "msg_index", "role", "content"])
        for c in convs:
            for i, m in enumerate(c["messages"]):
                writer.writerow([
                    c["title"],
                    c["provider"],
                    i + 1,
                    m["role"],
                    m["content"],
                ])


# ═══════════════════════════════════════════════════════════════
#  Stats & Reporting
# ═══════════════════════════════════════════════════════════════


def compute_stats(convs):
    """Compute aggregate statistics for a set of conversations."""
    return {
        "total": len(convs),
        "messages": sum(len(c["messages"]) for c in convs),
        "tokens": sum(estimate_conv_tokens(c) for c in convs),
        "code": sum(1 for c in convs if conv_has_code(c)),
        "providers": list({c["provider"] for c in convs}),
    }


def print_stats(convs):
    """Print a neutral parse overview to stdout."""
    stats = compute_stats(convs)

    print()
    print("=" * 56)
    print("  Open Source Conversations v1.0.0 — Parse overview")
    print("  https://www.ixcore.io")
    print("=" * 56)
    print()

    avg_msgs = (stats["messages"] / stats["total"]) if stats["total"] else 0
    print(f"  Conversations : {stats['total']}")
    print(f"  Messages      : {stats['messages']:,}")
    print(f"  Est. tokens   : {stats['tokens']:,} (~{stats['tokens'] / 1000:.0f}k)")
    print(f"  Avg msgs/conv : {avg_msgs:.1f}")
    print(f"  With code (heuristic) : {stats['code']}")
    print(f"  Sources      : {', '.join(stats['providers'])}")
    print()


def print_conversation_list(convs, limit=30):
    """Print conversation list (archival order: updated_at desc, created_at desc, title)."""
    def _sort_key(item):
        idx, c = item
        return (c.get("updated_at") or c.get("created_at") or "", c.get("title") or "")

    indexed = sorted(
        enumerate(convs),
        key=_sort_key,
        reverse=True,
    )

    print(f"\n  {'#':<4} {'Msgs':<6} {'Est.tok':<8} {'Provider':<9} {'Title'}")
    print(f"  {'—'*4} {'—'*5} {'—'*7} {'—'*8} {'—'*40}")

    for rank, (idx, conv) in enumerate(indexed[:limit], 1):
        tok = estimate_conv_tokens(conv)
        code_flag = " </>" if conv_has_code(conv) else ""
        print(
            f"  {rank:<4} {len(conv['messages']):<6} {tok/1000:.0f}k    "
            f"{conv['provider']:<9} {conv['title'][:45]}{code_flag}"
        )

    if len(indexed) > limit:
        print(f"\n  ... and {len(indexed) - limit} more (use --limit to show more)")


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        prog="open-source-conversations",
        description=(
            "Open Source Conversations v1.0.0 — Local parser and exporter for OpenAI and Anthropic conversation archives.\n"
            "Supports ChatGPT and Claude JSON exports. Exports: markdown, txt, html, json, csv.\n"
            "https://www.ixcore.io"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Export formats: markdown, txt, html, json, csv.\n"
            "Support: support@ixcore.io | Questions: cwwjacobs@ixcore.io"
        ),
    )

    parser.add_argument("input", nargs="+", help="JSON export file(s) to parse")
    parser.add_argument(
        "--format", "-f",
        choices=["markdown", "txt", "html", "json", "csv", "stats"],
        default="stats",
        help="Export format (default: stats — prints parse overview only)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./open_source_conversations_export",
        help="Output directory or file path (default: ./open_source_conversations_export)",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "claude"],
        help="Filter to a specific provider",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Only include conversations containing code",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print parse overview (always shown with --format stats)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print conversation list",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max conversations to show in --list (default: 30)",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"Open Source Conversations v{VERSION}",
    )

    args = parser.parse_args()

    # ── Parse all input files ──
    all_convs = []
    for filepath in args.input:
        path = Path(filepath)
        if not path.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            sys.exit(1)
        if not path.suffix.lower() == ".json":
            print(f"Warning: Skipping non-JSON file: {filepath}", file=sys.stderr)
            continue

        try:
            raw = path.read_text(encoding="utf-8")
            parsed = parse_export(raw)
            all_convs.extend(parsed)
            print(f"  Parsed {len(parsed)} conversations from {path.name}")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {filepath}: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"Error: {e} ({filepath})", file=sys.stderr)
            sys.exit(1)

    if not all_convs:
        print("No conversations found.", file=sys.stderr)
        sys.exit(1)

    # ── Dedup ──
    seen = set()
    deduped = []
    dupes = 0
    for c in all_convs:
        key = c["title"] + c.get("created_at", "")
        if key not in seen:
            seen.add(key)
            deduped.append(c)
        else:
            dupes += 1

    if dupes:
        print(f"  Removed {dupes} duplicate(s)")

    all_convs = deduped

    # ── Filter ──
    convs_out = list(all_convs)

    if args.provider:
        convs_out = [c for c in convs_out if c["provider"] == args.provider]

    if args.code_only:
        convs_out = [c for c in convs_out if conv_has_code(c)]

    if not convs_out:
        print("\nNo conversations match the specified filters.", file=sys.stderr)
        sys.exit(0)

    # ── Stats ──
    if args.stats or args.format == "stats" or args.list:
        print_stats(convs_out)

    if args.list or args.format == "stats":
        print_conversation_list(convs_out, args.limit)

    if args.format == "stats":
        return

    # ── Export ──
    out_path = Path(args.output)

    if args.format in ("markdown", "txt", "html"):
        # Per-file exports: create a directory
        out_path.mkdir(parents=True, exist_ok=True)
        ext_map = {"markdown": ".md", "txt": ".txt", "html": ".html"}
        fn_map = {"markdown": to_markdown, "txt": to_txt, "html": to_html_single}
        ext = ext_map[args.format]
        fn = fn_map[args.format]

        for i, conv in enumerate(convs_out):
            safe_title = re.sub(r'[^\w\s-]', '', conv["title"])[:60].strip() or f"conv_{i}"
            safe_title = re.sub(r'\s+', '_', safe_title)
            filepath = out_path / f"{safe_title}{ext}"

            # Avoid overwrites
            counter = 1
            while filepath.exists():
                filepath = out_path / f"{safe_title}_{counter}{ext}"
                counter += 1

            filepath.write_text(fn(conv), encoding="utf-8")

        print(f"\n  Exported {len(convs_out)} conversations to {out_path}/ ({args.format})")

    elif args.format == "json":
        if out_path.suffix != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(to_json_export(convs_out), encoding="utf-8")
        print(f"\n  Exported {len(convs_out)} conversations to {out_path}")

    elif args.format == "csv":
        if out_path.suffix != ".csv":
            out_path = out_path.with_suffix(".csv")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        to_csv_export(convs_out, str(out_path))
        print(f"\n  Exported {len(convs_out)} conversations to {out_path}")

    print()


if __name__ == "__main__":
    main()
