"""
fracttal_github.py
==================
Script adaptado para correr en GitHub Actions.
Las credenciales se leen desde variables de entorno (Secrets de GitHub).
El CSV se guarda en la carpeta raíz del repositorio.

NO modifiques las credenciales aquí — configúralas como Secrets en GitHub.
"""

import requests
import csv
import os
import asyncio
from datetime import datetime, timedelta
import uuid
from playwright.async_api import async_playwright

# ─────────────────────────────────────────────
#  CREDENCIALES — se leen desde GitHub Secrets
# ─────────────────────────────────────────────
USUARIO   = os.environ["FRACTTAL_USUARIO"]
PASSWORD  = os.environ["FRACTTAL_PASSWORD"]

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
URL_LOGIN      = "https://app.fracttal.com/signin"
URL_API        = "https://app.fracttal.com/rpc/proxy"

FECHA_INICIO   = "2023-06-25"
FECHA_FIN      = datetime.today().strftime("%Y-%m-%d")
DIAS_POR_LOTE  = 60

# Guarda el CSV en la raíz del repositorio
ARCHIVO_FINAL  = "OTs_Fracttal.csv"

COLUMNAS = [
    ("wo_folio",                        "ID Orden de Trabajo"),
    ("creation_date",                   "Fecha de Creación"),
    ("initial_date",                    "Fecha Inicio"),
    ("final_date",                      "Fecha Fin"),
    ("wo_final_date",                   "Fecha Cierre OT"),
    ("review_date",                     "Fecha Revisión"),
    ("description",                     "Descripción OT"),
    ("task_status",                     "Estado"),
    ("types_description",               "Tipo de OT"),
    ("tasks_log_types_description",     "Tipo de Tarea"),
    ("priorities_description",          "Prioridad"),
    ("code",                            "Código Activo"),
    ("items_log_description",           "Activo"),
    ("parent_description",              "Ubicación"),
    ("groups_description",              "Grupo"),
    ("groups_1_description",            "Subgrupo 1"),
    ("groups_2_description",            "Subgrupo 2"),
    ("costs_center_description",        "Centro de Costo"),
    ("personnel_description",           "Responsable"),
    ("user_assigned",                   "Usuario Asignado"),
    ("created_by",                      "Creado Por"),
    ("requested_by",                    "Solicitado Por"),
    ("validated_by_description",        "Validado Por"),
    ("completed_percentage",            "% Completado"),
    ("duration",                        "Duración Estimada (seg)"),
    ("real_duration",                   "Duración Real (seg)"),
    ("total_cost_task",                 "Costo Total"),
    ("stop_assets",                     "Fuera de Servicio"),
    ("caused_disruption",               "Causó Interrupción"),
    ("note",                            "Nota"),
    ("task_note",                       "Nota Tarea"),
    ("labels",                          "Etiquetas"),
]
# ─────────────────────────────────────────────


async def obtener_token_playwright():
    print("→ Iniciando login automático...")
    token_capturado = {"value": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        async def capturar_token(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and len(auth) > 50:
                token_capturado["value"] = auth.replace("Bearer ", "")

        page.on("request", capturar_token)

        await page.goto(URL_LOGIN, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.wait_for_selector('input[name="email"]', timeout=10000)

        await page.click('input[name="email"]')
        await page.keyboard.type(USUARIO, delay=50)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)
        await page.click('input[name="password"]')
        await page.keyboard.type(PASSWORD, delay=50)
        await page.wait_for_timeout(800)

        for _ in range(5):
            habilitado = await page.evaluate("""
                () => {
                    var btn = document.querySelector('button[data-cy="next-button"]');
                    return btn ? !btn.disabled : false;
                }
            """)
            if habilitado:
                break
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(600)

        await page.click('button[data-cy="next-button"]')

        for _ in range(20):
            await page.wait_for_timeout(1000)
            if "signin" not in page.url and token_capturado["value"]:
                break

        await browser.close()

    if not token_capturado["value"]:
        raise Exception("No se pudo capturar el token. Verifica las credenciales.")

    print("   ✓ Token obtenido")
    return token_capturado["value"]


def generar_rangos(fecha_inicio, fecha_fin, dias):
    rangos = []
    inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    fin    = datetime.strptime(fecha_fin,    "%Y-%m-%d")
    actual = inicio
    while actual <= fin:
        siguiente = min(actual + timedelta(days=dias - 1), fin)
        rangos.append((actual, siguiente))
        actual = siguiente + timedelta(days=1)
    return rangos


def obtener_ots_rango(token, fecha_desde, fecha_hasta):
    desde_iso = fecha_desde.strftime("%Y-%m-%dT05:00:00.000Z")
    hasta_iso  = (fecha_hasta + timedelta(days=1)).strftime("%Y-%m-%dT04:59:59.999Z")

    payload = [{
        "id": str(uuid.uuid4()),
        "jsonrpc": "2.0",
        "method": "tasks.work_orders_grid_list",
        "params": {
            "filter": [
                {"operator": "gt", "property": "creation_date", "value": desde_iso},
                {"operator": "lt", "property": "creation_date", "value": hasta_iso}
            ],
            "is_tree": False,
            "limit": 200,
            "node": None,
            "page": 1,
            "sort": [],
            "start": 0
        }
    }]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    r = requests.post(URL_API, json=payload, headers=headers, timeout=30)

    if r.status_code == 401:
        raise Exception("Token inválido o expirado.")

    data = r.json()

    for item in data:
        result = item.get("result", {})
        if isinstance(result, dict):
            registros = (result.get("data") or result.get("rows") or
                        result.get("results") or result.get("items") or [])
            total     = result.get("total") or result.get("count") or len(registros)
            return registros, total
        elif isinstance(result, list):
            return result, len(result)

    return [], 0


def limpiar_valor(val):
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Sí" if val else "No"
    if isinstance(val, list):
        return ""
    if isinstance(val, str):
        if len(val) > 10 and "T" in val and val[4] == "-":
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass
        val = val.replace("\n", " ").replace("\r", " ").strip()
        return val
    return str(val)


def main():
    token = asyncio.run(obtener_token_playwright())

    rangos = generar_rangos(FECHA_INICIO, FECHA_FIN, DIAS_POR_LOTE)
    print(f"\nTotal lotes: {len(rangos)}  ({FECHA_INICIO} → {FECHA_FIN})\n")

    todos = []
    campos_api  = [c[0] for c in COLUMNAS]
    nombres_es  = [c[1] for c in COLUMNAS]

    for i, (desde, hasta) in enumerate(rangos, start=1):
        print(f"── Lote {i}/{len(rangos)}: {desde.strftime('%d/%m/%Y')} → {hasta.strftime('%d/%m/%Y')}", end="")
        registros, total = obtener_ots_rango(token, desde, hasta)
        print(f"  →  {total} OTs")

        if total > 200:
            print(f"   ⚠ ATENCIÓN: Hay {total} OTs — se pierden {total-200}. Reduce DIAS_POR_LOTE a 15.")

        todos.extend(registros)

    if not todos:
        print("\n⚠ No se obtuvieron registros.")
        return

    vistos = set()
    unicos = []
    for r in todos:
        key = r.get("wo_folio", r.get("id_work_order", str(r)))
        if key not in vistos:
            vistos.add(key)
            unicos.append(r)

    print(f"\nTotal OTs únicas: {len(unicos)}")

    with open(ARCHIVO_FINAL, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(nombres_es)
        for r in unicos:
            fila = [limpiar_valor(r.get(campo)) for campo in campos_api]
            writer.writerow(fila)

    print(f"✅ Archivo guardado: {ARCHIVO_FINAL}")


if __name__ == "__main__":
    main()
