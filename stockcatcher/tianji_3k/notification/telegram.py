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
        r = requests.post(
            url,
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
        p = r.json()
        return {
            "sent": bool(p.get("ok")),
            "status": "SENT" if p.get("ok") else "FAILED",
            "message_id": (p.get("result") or {}).get("message_id"),
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
            structure_mark = "✔" if bool(micro.get("structure_pass")) else "✖"
            volume_mark = "✔" if bool(micro.get("volume_pass")) else "✖"
            text = (
                f"<b>🟡 天機 3K EARLY</b>\n"
                f"━━━━━━━━━━━━\n"
                f"📈 標的：<a href=\"{nstock_url}\"><b>{html.escape(symbol)} {name}</b></a>\n"
                f"💰 現價：{current_price:.1f} 📈 {up_pct:+.1f}%\n"
                f"📐 突破基準價：{breakout_level:.1f}\n\n"
                f"🔎 EARLY 觸發：\n"
                f"🏗️ 5M 結構：{structure_mark}\n"
                f"📊 5M 量能：{volume_mark}\n"
                f"📒 K3突破的5分K量比：{k3_volume_ratio}\n\n"
                f"🚀 有效突破：{'☑️' if effective_breakout else '⬜'}\n"
                f"━━━━━━━━━━━━\n"
                f"⏰ 觸發時間：{self._trigger_time(snapshot.get('observed_at') or event.get('created_at'))}\n\n"
                f"📝 <i>盤中提前預警，等待 STRONG 確認。</i>"
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
