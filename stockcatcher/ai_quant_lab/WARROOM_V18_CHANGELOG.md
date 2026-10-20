# AI Quant Lab V18 — Durable Notification Dispatcher

## Scope
V18 upgrades the V17 Outbox into a durable Telegram dispatcher for AI Quant Lab paper-trading notifications. It does not modify Tianji 3K production code and does not place broker orders.

## Implemented
- Additive Supabase migration `202610170002_v18_durable_notification_dispatcher.sql`.
- Atomic `ai_quant_lab_commit_event_and_outbox` RPC persists paper-fill event, paper-trade row, and Telegram outbox item in one database transaction.
- Deterministic outbox UUID and idempotency key `paper-fill-telegram:<event_id>`.
- Atomic claim RPC using `FOR UPDATE SKIP LOCKED`, worker lease, due-time scheduling, stale-lease recovery, and max-attempt dead-lettering.
- Background dispatcher polls durable outbox; retries Telegram 429/5xx with exponential backoff and honors `retry_after`.
- Ambiguous network outcomes are set to `UNKNOWN` and are not automatically resent, because Telegram sendMessage has no client idempotency key.
- Permanent failures and exhausted retries move to `DEAD_LETTER`; manual retry endpoint only permits `DEAD_LETTER`. `UNKNOWN` requires reconciliation first.
- Runtime status endpoint `GET /api/notifications/status` and dashboard tile for dispatcher health.
- Paper-fill notifications no longer send synchronously from the autonomy trading loop.
- All notification payloads are explicitly marked paper-only; no broker connector or live order API is introduced.

## Deploy
1. Back up the current AI Quant Lab folder and Supabase data.
2. Merge this `ai_quant_lab` folder into the existing project without replacing `.env`.
3. Apply V17 migration first if not already applied, then execute `supabase/migrations/202610170002_v18_durable_notification_dispatcher.sql` in Supabase SQL Editor.
4. Ensure backend `.env` contains `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_TOKEN`), and `TELEGRAM_CHAT_ID`. Never expose service-role key or Telegram token to the frontend.
5. Restart `START_LAB_WINDOWS.ps1`; verify `http://127.0.0.1:8765/api/notifications/status`.

## Guarantees and limitations
- Database event + paper fill + outbox insertion is atomic for the V18 RPC path.
- Delivery is at-least-once with an explicit `UNKNOWN` state for ambiguous outcomes, not mathematically exactly-once end-to-end. Telegram does not provide a client idempotency key for `sendMessage`.
- This environment ran unit tests, Python compile checks, and Vue script syntax checks. The migration has not been executed against the user's live Supabase project; a live database migration and failure-injection test remain deployment acceptance steps.
