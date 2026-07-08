"""CLI-вход на hh.ru и сохранение сессии для парсера."""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DEFAULT_SESSION_FILE = DATA_DIR / "session.json"
USER_DATA_DIR = DATA_DIR / "browser_data"


def _setup_path():
    import os
    from app.services.scraper import setup_playwright_browsers_path
    setup_playwright_browsers_path()


def interactive_login(session_file: Path) -> None:
    from app.services.scraper import (
        LOGIN_URL,
        dismiss_overlays,
        is_logged_in,
        save_session,
        ensure_chromium_installed,
    )

    _setup_path()
    ensure_chromium_installed()
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://hh.ru/", wait_until="domcontentloaded")
        from app.services.scraper import dismiss_overlays as d
        d(page)

        if not is_logged_in(page):
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            d(page)

            login_btn = page.get_by_role("button", name="Войти")
            if login_btn.count():
                login_btn.first.click()

            phone = input("Введите номер телефона: ").strip()
            phone_input = page.locator('input[type="tel"]:not([disabled])').last
            if phone_input.count() == 0:
                phone_input = page.get_by_role("textbox").nth(1)
            phone_input.wait_for(state="visible", timeout=15_000)
            phone_input.click()
            phone_input.fill(phone)

            next_btn = page.get_by_role("button", name="Дальше")
            if next_btn.count() == 0:
                next_btn = page.get_by_role("button", name="Продолжить")
            next_btn.click()

            page.get_by_role("heading", name="Введите код из смс").wait_for(timeout=30_000)
            code = input("Введите код из SMS: ").strip()

            otp_input = page.locator('input:not([disabled])[inputmode="numeric"]')
            if otp_input.count() == 0:
                otp_input = page.locator("input:not([disabled])").last
            otp_input.click()
            otp_input.fill(code)

            page.wait_for_function(
                "() => !window.location.pathname.includes('/account/login')",
                timeout=60_000,
            )
            print("Вход выполнен.")

        session_file.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(session_file))
        context.close()

    print(f"Сессия сохранена: {session_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Вход на hh.ru и экспорт session.json")
    parser.add_argument("--session-file", default=str(DEFAULT_SESSION_FILE))
    args = parser.parse_args()
    session_file = Path(args.session_file)

    sys.path.insert(0, str(ROOT_DIR / "backend"))
    interactive_login(session_file)


if __name__ == "__main__":
    main()
