import logging
import queue
import threading
from enum import Enum
from typing import Any, Optional

from playwright.sync_api import Page, sync_playwright

from app.config import settings
from app.services.runtime_env import is_railway_runtime, require_headless_browser
from app.services.scraper import (
    LOGIN_URL,
    click_login_next,
    dismiss_overlays,
    ensure_chromium_installed,
    find_login_otp_input,
    find_login_phone_input,
    login_browser_context_kwargs,
    normalize_phone,
    save_login_debug_screenshot,
    save_session,
    setup_playwright_browsers_path,
    wait_for_login_code_step,
)

logger = logging.getLogger(__name__)


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
                raise RuntimeError(
                    f"Вход уже в процессе ({self._state.value}). Отправьте /cancel и снова /login."
                )
            self._error = None
        self._run_cmd("start", timeout=90)

    def submit_phone(self, phone: str) -> None:
        with self._lock:
            if self._state != LoginState.WAITING_PHONE:
                raise RuntimeError(
                    f"Сейчас не ожидается телефон (состояние: {self._state.value}). "
                    "Отправьте /login чтобы начать заново."
                )
        self._run_cmd("phone", phone, timeout=90)

    def submit_code(self, code: str) -> None:
        with self._lock:
            if self._state != LoginState.WAITING_CODE:
                raise RuntimeError(
                    f"Сейчас не ожидается код (состояние: {self._state.value}). "
                    "Отправьте /login чтобы начать заново."
                )
        self._run_cmd("code", code, timeout=120)

    def cancel(self) -> None:
        try:
            self._run_cmd("cancel", timeout=15)
        except Exception:
            self._set_state(LoginState.IDLE)

    def _open_login_page(self, page: Page) -> None:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        dismiss_overlays(page)

        login_btn = page.get_by_role("button", name="Войти")
        if login_btn.count():
            login_btn.first.click()
            page.wait_for_timeout(800)

        find_login_phone_input(page).wait_for(state="visible", timeout=20_000)

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
                    context = browser.new_context(**login_browser_context_kwargs())
                    page = context.new_page()

                    self._open_login_page(page)
                    self._set_state(LoginState.WAITING_PHONE)
                    cmd.done.put(None)

                elif cmd.action == "phone":
                    if not page:
                        raise RuntimeError("Браузер не инициализирован. Отправьте /login.")

                    self._set_state(LoginState.STARTING)
                    phone = normalize_phone(str(cmd.payload))

                    phone_input = find_login_phone_input(page)
                    phone_input.wait_for(state="visible", timeout=20_000)
                    phone_input.click()
                    phone_input.fill(phone)

                    click_login_next(page)
                    wait_for_login_code_step(page, timeout=45_000)

                    self._set_state(LoginState.WAITING_CODE)
                    cmd.done.put(None)

                elif cmd.action == "code":
                    if not page or not context:
                        raise RuntimeError("Браузер не инициализирован. Отправьте /login.")

                    self._set_state(LoginState.STARTING)
                    code = str(cmd.payload).strip().replace(" ", "")

                    otp_input = find_login_otp_input(page)
                    otp_input.wait_for(state="visible", timeout=20_000)
                    otp_input.click()
                    otp_input.fill(code)

                    page.wait_for_function(
                        "() => !window.location.pathname.includes('/account/login')",
                        timeout=90_000,
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
                if page is not None:
                    save_login_debug_screenshot(page, settings.session_file, cmd.action)
                logger.exception("HH login failed at %s", cmd.action)
                cleanup()
                self._set_state(LoginState.FAILED, str(exc))
                cmd.done.put(exc)


_manager: Optional[LoginManager] = None
_manager_lock = threading.Lock()


def get_login_manager() -> LoginManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = LoginManager()
        return _manager
