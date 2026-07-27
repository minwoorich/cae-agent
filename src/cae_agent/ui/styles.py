"""CAE Agent NiceGUI 화면의 색상, 레이아웃과 반응형 스타일을 관리한다."""

from __future__ import annotations

from typing import Any


def apply_ui_theme(ui: Any) -> None:
    """모든 페이지가 공유하는 다크 테마와 컴팩트 채팅 스타일을 등록한다."""
    ui.colors(
        primary="#38bdf8",
        secondary="#22d3ee",
        accent="#f59e0b",
        positive="#34d399",
        negative="#fb7185",
        dark="#08111f",
    )
    ui.dark_mode().enable()
    ui.add_css(
        """
        :root {
            --cae-bg: #08111f;
            --cae-surface: #0d1a2b;
            --cae-surface-raised: #122238;
            --cae-border: rgba(148, 163, 184, 0.16);
            --cae-text: #e5eefb;
            --cae-muted: #8fa5bf;
            --cae-primary: #38bdf8;
            --cae-positive: #34d399;
            --cae-warning: #f59e0b;
            --cae-negative: #fb7185;
        }
        body, .q-page, .nicegui-content {
            background:
                radial-gradient(circle at 80% -10%, rgba(56, 189, 248, 0.10), transparent 32rem),
                var(--cae-bg);
            color: var(--cae-text);
        }
        .cae-header {
            background: rgba(8, 17, 31, 0.88);
            border-bottom: 1px solid var(--cae-border);
            backdrop-filter: blur(18px);
        }
        .cae-drawer {
            background: #0a1525;
            border-right: 1px solid var(--cae-border);
        }
        .cae-drawer .q-tab {
            justify-content: flex-start;
            min-height: 48px;
            border-radius: 12px;
            color: var(--cae-muted);
        }
        .cae-drawer .q-tab--active {
            color: var(--cae-text);
            background: rgba(56, 189, 248, 0.12);
        }
        .cae-panel {
            background: linear-gradient(145deg, rgba(18, 34, 56, 0.94), rgba(13, 26, 43, 0.94));
            border: 1px solid var(--cae-border);
            border-radius: 18px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.18);
        }
        .cae-metric {
            min-width: 190px;
            flex: 1 1 190px;
        }
        .cae-eyebrow {
            color: var(--cae-primary);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }
        .cae-muted { color: var(--cae-muted); }
        .cae-hero-copy {
            max-width: 100%;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .cae-actions {
            display: flex;
            flex-wrap: wrap !important;
        }
        .cae-upload {
            border: 1px dashed rgba(56, 189, 248, 0.55);
            border-radius: 16px;
            background: rgba(56, 189, 248, 0.05);
        }
        .cae-file-row {
            border-bottom: 1px solid var(--cae-border);
            padding: 0.7rem 0;
        }
        .cae-file-row:last-child { border-bottom: 0; }
        .cae-danger {
            border-color: rgba(251, 113, 133, 0.34);
            background: rgba(127, 29, 29, 0.12);
        }
        .q-dialog__backdrop {
            background: rgba(2, 6, 23, 0.86) !important;
            backdrop-filter: blur(8px);
        }
        .cae-dialog-card {
            background: #0d1a2b !important;
            color: var(--cae-text) !important;
            border: 1px solid rgba(148, 163, 184, 0.42) !important;
            box-shadow:
                0 28px 90px rgba(0, 0, 0, 0.72),
                0 0 0 1px rgba(56, 189, 248, 0.08) !important;
            opacity: 1 !important;
        }
        .cae-dialog-card.cae-danger {
            background:
                linear-gradient(145deg, #241827, #0d1a2b 58%) !important;
            border-color: rgba(251, 113, 133, 0.58) !important;
        }
        .cae-chat-stream {
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
            scroll-behavior: smooth;
            padding: 1.5rem clamp(0.5rem, 4vw, 4rem);
        }
        .cae-chat-page {
            height: 100%;
            min-height: 0;
            overflow: hidden;
            padding: 0.75rem clamp(0.75rem, 2vw, 1.25rem);
            position: relative;
        }
        .cae-chat-shell {
            flex: 1 1 auto;
            min-height: 0;
            background: rgba(8, 17, 31, 0.46);
            border: 1px solid var(--cae-border);
            border-radius: 22px;
            overflow: hidden;
        }
        .cae-chat-tab-panel {
            height: calc(100dvh - 64px);
            min-height: 0;
            overflow: hidden !important;
            padding: 0 !important;
        }
        .cae-session-menu-trigger {
            position: fixed !important;
            top: 16px;
            right: 176px;
            z-index: 3000;
            color: var(--cae-primary) !important;
        }
        .cae-session-menu {
            background: #0d1a2b !important;
            color: var(--cae-text) !important;
            border: 1px solid var(--cae-border);
            border-radius: 14px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.38);
        }
        .cae-message {
            width: auto;
            max-width: min(980px, 88%);
            border: 1px solid var(--cae-border);
            border-radius: 18px;
            padding: 1rem 1.15rem;
        }
        .cae-message-user {
            align-self: flex-end;
            background: rgba(56, 189, 248, 0.13);
            border-color: rgba(56, 189, 248, 0.30);
        }
        .cae-message-assistant {
            align-self: flex-start;
            background: rgba(18, 34, 56, 0.58);
            border-color: transparent;
        }
        .cae-message-system {
            align-self: center;
            background: rgba(148, 163, 184, 0.08);
        }
        .cae-message-error {
            align-self: flex-start;
            background: rgba(127, 29, 29, 0.18);
            border-color: rgba(251, 113, 133, 0.34);
        }
        .cae-message-body {
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            line-height: 1.7;
        }
        .cae-progress-panel {
            border: 1px solid rgba(148, 163, 184, 0.20);
            border-radius: 14px;
            background: rgba(2, 6, 23, 0.20);
        }
        .cae-progress-step {
            padding: 0.4rem 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
        }
        .cae-progress-step:last-child { border-bottom: 0; }
        .cae-progress-detail {
            overflow-wrap: anywhere;
            white-space: pre-wrap;
        }
        .cae-composer {
            position: sticky;
            bottom: 0;
            z-index: 2;
            border: 0 !important;
            border-radius: 0 !important;
            background: linear-gradient(
                180deg,
                rgba(8, 17, 31, 0),
                rgba(8, 17, 31, 0.98) 24%
            ) !important;
            backdrop-filter: blur(16px);
            box-shadow: none !important;
        }
        .cae-composer-inner {
            width: min(920px, 100%);
            margin: 0 auto;
            padding: 0.55rem 0.65rem;
            border: 1px solid rgba(148, 163, 184, 0.32);
            border-radius: 26px;
            background: #111d2e;
            box-shadow: 0 10px 32px rgba(0, 0, 0, 0.24);
        }
        .cae-composer-inner:focus-within {
            border-color: rgba(148, 163, 184, 0.56);
        }
        .cae-hidden-upload { display: none !important; }
        .cae-input-library {
            border-top: 1px solid rgba(148, 163, 184, 0.18);
            margin-top: 0.15rem;
            padding-top: 0.15rem;
        }
        .cae-input-library .q-expansion-item__container {
            background: transparent;
            border-radius: 14px;
        }
        .cae-input-library-row {
            border-radius: 12px;
            padding: 0.25rem 0.35rem;
        }
        .cae-input-library-row:hover {
            background: rgba(148, 163, 184, 0.08);
        }
        .cae-chat-input .q-field__control {
            min-height: 42px !important;
            padding: 0 0.35rem !important;
            color: var(--cae-text);
        }
        .cae-chat-input textarea {
            max-height: 180px;
            line-height: 1.55 !important;
            resize: none !important;
        }
        .cae-composer-feedback:empty { display: none; }
        .cae-composer-actions { min-height: 38px; }
        .cae-composer .q-chip { max-width: min(360px, 76vw); }
        .cae-composer .q-chip__content {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .q-tab-panels, .q-tab-panel {
            background: transparent !important;
        }
        .q-tab-panel {
            overflow-x: hidden;
        }
        .cae-page, .cae-panel {
            box-sizing: border-box;
            max-width: 100%;
        }
        @media (max-width: 900px) {
            body { overflow-x: hidden; }
            .cae-page {
                width: 100% !important;
                padding: 1rem !important;
            }
            .cae-hero-title { font-size: 1.75rem !important; }
            .cae-metric {
                min-width: 100% !important;
                flex-basis: 100% !important;
            }
            .cae-header-status { display: none !important; }
            .cae-actions .q-btn {
                width: 100%;
            }
            .cae-brand-subtitle { display: none !important; }
            .cae-chat-page {
                min-height: 0;
                height: 100%;
                padding: 0.5rem;
            }
            .cae-chat-tab-panel { height: calc(100dvh - 56px); }
            .cae-session-menu-trigger { right: 0.75rem; top: 12px; }
            .cae-chat-stream { padding: 1rem; }
            .cae-message { max-width: 100% !important; }
            .cae-composer { padding: 0.65rem !important; }
            .cae-composer-inner { border-radius: 22px; }
        }
        """
    )

