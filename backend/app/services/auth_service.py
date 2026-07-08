import queue
import threading
from enum import Enum
from typing import Any, Optional

from playwright.sync_api import sync_playwright

from app.config import settings
from app.services.runtime_env import is_railway_runtime, require_headless_browser
from app.services.scraper import (
    LOGIN_URL,
    dismiss_overlays,
    ensure_chromium_installed,
    save_session,
    setup_playwright_browsers_path,
)


class LoginState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    WAITING_PHONE = "waiting_phone"
    WAITING_CODE = "waiting_code"
    COMPLETED = "completed"
    FAILED = "failed"


class _Command:
    __slots__ = ("action", "payload", "done")

    def __init__(self, action: str, payload: Any = None):
        self.action = action
        self.payload = payload
        self.done: queue.Queue = queue.Queue(maxsize=1)


class LoginManager:
    """Все операции Playwright выполняются в одном фоновом потоке."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = LoginState.IDLE
        self._error: Optional[str] = None
        self._cmd_queue: queue.Queue[_Command] = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="login-worker")
        self._worker.start()

    @property
    def state(self) -> LoginState:
        with self._lock:
            return self._state

    @property
    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    def _set_state(self, state: LoginState, error: Optional[str] = None) -> None:
        with self._lock:
            self._state = state
            if error is not None:
                self._error = error

    def _run_cmd(self, action: str, payload: Any = None, timeout: float = 120) -> Any:
        cmd = _Command(action, payload)
        self._cmd_queue.put(cmd)
        result = cmd.done.get(timeout=timeout)
        if isinstance(result, Exception):
            raise result
        return result

    def start(self) -> None:
        with self._lock:
            if self._state not in (LoginState.IDLE, LoginState.COMPLETED, LoginState.FAILED):
                raise RuntimeError(f"Вход уже в процессе: {self._state}")
            self._error = None
        self._run_cmd("start", timeout=60)

    def submit_phone(self, phone: str) -> None:
        with self._lock:
            if self._state != LoginState.WAITING_PHONE:
                raise RuntimeError("Сейчас не ожидается ввод телефона")
        self._run_cmd("phone", phone, timeout=60)

    def submit_code(self, code: str) -> None:
        with self._lock:
            if self._state != LoginState.WAITING_CODE:
                raise RuntimeError("Сейчас не ожидается ввод кода")
        self._run_cmd("code", code, timeout=90)

    def cancel(self) -> None:
        try:
            self._run_cmd("cancel", timeout=10)
        except Exception:
            self._set_state(LoginState.IDLE)

    def _worker_loop(self) -> None:
        playwright = None
        browser = None
        context = None
        page = None

        def cleanup() -> None:
            nonlocal playwright, browser, context, page
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    playwright.stop()
            except Exception:
                pass
            playwright = browser = context = page = None

        while True:
            cmd = self._cmd_queue.get()
            try:
                if cmd.action == "start":
                    cleanup()
                    self._set_state(LoginState.STARTING)
                    if is_railway_runtime() and not settings.headless:
                        raise RuntimeError(
                            "На Railway браузер работает только headless. Установите HEADLESS=true."
                        )
                    if not require_headless_browser() and not settings.headless:
                        raise RuntimeError(
                            "Нет графического дисплея. Установите HEADLESS=true или выполните вход локально: python login.py"
                        )

                    setup_playwright_browsers_path()
                    ensure_chromium_installed()

                    playwright = sync_playwright().start()
                    browser = playwright.chromium.launch(headless=settings.headless)
                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                    page = context.new_page()

                    page.goto(LOGIN_URL, wait_until="domcontentloaded")
                    dismiss_overlays(page)

                    login_btn = page.get_by_role("button", name="Войти")
                    if login_btn.count():
                        login_btn.first.click()

                    self._set_state(LoginState.WAITING_PHONE)
                    cmd.done.put(None)

                elif cmd.action == "phone":
                    if not page:
                        raise RuntimeError("Браузер не инициализирован")

                    self._set_state(LoginState.STARTING)
                    phone = str(cmd.payload)

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
                    self._set_state(LoginState.WAITING_CODE)
                    cmd.done.put(None)

                elif cmd.action == "code":
                    if not page or not context:
                        raise RuntimeError("Браузер не инициализирован")

                    self._set_state(LoginState.STARTING)
                    code = str(cmd.payload)

                    otp_input = page.locator('input:not([disabled])[inputmode="numeric"]')
                    if otp_input.count() == 0:
                        otp_input = page.locator('input:not([disabled])[autocomplete="one-time-code"]')
                    if otp_input.count() == 0:
                        otp_input = page.locator("input:not([disabled])").last
                    otp_input.wait_for(state="visible", timeout=15_000)
                    otp_input.click()
                    otp_input.fill(code)

                    page.wait_for_function(
                        "() => !window.location.pathname.includes('/account/login')",
                        timeout=60_000,
                    )

                    save_session(context, settings.session_file)
                    self._set_state(LoginState.COMPLETED)
                    cleanup()
                    cmd.done.put(None)

                elif cmd.action == "cancel":
                    cleanup()
                    self._set_state(LoginState.IDLE)
                    cmd.done.put(None)

            except Exception as exc:
                cleanup()
                self._set_state(LoginState.FAILED, str(exc))
                cmd.done.put(exc)


login_manager = LoginManager()
