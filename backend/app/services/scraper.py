import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from app.config import settings


@dataclass(frozen=True)
class Vacancy:
    vacancy_id: str
    title: str
    watchers_text: str
    watchers_count: Optional[int]


@dataclass
class RunStats:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class ApplyResult:
    status: str
    cover_letter_sent: bool = False


LOGIN_URL = "https://hh.ru/account/login?role=applicant&backurl=/"


def _parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.replace("\xa0", " ")
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def setup_playwright_browsers_path() -> None:
    custom = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = custom
        return

    docker_path = Path("/ms-playwright")
    if docker_path.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(docker_path)
        return

    local_cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if local_cache.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_cache)


def ensure_chromium_installed() -> None:
    browsers_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if browsers_root.exists() and list(browsers_root.glob("chromium-*")):
        return
    raise RuntimeError(
        "Chromium не найден. Выполните: python3 -m playwright install chromium"
    )


def create_context(
    playwright: Playwright,
    *,
    session_file: Path,
    headless: bool = True,
    block_media: bool = True,
) -> Tuple[Browser, BrowserContext]:
    browser = playwright.chromium.launch(headless=headless)
    context_kwargs = {"viewport": {"width": 1920, "height": 1080}}
    if session_file.exists():
        context_kwargs["storage_state"] = str(session_file)
    context = browser.new_context(**context_kwargs)
    if block_media:
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "font", "media")
            else route.continue_(),
        )
    return browser, context


def save_session(context: BrowserContext, session_file: Path) -> None:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(session_file))


def dismiss_overlays(page: Page) -> None:
    for name in ("Понятно", "Да, верно"):
        btn = page.get_by_role("button", name=name)
        if btn.count():
            try:
                btn.first.click(timeout=3000)
            except Exception:
                pass


def is_logged_in(page: Page) -> bool:
    if "account/login" in page.url:
        return False
    if page.locator('a[href*="/applicant/"]').count():
        return True
    if page.locator('[data-qa="mainmenu_applicantProfile"]').count():
        return True
    return page.get_by_role("button", name="Войти").count() == 0


def check_session_valid(session_file: Path, *, headless: bool = True) -> bool:
    if not session_file.exists():
        return False

    setup_playwright_browsers_path()
    ensure_chromium_installed()

    with sync_playwright() as playwright:
        browser, context = create_context(
            playwright,
            session_file=session_file,
            headless=headless,
            block_media=False,
        )
        page = context.new_page()
        try:
            page.goto("https://hh.ru/", wait_until="domcontentloaded", timeout=30_000)
            dismiss_overlays(page)
            return is_logged_in(page)
        finally:
            context.close()
            browser.close()


def scroll_until_all_loaded(
    page: Page,
    *,
    pause_ms: int = 500,
    max_scrolls: int = 50,
    stable_rounds_needed: int = 2,
) -> None:
    cards = page.locator('[data-qa="vacancy-serp__vacancy"]')
    stable = 0
    prev = cards.count()

    for _ in range(1, max_scrolls + 1):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)
        page.wait_for_timeout(int(pause_ms * 0.4))

        cur = cards.count()
        if cur > prev:
            prev = cur
            stable = 0
        else:
            stable += 1
            if stable >= stable_rounds_needed:
                break


def count_applicable_vacancies(page: Page) -> int:
    cards = page.locator('[data-qa="vacancy-serp__vacancy"]')
    count = 0
    for i in range(cards.count()):
        card = cards.nth(i)
        resp = card.locator('[data-qa="vacancy-serp__vacancy_response"]')
        if resp.count() == 0:
            continue
        btn_text = resp.first.inner_text().strip().lower()
        if "откликнуться" in btn_text:
            count += 1
    return count


def scroll_until_enough_for_apply(
    page: Page,
    *,
    apply_limit: int,
    buffer_factor: float = 1.5,
    pause_ms: int = 500,
    max_scrolls: int = 50,
    stable_rounds_needed: int = 2,
) -> int:
    """Прокручивает выдачу, пока не наберётся достаточно вакансий для отклика."""
    target = max(apply_limit, int(apply_limit * buffer_factor))
    cards = page.locator('[data-qa="vacancy-serp__vacancy"]')
    stable = 0
    prev = cards.count()

    applicable = count_applicable_vacancies(page)
    if applicable >= target:
        return applicable

    effective_max = min(max_scrolls, max(apply_limit * 3, 10))

    for _ in range(1, effective_max + 1):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)
        page.wait_for_timeout(int(pause_ms * 0.4))

        applicable = count_applicable_vacancies(page)
        if applicable >= target:
            return applicable

        cur = cards.count()
        if cur > prev:
            prev = cur
            stable = 0
        else:
            stable += 1
            if stable >= stable_rounds_needed:
                break

    return count_applicable_vacancies(page)


def collect_vacancies_for_apply(page: Page, limit: int = 10) -> List[Vacancy]:
    page.wait_for_selector('[data-qa="vacancy-serp__vacancy"]', timeout=30_000)
    cards = page.locator('[data-qa="vacancy-serp__vacancy"]')

    result: List[Vacancy] = []
    for i in range(cards.count()):
        card = cards.nth(i)

        resp = card.locator('[data-qa="vacancy-serp__vacancy_response"]')
        if resp.count() == 0:
            continue

        btn_text = resp.first.inner_text().strip().lower()
        if "откликнуться" not in btn_text:
            continue

        title = card.locator('[data-qa="serp-item__title-text"]').first.inner_text().strip()
        href = card.locator('a[data-qa="serp-item__title"]').first.get_attribute("href") or ""
        match = re.search(r"/vacancy/(\d+)", href)
        if not match:
            continue
        vacancy_id = match.group(1)

        watchers_loc = card.locator('span:has-text("Сейчас смотрят")').first
        watchers_text = watchers_loc.inner_text().strip() if watchers_loc.count() else "Сейчас смотрят —"
        watchers_count = _parse_int(watchers_text)

        result.append(
            Vacancy(
                vacancy_id=vacancy_id,
                title=title,
                watchers_text=watchers_text,
                watchers_count=watchers_count,
            )
        )
        if len(result) >= limit:
            break

    return result


def find_card_by_vacancy_id(page: Page, vacancy_id: str):
    return page.locator(
        '[data-qa="vacancy-serp__vacancy"]',
        has=page.locator(f'a[data-qa="serp-item__title"][href*="/vacancy/{vacancy_id}"]'),
    ).first


def is_test_page(page: Page) -> bool:
    container = page.locator('[data-qa="title-container"]').first
    if container.count() == 0:
        return False
    desc = page.locator('[data-qa="title-description"]:has-text("Для отклика необходимо ответить")').first
    return desc.count() > 0


def safe_go_back_to_serp(page: Page, fallback_url: str) -> None:
    page.goto(fallback_url, wait_until="domcontentloaded")
    page.wait_for_selector('[data-qa="vacancy-serp__vacancy"]', timeout=8_000)


def is_cover_letter_required_modal(page: Page) -> bool:
    dlg = page.locator('[role="dialog"]').first
    if dlg.count() == 0:
        return False
    required_hint = dlg.locator(
        '[data-qa="form-helper-description"]:has-text("Сопроводительное письмо обязательное")'
    ).first
    letter_input = dlg.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    return required_hint.count() > 0 and letter_input.count() > 0


def close_response_modal_if_open(page: Page) -> None:
    close_btn = page.locator('[data-qa="response-popup-close"]').first
    if close_btn.count():
        close_btn.click()
        try:
            page.locator('[role="dialog"]').first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass


def _select_resume_in_modal(dlg, page: Page) -> None:
    resume_select = dlg.locator('[data-qa*="resume-select"]')
    if resume_select.count():
        try:
            resume_select.first.click(timeout=2000)
            option = page.locator(
                '[data-qa*="resume-select"] [role="option"], [role="listbox"] [role="option"]'
            ).first
            if option.count():
                option.click(timeout=2000)
        except Exception:
            pass


def _fill_cover_letter_in_modal(dlg, cover_letter: str) -> bool:
    if not cover_letter.strip():
        return False
    letter_input = dlg.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    if letter_input.count() == 0:
        letter_input = dlg.locator("textarea").first
    if letter_input.count() == 0:
        return False
    try:
        letter_input.click(timeout=2000)
        letter_input.fill(cover_letter)
        return True
    except Exception:
        return False


def _click_modal_submit(dlg) -> bool:
    submit_btn = dlg.locator('[data-qa="vacancy-response-submit-popup"]').first
    if submit_btn.count() == 0:
        submit_btn = dlg.get_by_role("button", name=re.compile(r"Отклик", re.I)).first
    if submit_btn.count() == 0:
        return False
    try:
        submit_btn.click(timeout=3000)
        return True
    except Exception:
        return False


def try_submit_cover_letter_modal(page: Page, cover_letter: str) -> bool:
    dlg = page.locator('[role="dialog"]').first
    if dlg.count() == 0:
        return False
    if not _fill_cover_letter_in_modal(dlg, cover_letter):
        return False
    _select_resume_in_modal(dlg, page)
    return _click_modal_submit(dlg)


def has_letter_field_in_modal(page: Page) -> bool:
    dlg = page.locator('[role="dialog"]').first
    if dlg.count() == 0:
        return False
    letter_input = dlg.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    if letter_input.count():
        return True
    return dlg.locator("textarea").count() > 0


def try_submit_simple_response_modal(page: Page, cover_letter: str = "") -> bool:
    dlg = page.locator('[role="dialog"]').first
    if dlg.count() == 0:
        return False
    if is_cover_letter_required_modal(page) and not cover_letter.strip():
        return False

    _select_resume_in_modal(dlg, page)
    if cover_letter.strip():
        _fill_cover_letter_in_modal(dlg, cover_letter)

    return _click_modal_submit(dlg)


def hide_vacancy_card(page: Page, card, *, timeout_ms: int = 5000) -> bool:
    hide_icon = card.locator('button[data-qa="vacancy__blacklist-show-add"]').first
    if hide_icon.count() == 0:
        return False

    card.scroll_into_view_if_needed(timeout=timeout_ms)
    try:
        card.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
    except Exception:
        pass

    try:
        hide_icon.click(timeout=timeout_ms)
    except Exception:
        return False

    menu_item = page.locator('button[data-qa="vacancy__blacklist-menu-add-vacancy"]').first
    try:
        menu_item.wait_for(state="visible", timeout=timeout_ms)
        menu_item.click(timeout=timeout_ms)
    except Exception:
        return False

    try:
        card.wait_for(state="detached", timeout=3000)
    except Exception:
        pass

    return True


def scroll_card_into_view(page: Page, card) -> None:
    card.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
    page.wait_for_timeout(150)
    page.evaluate("window.scrollBy(0, -120)")


def click_apply_button(page: Page, card, apply_btn) -> None:
    scroll_card_into_view(page, card)

    for _ in range(3):
        try:
            apply_btn.click(timeout=5000)
            return
        except Exception:
            scroll_card_into_view(page, card)

    try:
        apply_btn.click(force=True, timeout=5000)
        return
    except Exception:
        pass

    try:
        apply_btn.evaluate("el => el.click()")
        return
    except Exception:
        pass

    href = apply_btn.get_attribute("href")
    if href:
        target = href if href.startswith("http") else f"https://hh.ru{href}"
        page.goto(target, wait_until="domcontentloaded")


def is_apply_success(page: Page, card=None) -> bool:
    success_locators = [
        '#dialog-description:has-text("Отклик отправлен")',
        '[role="alert"]:has-text("Отклик отправлен")',
        ':text("Отклик отправлен")',
    ]
    for selector in success_locators:
        if page.locator(selector).count():
            return True

    if card is not None:
        btn = card.locator('[data-qa="vacancy-serp__vacancy_response"]').first
        if btn.count():
            text = btn.inner_text().strip().lower()
            if "откликнулись" in text or "отклик отправлен" in text:
                return True

    return False


def click_apply_on_card(
    page: Page,
    card,
    *,
    poll_timeout_sec: float = 5.0,
    cover_letter: str = "",
) -> ApplyResult:
    original_url = page.url
    cover_letter_sent = False

    apply_btn = card.locator('[data-qa="vacancy-serp__vacancy_response"]').first
    if apply_btn.count() == 0:
        return ApplyResult("no_apply_button")

    click_apply_button(page, card, apply_btn)

    deadline = time.time() + poll_timeout_sec
    while time.time() < deadline:
        if is_apply_success(page, card):
            return ApplyResult("sent", cover_letter_sent)

        if is_cover_letter_required_modal(page):
            if cover_letter.strip():
                if try_submit_cover_letter_modal(page, cover_letter):
                    cover_letter_sent = True
                    page.wait_for_timeout(250)
                    if is_apply_success(page, card):
                        return ApplyResult("sent", True)
                return ApplyResult("cover_letter_failed")
            close_response_modal_if_open(page)
            return ApplyResult("cover_letter_required")

        if has_letter_field_in_modal(page) and cover_letter.strip():
            letter_used = True
        else:
            letter_used = False
        if try_submit_simple_response_modal(page, cover_letter):
            if letter_used:
                cover_letter_sent = True
            page.wait_for_timeout(250)
            if is_apply_success(page, card):
                return ApplyResult("sent", cover_letter_sent)

        if page.url != original_url:
            if is_test_page(page):
                safe_go_back_to_serp(page, fallback_url=original_url)
                return ApplyResult("test_required")
            safe_go_back_to_serp(page, fallback_url=original_url)
            return ApplyResult("extra_steps")

        page.wait_for_timeout(100)

    return ApplyResult("unknown")


def search_vacancies(page: Page, query: str, area_id: str = "") -> None:
    params = {"text": query}
    if area_id:
        params["area"] = area_id
    url = "https://hh.ru/search/vacancy?" + urllib.parse.urlencode(params)
    page.goto(url, wait_until="domcontentloaded")
    dismiss_overlays(page)


def wait_for_search_results(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const hasCards = document.querySelector('[data-qa="vacancy-serp__vacancy"]');
            const body = document.body
                ? document.body.innerText.replace(/\\s+/g, ' ').toLowerCase()
                : '';
            const isEmpty = body.includes('ничего не найдено')
                || body.includes('ничего не нашлось');
            return hasCards || isEmpty;
        }""",
        timeout=30_000,
    )


def search_has_vacancies(page: Page) -> bool:
    return page.locator('[data-qa="vacancy-serp__vacancy"]').count() > 0


def process_vacancy(
    page: Page,
    vacancy: Vacancy,
    *,
    hide_skipped: bool = False,
    poll_timeout_sec: float = 5.0,
    cover_letter: str = "",
) -> ApplyResult:
    card = find_card_by_vacancy_id(page, vacancy.vacancy_id)
    if card.count() == 0:
        return ApplyResult("card_not_found")

    try:
        result = click_apply_on_card(
            page,
            card,
            poll_timeout_sec=poll_timeout_sec,
            cover_letter=cover_letter,
        )
    except PlaywrightTimeoutError:
        return ApplyResult("timeout")
    except Exception:
        return ApplyResult("error")

    if result.status != "sent" and hide_skipped:
        card_again = find_card_by_vacancy_id(page, vacancy.vacancy_id)
        if card_again.count() > 0:
            hide_vacancy_card(page, card_again)

    return result


ProgressCallback = Callable[[dict], None]
ShouldStopCallback = Callable[[], bool]


def run_campaign(
    *,
    search_query: str,
    area_id: str,
    apply_limit: int,
    session_file: Path,
    headless: bool = True,
    scroll_max: int = 30,
    scroll_pause_ms: int = 500,
    scroll_buffer_factor: float = 1.5,
    apply_delay_ms: int = 700,
    apply_poll_timeout_sec: float = 5.0,
    hide_skipped_vacancies: bool = False,
    block_media: bool = True,
    cover_letter: str = "",
    on_progress: Optional[ProgressCallback] = None,
    should_stop: Optional[ShouldStopCallback] = None,
) -> RunStats:
    setup_playwright_browsers_path()
    ensure_chromium_installed()

    if not session_file.exists():
        raise RuntimeError("Сессия не найдена. Выполните вход через админку или login.py")

    stats = RunStats()

    with sync_playwright() as playwright:
        browser, context = create_context(
            playwright,
            session_file=session_file,
            headless=headless,
            block_media=block_media,
        )
        page = context.new_page()

        try:
            page.goto("https://hh.ru/", wait_until="domcontentloaded")
            dismiss_overlays(page)

            if not is_logged_in(page):
                raise RuntimeError("Сессия недействительна. Выполните повторный вход")

            search_vacancies(page, search_query, area_id)
            wait_for_search_results(page)

            if not search_has_vacancies(page):
                return stats

            scroll_until_enough_for_apply(
                page,
                apply_limit=apply_limit,
                buffer_factor=scroll_buffer_factor,
                pause_ms=scroll_pause_ms,
                max_scrolls=scroll_max,
            )
            vacancies = collect_vacancies_for_apply(page, limit=apply_limit)

            if on_progress:
                on_progress({"event": "vacancies_found", "count": len(vacancies)})

            for idx, vacancy in enumerate(vacancies, start=1):
                if should_stop and should_stop():
                    break

                result = process_vacancy(
                    page,
                    vacancy,
                    hide_skipped=hide_skipped_vacancies,
                    poll_timeout_sec=apply_poll_timeout_sec,
                    cover_letter=cover_letter,
                )

                if result.status == "sent":
                    stats.sent += 1
                elif result.status in ("card_not_found", "timeout", "error", "cover_letter_failed"):
                    stats.failed += 1
                else:
                    stats.skipped += 1

                if on_progress:
                    on_progress({
                        "event": "vacancy_processed",
                        "index": idx,
                        "total": len(vacancies),
                        "vacancy_id": vacancy.vacancy_id,
                        "vacancy_title": vacancy.title,
                        "status": result.status,
                        "cover_letter_sent": result.cover_letter_sent,
                        "stats": {
                            "sent": stats.sent,
                            "skipped": stats.skipped,
                            "failed": stats.failed,
                        },
                    })

                page.wait_for_timeout(apply_delay_ms)

            return stats
        finally:
            try:
                save_session(context, session_file)
            except Exception:
                pass
            context.close()
            browser.close()
