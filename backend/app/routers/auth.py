from fastapi import APIRouter

from app.config import settings
from app.schemas import (
    AuthStatus,
    LoginCodeRequest,
    LoginPhoneRequest,
    LoginStartResponse,
)
from app.services.auth_service import LoginState, login_manager
from app.services.scraper import check_session_valid

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
def get_auth_status():
    connected = check_session_valid(settings.session_file, headless=settings.headless)
    message = None
    if not connected:
        if settings.session_file.exists():
            message = "Сессия истекла. Выполните повторный вход."
        else:
            message = "Войдите в аккаунт HH для начала работы."

    return AuthStatus(
        connected=connected,
        session_file=str(settings.session_file),
        message=message,
    )


@router.post("/login/start", response_model=LoginStartResponse)
def start_login():
    try:
        login_manager.start()
        return LoginStartResponse(
            status=login_manager.state.value,
            message="Откроется окно браузера. Введите номер телефона в админке.",
        )
    except RuntimeError as exc:
        return LoginStartResponse(status="error", message=str(exc))


@router.get("/login/status")
def login_status():
    return {
        "state": login_manager.state.value,
        "error": login_manager.error,
    }


@router.post("/login/phone", response_model=LoginStartResponse)
def submit_phone(body: LoginPhoneRequest):
    try:
        login_manager.submit_phone(body.phone)
        return LoginStartResponse(
            status=login_manager.state.value,
            message="Код отправлен на телефон. Введите его в админке.",
        )
    except RuntimeError as exc:
        return LoginStartResponse(status="error", message=str(exc))


@router.post("/login/code", response_model=LoginStartResponse)
def submit_code(body: LoginCodeRequest):
    try:
        login_manager.submit_code(body.code)
        return LoginStartResponse(
            status=login_manager.state.value,
            message="Вход выполнен успешно." if login_manager.state == LoginState.COMPLETED else "Обработка...",
        )
    except RuntimeError as exc:
        return LoginStartResponse(status="error", message=str(exc))


@router.post("/login/cancel")
def cancel_login():
    login_manager.cancel()
    return {"status": "cancelled"}


@router.delete("/session")
def delete_session():
    login_manager.cancel()
    if settings.session_file.exists():
        settings.session_file.unlink()
    return {"status": "deleted"}
