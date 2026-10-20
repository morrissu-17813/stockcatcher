from __future__ import annotations

import html

import requests

from ..data.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


_SIGNAL_PRESENTATION = {
    "EARLY": ("🔥", "盤中早期預判訊號"),
    "STRONG": ("🔥🔥", "盤中強勢預判訊號"),
    "MOMENTUM": ("🔥🔥🔥", "盤中動能預判訊號"),
}


class TelegramNotifier:
    def __init__(self, token=None, chat_id=None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID

    @property
    def enabled(self):
        return bool(self.token and self.chat_id)

    def send(self, text):
        if not self.enabled:
            return {"sent": False, "status": "DISABLED", "message_id": None}
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        # Telegram sendMessage does not provide an idempotency key. A read timeout
        # is therefore ambiguous: Telegram may have accepted the message even
        # though this client did not receive the response. Never raise a transport
        # error into the Radar loop and never label an ambiguous result as FAILED
        # (which would invite an automatic duplicate retry).
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=(5, 10),
            )
        except requests.exceptions.ConnectTimeout as exc:
            # Connection establishment timed out before a response was received.
            return {
                "sent": False, "status": "FAILED", "message_id": None,
                "error_type": type(exc).__name__, "error": str(exc)[:300],
            }
        except requests.exceptions.RequestException as exc:
            # ReadTimeout/ConnectionError can occur after the request reached
            # Telegram. Mark UNKNOWN and let reconciliation avoid blind resend.
            return {
                "sent": False, "status": "UNKNOWN", "message_id": None,
                "error_type": type(exc).__name__, "error": str(exc)[:300],
            }

        status_code = int(getattr(r, "status_code", 200))
        if status_code >= 500:
            # A server-side error can still leave delivery ambiguous.
            return {
                "sent": False, "status": "UNKNOWN", "message_id": None,
                "error_type": "HTTPServerError", "error": f"HTTP {status_code}",
            }
        if status_code >= 400:
            return {
                "sent": False, "status": "FAILED", "message_id": None,
                "error_type": "HTTPError", "error": f"HTTP {status_code}",
            }
        try:
            p = r.json()
        except (ValueError, requests.exceptions.RequestException) as exc:
            return {
                "sent": False, "status": "UNKNOWN", "message_id": None,
                "error_type": type(exc).__name__, "error": str(exc)[:300],
            }
        ok = bool(p.get("ok")) if isinstance(p, dict) else False
        return {
            "sent": ok,
            "status": "SENT" if ok else "FAILED",
            "message_id": ((p.get("result") or {}).get("message_id") if isinstance(p, dict) else None),
            "error": None if ok else (p.get("description") if isinstance(p, dict) else "invalid Telegram response"),
        }

    def send_premarket_watchlist(self, trade_date, pool):
        lines = [
            f"🌅 PREMARKET_WATCHLIST | {trade_date}",
            "盤前觀察池（非盤中訊號）",
            f"共 {len(pool)} 檔，盤中 Radar 將持續觀察：",
        ]
        for x in pool:
            lines.append(
                f"• {x.get('symbol')} {x.get('name', '')} | "
                f"Close {x.get('close', '-')} | Breakout {x.get('breakout_level', '-')}"
            )
        return self.send("\n".join(lines))

    @staticmethod
    def _format_ratio(value, suffix="x"):
        try:
            return f"{float(value):.1f}{suffix}"
        except (TypeError, ValueError):
            return "-"

    def send_intraday_prediction(self, event):
        snapshot = event["trigger_snapshot"]
        volume = event.get("volume_snapshot", {})
        context = event["context"]
        symbol = str(context.get("symbol", "")).strip()
        name = html.escape(str(context.get("name", "")).strip())
        nstock_url = f"https://www.nstock.tw/{symbol}"

        current_price = float(snapshot.get("current_price") or 0)
        up_pct = float(snapshot.get("up_pct") or 0)
        breakout_level = float(snapshot.get("breakout_level") or 0)
        projected_ratio = self._format_ratio(volume.get("projected_ratio"))
        effective_breakout = bool(snapshot.get("effective_breakout"))

        signal_level = str(
            snapshot.get("signal_level")
            or volume.get("signal_level")
            or event.get("signal_level")
            or "STRONG"
        ).upper()
        fire, wording = _SIGNAL_PRESENTATION.get(
            signal_level, ("🔥", "盤中預判訊號")
        )

        micro = snapshot.get("fugle_5m_confirmation") or event.get("fugle_5m_confirmation") or {}
        k3_volume_ratio = self._format_ratio(micro.get("volume_ratio"))

        if signal_level == "EARLY":
            evidence_source = str(snapshot.get("early_evidence_source") or "FUGLE_5M")
            if evidence_source == "MIS_LIVE":
                evidence_label = "MIS 即時量價"
                evidence_lines = (
                    f"🔎 EARLY 證據：MIS 即時量價\n"
                    f"📈 連續快照確認：{int(snapshot.get('confirmed_snapshots') or 2)} 次\n"
                    f"📊 量能速度比：{self._format_ratio(snapshot.get('mis_live_volume_ratio') or volume.get('live_volume_ratio'))}\n"
                    f"📦 觀察窗增量：{float(snapshot.get('mis_volume_delta_lots') or volume.get('volume_delta_lots') or 0):.1f} 張 / "
                    f"{float(snapshot.get('mis_volume_window_seconds') or volume.get('live_volume_window_seconds') or 0):.0f} 秒\n"
                    f"📐 量能基準：{html.escape(str(snapshot.get('mis_volume_baseline_source') or volume.get('live_volume_baseline_source') or 'VMA5_DAILY_DIV_54'))}\n"
                    f"🏗️ Fugle 5M：背景驗證中"
                )
                footer = "MIS 即時量價先行預警，Fugle 5M 持續補充證據。"
            else:
                evidence_label = "Fugle 已完成 5M K"
                structure_mark = "✔" if bool(micro.get("structure_pass")) else "✖"
                volume_mark = "✔" if bool(micro.get("volume_pass")) else "✖"
                evidence_lines = (
                    f"🔎 EARLY 證據：{evidence_label}\n"
                    f"🏗️ 5M 結構：{structure_mark}\n"
                    f"📊 5M 量能：{volume_mark}\n"
                    f"📒 K3突破的5分K量比：{k3_volume_ratio}"
                )
                footer = "盤中提前預警，等待 STRONG 確認。"
            text = (
                f"<b>🟡 天機 3K EARLY</b>\n"
                f"━━━━━━━━━━━━\n"
                f"📈 標的：<a href=\"{nstock_url}\"><b>{html.escape(symbol)} {name}</b></a>\n"
                f"💰 現價：{current_price:.1f} 📈 {up_pct:+.1f}%\n"
                f"📊 預估量比：{projected_ratio}\n"
                f"📐 突破基準價：{breakout_level:.1f}\n\n"
                f"{evidence_lines}\n\n"
                f"🚀 有效突破：{'☑️' if effective_breakout else '⬜'}\n"
                f"━━━━━━━━━━━━\n"
                f"⏰ 觸發時間：{self._trigger_time(snapshot.get('observed_at') or event.get('created_at'))}\n\n"
                f"📝 <i>{footer}</i>"
            )
        else:
            text = (
                f"<b>{fire} 天機 3K {signal_level}</b>\n"
                f"━━━━━━━━━━━━\n"
                f"📈 標的：<a href=\"{nstock_url}\"><b>{html.escape(symbol)} {name}</b></a>\n"
                f"💰 現價：{current_price:.1f} 📈 {up_pct:+.1f}%\n"
                f"📊 預估量比：{projected_ratio}\n"
                f"📐 突破基準價：{breakout_level:.1f}\n"
                f"📒 K3突破的5分K量比：{k3_volume_ratio}\n"
                f"🚀 有效突破：{'☑️' if effective_breakout else '⬜'}\n"
                f"━━━━━━━━━━━━\n"
                f"⏰ 觸發時間：{self._trigger_time(snapshot.get('observed_at') or event.get('created_at'))}\n\n"
                f"📝 <i>{wording}，收盤後以 GROUND_TRUTH 驗證。</i>"
            )
        return self.send(text)

    @staticmethod
    def _trigger_time(value):
        if not value:
            return "-"
        text = str(value)
        if "T" in text:
            text = text.split("T", 1)[1]
        text = text.split("+", 1)[0].split("Z", 1)[0]
        return text[:8]

    def send_ground_truth(self, gt):
        status = "PASS" if gt.get("ground_truth_3k") else "FAIL"
        return self.send(
            f"🏁 GROUND_TRUTH | {gt.get('trade_date')} | {gt.get('symbol')}\n"
            f"收盤驗證：{status}\n"
            f"收盤 {gt.get('close', '-')} | 漲幅 {gt.get('gain_pct', '-')}%"
        )


def send_telegram(text, chat_id=None, token=None):
    return TelegramNotifier(
        token or TELEGRAM_BOT_TOKEN,
        chat_id or TELEGRAM_CHAT_ID,
    ).send(text).get("sent", False)
