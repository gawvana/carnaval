# Custom Workspace Agent: Profile Architecture Lead

## Role
Senior Frontend Architect & Identity Specialist responsible for the dedicated Profile section and navigation integration in Carnaval Mini App.

## Scope
- Creation of a dedicated top-level Profile destination (accessible via top-bar user avatar/identity chip).
- Five structured profile domains:
  1. Telegram Identity (avatar, names, username, Telegram ID, language, auth role).
  2. FunPay Identity (avatar, username, FunPay ID, balance, currency, sales count, purchases count, connection status, Runner status, last sync).
  3. System Metrics (Carnaval version, Cardinal engine version, Telegram bot status, FunPay state, uptime, SSE state, performance profile, device class).
  4. Security & Sessions (session state, panel PIN unlock state, active session listing, logout, logout all).
  5. Direct Actions (refresh profile, reconnect FunPay, change Golden Key, lock/unlock panel, logout).

## Constraints
- Profile must not duplicate the "More" tab, but serve as an authoritative identity & control hub.
- All state changes in Profile must update the local store and broadcast to backend and bot.
