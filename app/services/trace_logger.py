"""Dashboard trace logging for Telegram request flows."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class TraceLogger:
    """Task: Persist request-flow events and render them for the dashboard page.
    Input: A filesystem path where JSONL trace events should be written and later read from.
    Output: Trace ids, append-only event logs, grouped trace views, and dashboard HTML.
    Failures: File read or write errors can raise OSError or JSON decode issues, which are handled best-effort where possible.
    """

    def __init__(self, log_path: Path) -> None:
        """Task: Initialize the trace logger with a JSONL log file path.
        Input: The filesystem path where request trace events should be stored.
        Output: A ready-to-use TraceLogger instance.
        Failures: No failure is expected during construction.
        """

        self.log_path = log_path

    def ensure_store_exists(self) -> None:
        """Task: Create the log directory and JSONL file if they do not already exist.
        Input: No direct arguments.
        Output: The on-disk trace log location exists and is writable.
        Failures: Raises OSError if the directory or file cannot be created.
        """

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.touch(exist_ok=True)

    def new_trace_id(self) -> str:
        """Task: Produce a unique trace id for one Telegram request flow.
        Input: No direct arguments.
        Output: A UUID-based trace identifier string.
        Failures: No failure is expected.
        """

        return uuid4().hex

    def log_event(
        self,
        trace_id: str,
        level: str,
        agent: str,
        message: str,
        user_id: int | None = None,
        chat_id: int | None = None,
        telegram_text: str | None = None,
        agent_input: Any | None = None,
        agent_output: Any | None = None,
        error: str | None = None,
    ) -> None:
        """Task: Append a single structured event to the trace log.
        Input: Trace metadata plus optional input, output, and error payloads for one processing step.
        Output: A JSONL event appended to the trace log file.
        Failures: Raises OSError if the log file cannot be written.
        """

        self.ensure_store_exists()
        event = {
            "trace_id": trace_id,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "level": level,
            "agent": agent,
            "message": message,
            "user_id": user_id,
            "chat_id": chat_id,
            "telegram_text": telegram_text,
            "agent_input": agent_input,
            "agent_output": agent_output,
            "error": error,
        }
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_recent_traces(self, limit: int = 25) -> list[dict[str, Any]]:
        """Task: Load recent trace events and group them into request-centric records for the dashboard.
        Input: The maximum number of most recent traces to return.
        Output: A list of grouped trace dictionaries sorted from newest to oldest.
        Failures: Malformed JSON lines are skipped so one bad record does not break the dashboard.
        """

        self.ensure_store_exists()
        grouped_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        with self.log_path.open("r", encoding="utf-8") as log_file:
            for raw_line in log_file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                grouped_events[event["trace_id"]].append(event)

        traces: list[dict[str, Any]] = []
        for trace_id, events in grouped_events.items():
            ordered_events = sorted(events, key=lambda event: event["timestamp"])
            first_event = ordered_events[0]
            last_event = ordered_events[-1]
            status = "error" if any(event.get("level") == "error" for event in ordered_events) else "ok"
            final_output = ""
            for event in reversed(ordered_events):
                if event.get("agent_output"):
                    final_output = self._stringify_payload(event["agent_output"])
                    break
            traces.append(
                {
                    "trace_id": trace_id,
                    "started_at": first_event["timestamp"],
                    "status": status,
                    "user_id": first_event.get("user_id"),
                    "chat_id": first_event.get("chat_id"),
                    "telegram_text": first_event.get("telegram_text") or "",
                    "final_output": final_output,
                    "events": ordered_events,
                    "updated_at": last_event["timestamp"],
                }
            )

        traces.sort(key=lambda trace: trace["updated_at"], reverse=True)
        return traces[:limit]

    def render_dashboard_html(self, limit: int = 25) -> str:
        """Task: Render recent traces as a simple standalone HTML dashboard.
        Input: The maximum number of traces to include in the rendered page.
        Output: A full HTML document string for the `/dashboard` endpoint.
        Failures: No failure is expected unless trace loading itself raises filesystem errors.
        """

        traces = self.read_recent_traces(limit=limit)
        trace_cards = "\n".join(self._render_trace_card(trace) for trace in traces) or "<p>No traces yet.</p>"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>myPlant Dashboard</title>
  <style>
    body {{
      font-family: Georgia, 'Times New Roman', serif;
      margin: 0;
      background: linear-gradient(180deg, #f2f7ef 0%, #f9fbf7 100%);
      color: #1e2b20;
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2.2rem;
    }}
    .sub {{
      color: #506055;
      margin-bottom: 28px;
    }}
    .trace {{
      background: #ffffff;
      border: 1px solid #dbe6d6;
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 12px 30px rgba(41, 74, 43, 0.06);
    }}
    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      color: #55645b;
      font-size: 0.95rem;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.85rem;
      background: #edf5e7;
      color: #2a5b33;
    }}
    .badge.error {{
      background: #fdeceb;
      color: #9f2f28;
    }}
    .text-block {{
      background: #f7faf5;
      border-radius: 12px;
      padding: 12px 14px;
      margin: 10px 0 14px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 0.95rem;
    }}
    th, td {{
      border-top: 1px solid #e6eee1;
      vertical-align: top;
      text-align: left;
      padding: 10px 8px;
    }}
    th {{
      color: #516258;
      font-weight: 600;
    }}
    .level-info {{
      color: #2d5d35;
      font-weight: 600;
    }}
    .level-error {{
      color: #a2322b;
      font-weight: 600;
    }}
    code {{
      font-family: Menlo, Monaco, monospace;
      font-size: 0.9rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>myPlant Dashboard</h1>
    <p class="sub">Telegram request traces from incoming user text all the way to the final reply.</p>
    {trace_cards}
  </div>
</body>
</html>"""

    def _render_trace_card(self, trace: dict[str, Any]) -> str:
        """Task: Render one grouped trace as an HTML card for the dashboard.
        Input: A grouped trace dictionary containing request metadata and ordered events.
        Output: An HTML fragment for one trace.
        Failures: No failure is expected.
        """

        status_class = "error" if trace["status"] == "error" else ""
        event_rows = "\n".join(self._render_event_row(event) for event in trace["events"])
        telegram_text = html.escape(trace.get("telegram_text") or "")
        final_output = html.escape(trace.get("final_output") or "")
        return f"""
        <section class="trace">
          <div class="meta">
            <span class="badge {status_class}">{html.escape(trace['status'])}</span>
            <span>Trace: <code>{html.escape(trace['trace_id'])}</code></span>
            <span>User: <code>{html.escape(str(trace.get('user_id') or ''))}</code></span>
            <span>Chat: <code>{html.escape(str(trace.get('chat_id') or ''))}</code></span>
            <span>Started: <code>{html.escape(trace['started_at'])}</code></span>
          </div>
          <strong>Telegram Input</strong>
          <div class="text-block">{telegram_text or "No text payload recorded."}</div>
          <strong>Final Output</strong>
          <div class="text-block">{final_output or "No final output recorded."}</div>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Agent</th>
                <th>Message</th>
                <th>Input</th>
                <th>Output / Error</th>
              </tr>
            </thead>
            <tbody>
              {event_rows}
            </tbody>
          </table>
        </section>
        """

    def _render_event_row(self, event: dict[str, Any]) -> str:
        """Task: Render one structured event as an HTML table row.
        Input: A single trace event dictionary.
        Output: An HTML row string for the dashboard table.
        Failures: No failure is expected.
        """

        level = event.get("level", "info")
        level_class = "level-error" if level == "error" else "level-info"
        input_text = html.escape(self._stringify_payload(event.get("agent_input")))
        output_or_error = event.get("error") or self._stringify_payload(event.get("agent_output"))
        output_text = html.escape(output_or_error)
        return f"""
        <tr>
          <td><code>{html.escape(event.get('timestamp', ''))}</code></td>
          <td class="{level_class}">{html.escape(level)}</td>
          <td><code>{html.escape(event.get('agent', ''))}</code></td>
          <td>{html.escape(event.get('message', ''))}</td>
          <td>{input_text}</td>
          <td>{output_text}</td>
        </tr>
        """

    def _stringify_payload(self, payload: Any) -> str:
        """Task: Convert structured payloads into readable strings for storage and rendering.
        Input: Any input or output payload attached to one trace event.
        Output: A readable string representation suitable for dashboard display.
        Failures: No failure is expected.
        """

        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(payload)
