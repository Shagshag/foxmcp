#!/usr/bin/env python3
# foxmcp-description: Read what the page logged to its console and its uncaught errors; recording starts with the first call on a page and ends when the tab navigates
# foxmcp-args: [--level log|info|warn|error|debug|uncaught] [--pattern TEXT] [--limit 1-500] [--clear]
#
# Wrapping console on every page from the start would change stack locations and
# cost time on pages nobody is debugging, so recording begins with the first call
# on a page. Entries are kept in the tab's script scope (globalThis.foxmcpConsole),
# at most 500, and go when the tab navigates.

import argparse
import json
import sys

parser = argparse.ArgumentParser(prog="read-console.py", add_help=False)
parser.add_argument("--level", choices=["log", "info", "warn", "error", "debug", "uncaught"])
parser.add_argument("--pattern")
parser.add_argument("--limit", type=int, default=50)
parser.add_argument("--clear", action="store_true")
options = parser.parse_args()
if not 1 <= options.limit <= 500:
    parser.error("--limit must be an integer from 1 to 500")

args = json.dumps([options.level, options.pattern, options.limit, options.clear])
sys.stdout.write("""(() => {
  const [level, pattern, limit, clear] = """ + args + """;
  const state = globalThis.foxmcpConsole
    || (globalThis.foxmcpConsole = { armed: false, entries: [] });
  const started = !state.armed;
  if (started) {
    state.armed = true;
    const format = value => {
      if (value === undefined) return 'undefined';
      if (value === null || typeof value !== 'object') return String(value);
      try {
        // Firefox's stack has no message line, so keep the message with it.
        if (value instanceof window.wrappedJSObject.Error) {
          return value.stack ? String(value) + '\\n' + value.stack : String(value);
        }
        return JSON.stringify(value);
      } catch (error) {
        return Object.prototype.toString.call(value);
      }
    };
    const add = (entryLevel, message) => {
      state.entries.push({ level: entryLevel, message: message.slice(0, 2000) });
      if (state.entries.length > 500) state.entries.shift();
    };
    const page = window.wrappedJSObject;
    for (const name of ['log', 'info', 'warn', 'error', 'debug']) {
      const original = page.console[name];
      if (typeof original !== 'function') continue;
      // A page that froze or replaced console methods must not stop the others from being wrapped.
      try {
        page.console[name] = exportFunction(function (...values) {
          add(name, values.map(format).join(' '));
          // Spread, not apply(this, values): the array belongs to this script's side, and the
          // page's console cannot read it ("Permission denied to access property length"),
          // which would make every logged call throw in the page.
          return original.call(this || page.console, ...values);
        }, window);
      } catch (wrapError) {
        // Left as the page had it; its entries just are not recorded.
      }
    }
    window.addEventListener('error', event => add('uncaught',
      `${event.message} (${event.filename}:${event.lineno}:${event.colno})`));
    window.addEventListener('unhandledrejection', event => add('uncaught',
      'Unhandled promise rejection: ' + format(event.reason)));
  }
  let entries = state.entries.filter(entry =>
    (!level || entry.level === level || (level === 'error' && entry.level === 'uncaught'))
    && (!pattern || entry.message.includes(pattern)));
  entries = entries.slice(-limit);
  if (clear) state.entries.length = 0;
  return { started, entries };
})()
""")
