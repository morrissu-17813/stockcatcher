"""Durable notification formatting and Telegram transport for AI Quant Lab paper events."""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error
from dataclasses import dataclass

@dataclass
class TelegramResult:
    accepted: bool
    message_id: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    retry_after: int | None = None

class TelegramTransport:
    def __init__(self, token=None, chat_id=None, timeout=8):
        self.token = token or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.token and self.chat_id)

    def send(self, text):
        if not self.configured:
            return TelegramResult(False, error_code='NOT_CONFIGURED', error_description='Telegram credentials are not configured')
        payload = json.dumps({'chat_id': self.chat_id, 'text': str(text)[:4000]}).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{self.token}/sendMessage', data=payload,
                                     headers={'Content-Type':'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                body = json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode('utf-8', 'replace')[:1000]
            try: body = json.loads(raw)
            except Exception: body = {}
            params = body.get('parameters') or {}
            return TelegramResult(False, error_code=str(exc.code), error_description=str(body.get('description') or raw or exc.reason)[:500],
                                  retry_after=int(params['retry_after']) if str(params.get('retry_after','')).isdigit() else None)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Network failure may occur after Telegram accepted the message: outcome is unknown.
            raise DeliveryOutcomeUnknown(f'{type(exc).__name__}: {exc}') from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise DeliveryOutcomeUnknown(f'Invalid/empty Telegram response: {type(exc).__name__}') from exc
        if body.get('ok'):
            result = body.get('result') or {}
            return TelegramResult(True, message_id=str(result.get('message_id')) if result.get('message_id') is not None else None)
        params = body.get('parameters') or {}
        return TelegramResult(False, error_code=str(body.get('error_code') or 'API_REJECTED'),
                              error_description=str(body.get('description') or 'Telegram rejected the message')[:500],
                              retry_after=int(params['retry_after']) if str(params.get('retry_after','')).isdigit() else None)

class DeliveryOutcomeUnknown(RuntimeError):
    """Transport ended without enough evidence to know whether a message was accepted."""

def paper_fill_text(fill, stock_name=None):
    side = str(fill.get('side','')).upper()
    label = '模擬買進' if side == 'BUY' else '模擬賣出'
    return (f'🐾 天機 AI Quant Lab｜紙上交易\n{label} {fill.get("symbol", "")} {stock_name or ""}\n'
            f'數量：{fill.get("quantity", 0)} 股\n成交價：NT${float(fill.get("price", 0)):,.2f}\n'
            f'手續費：NT${float(fill.get("fee", 0)):,.0f}\n已實現損益：NT${float(fill.get("realized_pnl", 0)):,.0f}\n'
            '⚠️ 紙上交易，非券商委託')

# Backward-compatible helper for tests/integrations; new runtime should enqueue instead.
def send_paper_fill(fill, stock_name=None):
    result = TelegramTransport().send(paper_fill_text(fill, stock_name))
    return {'sent': result.accepted, 'reason': result.error_description or result.error_code,
            'message_id': result.message_id, 'retry_after': result.retry_after}
