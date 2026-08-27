#!/usr/bin/env python3
"""
BOB Alchimia a Spicchi - monitor de disponibilidad.

Versión preparada para:
- ejecución local con Playwright;
- GitHub Actions usando el Google Chrome ya instalado en el runner.

Comprueba 1..8 personas y envía avisos por ntfy.
No realiza reservas ni rellena datos personales.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
DEBUG_HTML = BASE_DIR / "bob_debug.html"
DEBUG_PNG = BASE_DIR / "bob_debug.png"

ROME = ZoneInfo("Europe/Rome")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"No encuentro {CONFIG_PATH.name}")

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data.setdefault("url", "https://www.bobalchimiaspicchi.com/prenota2.php")
    data.setdefault("party_sizes", list(range(1, 9)))
    data.setdefault("headless", True)
    data.setdefault("timezone", "Europe/Rome")
    data.setdefault("notify_on_first_run", True)
    data.setdefault("notification", {"type": "ntfy", "server": "https://ntfy.sh"})

    # En GitHub se usa un Secret para no publicar el topic.
    topic_from_env = os.environ.get("NTFY_TOPIC", "").strip()
    if topic_from_env:
        data["notification"]["topic"] = topic_from_env

    return data


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"active": [], "initialized": False}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"active": [], "initialized": False}


def save_state(active: set[str]) -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "active": sorted(active),
                "initialized": True,
                "updated_at": datetime.now(ROME).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


def post_text(url: str, body: str, headers: dict | None = None) -> None:
    h = {"Content-Type": "text/plain; charset=utf-8"}
    if headers:
        h.update(headers)

    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers=h,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def notify(config: dict, title: str, message: str) -> None:
    n = config.get("notification", {})
    topic = str(n.get("topic", "")).strip()
    server = str(n.get("server", "https://ntfy.sh")).rstrip("/")

    if not topic:
        raise RuntimeError(
            "Falta NTFY_TOPIC. En GitHub debes crearlo como Repository Secret."
        )

    post_text(
        f"{server}/{topic}",
        message,
        {
            # Mantener ASCII en las cabeceras HTTP para compatibilidad.
            "Title": title,
            "Priority": "high",
            "Tags": "pizza,calendar",
            "Click": config["url"],
        },
    )


async def save_debug(page) -> None:
    try:
        DEBUG_HTML.write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass

    try:
        await page.screenshot(path=str(DEBUG_PNG), full_page=True)
    except Exception:
        pass


async def wait_for_availability_update(page) -> None:
    """
    ResDiary añade la clase 'loading' mientras recalcula la disponibilidad.
    """
    try:
        await page.wait_for_function(
            """() => {
                const el = document.querySelector(
                    '#initial [data-bind*="requestingAvailability"]'
                );
                return !el || !el.classList.contains('loading');
            }""",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        pass

    await page.wait_for_timeout(700)


async def select_party_size(page, size: int) -> None:
    """
    Selector real de ResDiary:
      #party-size-input
        .covers-input.dropdown-selected
        .drop-list li
    """
    root = page.locator("#party-size-input")
    await root.wait_for(state="visible", timeout=15000)

    selected_text = root.locator(".dropdown-selected .form-control")
    current = (await selected_text.inner_text()).strip()

    if current == str(size):
        await wait_for_availability_update(page)
        return

    trigger = root.locator(".covers-input.dropdown-selected")

    # Clic DOM: evita "element is outside of the viewport" causado por
    # las transformaciones/scroll de la página exterior.
    await trigger.evaluate("el => el.click()")

    options = root.locator(".drop-list li")
    exact_option = None

    for i in range(await options.count()):
        item = options.nth(i)
        if (await item.inner_text()).strip() == str(size):
            exact_option = item
            break

    if exact_option is None:
        raise RuntimeError(f"No encuentro la opción {size} en el selector Persone.")

    await exact_option.evaluate("el => el.click()")

    await page.wait_for_function(
        """expected => {
            const el = document.querySelector(
                '#party-size-input .dropdown-selected .form-control'
            );
            return el && el.textContent.trim() === String(expected);
        }""",
        arg=size,
        timeout=8000,
    )

    await wait_for_availability_update(page)


async def extract_available_dates(page) -> set[str]:
    """
    ResDiary marca las fechas no seleccionables con .disabled.
    data-day tiene formato DD/MM/YYYY.
    """
    cells = page.locator(
        '#datepicker td.day[data-action="selectDay"][data-day]:not(.disabled)'
    )

    dates: set[str] = set()

    for i in range(await cells.count()):
        raw = (await cells.nth(i).get_attribute("data-day") or "").strip()

        try:
            dt = datetime.strptime(raw, "%d/%m/%Y")
        except ValueError:
            continue

        dates.add(dt.date().isoformat())

    return dates


async def check_once(config: dict, show_browser: bool = False) -> dict[int, set[str]]:
    async with async_playwright() as p:
        launch_kwargs = {
            "headless": not show_browser,
        }

        # GitHub Actions establece PLAYWRIGHT_CHANNEL=chrome y usa el Chrome
        # preinstalado en ubuntu-latest. En local, si no existe esta variable,
        # Playwright usa el Chromium que hayas instalado.
        channel = os.environ.get("PLAYWRIGHT_CHANNEL", "").strip()
        if channel:
            launch_kwargs["channel"] = channel

        browser = await p.chromium.launch(**launch_kwargs)

        page = await browser.new_page(
            locale="it-IT",
            timezone_id=config.get("timezone", "Europe/Rome"),
            viewport={"width": 1280, "height": 900},
        )

        page.set_default_timeout(10000)
        result: dict[int, set[str]] = {}

        try:
            await page.goto(
                config["url"],
                wait_until="domcontentloaded",
                timeout=30000,
            )

            await page.locator("#party-size-input").wait_for(
                state="visible",
                timeout=20000,
            )

            await wait_for_availability_update(page)

            for size in config["party_sizes"]:
                await select_party_size(page, int(size))
                dates = await extract_available_dates(page)
                result[int(size)] = dates

                label = "persona" if int(size) == 1 else "personas"
                readable = ", ".join(sorted(dates)) if dates else "sin huecos detectados"

                print(
                    f"[{datetime.now(ROME):%Y-%m-%d %H:%M:%S}] "
                    f"{size} {label}: {readable}",
                    flush=True,
                )

            return result

        except Exception:
            await save_debug(page)
            raise

        finally:
            await page.close()
            await browser.close()


def flatten(result: dict[int, set[str]]) -> set[str]:
    return {
        f"{size}|{date}"
        for size, dates in result.items()
        for date in dates
    }


def pretty_date(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d")

    weekdays = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ]

    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]

    return f"{weekdays[d.weekday()]} {d.day} de {months[d.month - 1]}"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--test-notification", action="store_true")
    args = parser.parse_args()

    config = load_config()

    if args.test_notification:
        notify(
            config,
            "BOB monitor: prueba OK",
            "Las notificaciones del monitor de GitHub funcionan correctamente.",
        )
        print("Notificación de prueba enviada.", flush=True)
        return 0

    previous_state = load_state()

    try:
        result = await check_once(config, show_browser=args.show_browser)
    except Exception as e:
        print(
            f"[ERROR] {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    active = flatten(result)
    previous = set(previous_state.get("active", []))
    initialized = bool(previous_state.get("initialized", False))

    new_slots = active - previous

    # En la primera ejecución avisará si ya hay algún hueco.
    if initialized or bool(config.get("notify_on_first_run", True)):
        for item in sorted(new_slots):
            size_s, date_s = item.split("|", 1)
            size = int(size_s)
            label = "persona" if size == 1 else "personas"

            notify(
                config,
                f"BOB: hueco para {size} {label}",
                (
                    f"Se ha detectado una fecha disponible para "
                    f"{size} {label}: {pretty_date(date_s)}.\n"
                    f"Abre la web cuanto antes. "
                    f"El monitor no reserva automáticamente."
                ),
            )

            print(
                f"ALERTA enviada: {size} {label} - {date_s}",
                flush=True,
            )

    save_state(active)
    print("Estado guardado correctamente.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
