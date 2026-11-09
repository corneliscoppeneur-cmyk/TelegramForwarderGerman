"""Minimaler MCP-Client (JSON-RPC über HTTP, zustandslos).

Spricht den telegram-mcp-Server an (``tools/call``). Der Server antwortet je
nach Transport als JSON oder als Server-Sent-Event (``data: {...}``) – beides
wird hier geparst. Kein Session-Handling nötig: der Server akzeptiert
zustandslose Aufrufe.
"""
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)


class McpError(Exception):
    pass


class McpClient:
    def __init__(self, url, timeout=60):
        self.url = url
        self.timeout = timeout
        self._next_id = 0

    async def call_tool(self, name, arguments):
        """Werkzeug aufrufen; gibt den Text des ersten Inhaltsblocks zurück."""
        self._next_id += 1
        payload = {
            'jsonrpc': '2.0',
            'id': self._next_id,
            'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments},
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
                async with s.post(self.url, json=payload, headers=headers) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        raise McpError(f'HTTP {resp.status}: {body[:200]}')
        except aiohttp.ClientError as e:
            raise McpError(f'MCP nicht erreichbar: {e}') from e

        data = self._parse(body)
        if 'error' in data:
            raise McpError(str(data['error'])[:300])
        result = data.get('result') or {}
        text = ''
        for block in result.get('content') or []:
            if block.get('type') == 'text':
                text = block.get('text', '')
                break
        if not text and isinstance(result.get('structuredContent'), dict):
            text = str(result['structuredContent'].get('result', ''))
        if result.get('isError'):
            raise McpError(text[:300] or 'Werkzeugfehler')
        return text

    @staticmethod
    def _parse(body):
        body = body.strip()
        if body.startswith('{'):
            return json.loads(body)
        # SSE: letzte ``data:``-Zeile mit JSON-RPC-Antwort nehmen
        last = None
        for line in body.splitlines():
            if line.startswith('data:'):
                chunk = line[5:].strip()
                if chunk:
                    try:
                        last = json.loads(chunk)
                    except ValueError:
                        continue
        if last is None:
            raise McpError(f'Unerwartete MCP-Antwort: {body[:200]}')
        return last
