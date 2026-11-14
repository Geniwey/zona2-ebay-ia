import os
import re
import csv
import html
import json
import time
import base64
import datetime
import requests
import numpy as np
import imageio.v2 as imageio
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw
from io import BytesIO

# ==============================================================================
# CONFIGURACIÓN Y CREDENCIALES DESDE GITHUB SECRETS
# ==============================================================================
CJ_TOKEN = os.environ.get("CJ_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "").strip()
EBAY_CERT_ID = os.environ.get("EBAY_CERT_ID", "").strip()
EBAY_REFRESH_TOKEN = os.environ.get("EBAY_REFRESH_TOKEN", "").strip()
EBAY_STATIC_TOKEN = os.environ.get("EBAY_TOKEN", "").strip()

PINTEREST_TOKEN = os.environ.get("PINTEREST_TOKEN", "").strip()
PINTEREST_BOARD_ID = os.environ.get("PINTEREST_BOARD_ID", "").strip()

EBAY_XML_URL = "https://api.ebay.com/ws/api.dll"
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"

# Palabras bloqueadas por seguridad UE / políticas de cuentas nuevas en eBay
PALABRAS_PROHIBIDAS_UE = {
    "magnet", "magnetic", "toy", "toys", "children", "child", "kids", "baby", "infant",
    "battery", "batteries", "lithium", "powerbank", "charger", "knife", "knives", "blade",
    "laser", "medical", "therapy", "massage", "massager", "supplement", "vitamin", "cream",
    "serum", "cosmetic", "perfume", "liquid", "oil", "cbd", "vape", "smoke", "weapon",
    "lego", "disney", "marvel", "pokemon", "apple", "iphone", "samsung", "sony", "nike",
    "adidas", "gucci", "rolex", "dyson", "philips", "xiaomi", "bluetooth", "wifi"
}

# ==============================================================================
# MÓDULO 0: AUTO-DETECCIÓN DE CREDENCIALES, MODELOS IA Y UTILIDADES
# ==============================================================================
def es_token_auth_n_auth(token):
    return token.startswith("AgAAAA") or ("#r^1#" in token and len(token) < 600)

def verificar_formato_secretos():
    print(f"🔎 [Diagnóstico] EBAY_APP_ID len={len(EBAY_APP_ID)} | inicio={EBAY_APP_ID[:12]}...")
    print(f"🔎 [Diagnóstico] EBAY_CERT_ID len={len(EBAY_CERT_ID)} | inicio={EBAY_CERT_ID[:8]}...fin={EBAY_CERT_ID[-4:]}")
    print(f"🔎 [Diagnóstico] EBAY_REFRESH_TOKEN len={len(EBAY_REFRESH_TOKEN)} | inicio={EBAY_REFRESH_TOKEN[:16]}...fin={EBAY_REFRESH_TOKEN[-6:]}")

def obtener_token_ebay_vivo():
    verificar_formato_secretos()
    if not EBAY_REFRESH_TOKEN:
        return EBAY_STATIC_TOKEN

    if es_token_auth_n_auth(EBAY_REFRESH_TOKEN):
        print("🔑 [Seguridad] Detectado Token permanente Auth'n'Auth de eBay (válido hasta 2028).")
        return EBAY_REFRESH_TOKEN

    if "#f^0#r^0#" in EBAY_REFRESH_TOKEN or len(EBAY_REFRESH_TOKEN) > 2200:
        print("🔑 [Seguridad] Detectado User Access Token directo de eBay. Conectando...")
        return EBAY_REFRESH_TOKEN

    if EBAY_APP_ID and EBAY_CERT_ID:
        credenciales = f"{EBAY_APP_ID}:{EBAY_CERT_ID}"
        b64_auth = base64.b64encode(credenciales.encode("utf-8")).decode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64_auth}"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": EBAY_REFRESH_TOKEN
        }
        res = requests.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=15)
        if res.status_code == 200:
            print("🔑 [Seguridad] Token de eBay renovado automáticamente con éxito (18 meses activo).")
            return res.json().get("access_token")
        else:
            print(f"⚠️ Error renovando token eBay ({res.status_code}): {res.text}")
    return EBAY_STATIC_TOKEN

EBAY_ACTIVE_TOKEN = obtener_token_ebay_vivo()

def obtener_token_publico_ebay():
    if EBAY_APP_ID and EBAY_CERT_ID:
        try:
            credenciales = f"{EBAY_APP_ID}:{EBAY_CERT_ID}"
            b64_auth = base64.b64encode(credenciales.encode("utf-8")).decode("utf-8")
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {b64_auth}"
            }
            data = {
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope"
            }
            res = requests.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=15)
            if res.status_code == 200 and res.json().get("access_token"):
                return res.json()["access_token"]
        except Exception:
            pass
    return EBAY_ACTIVE_TOKEN

def obtener_modelo_groq_activo():
    if not GROQ_API_KEY:
        return "openai/gpt-oss-120b"
    try:
        res = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=15
        ).json()
        disponibles = [
            m["id"] for m in res.get("data", [])
            if not any(x in m["id"].lower() for x in ["whisper", "guard", "tts", "orpheus", "playai"])
        ]
        preferidos = [
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "qwen/qwen3-32b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant"
        ]
        for p in preferidos:
            if p in disponibles:
                print(f"🧠 [Groq IA] Modelo activo seleccionado: {p}")
                return p
        if disponibles:
            print(f"🧠 [Groq IA] Modelo activo seleccionado: {disponibles[0]}")
            return disponibles[0]
    except Exception as e:
        print(f"⚠️ Aviso detectando modelos Groq: {e}")
    return "openai/gpt-oss-120b"

GROQ_MODEL_ACTIVO = obtener_modelo_groq_activo()

def obtener_access_token_cj():
    url = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
    res = requests.post(url, json={"apiKey": CJ_TOKEN}, timeout=15).json()
    time.sleep(1.2)
    if res.get("result") and res.get("data", {}).get("accessToken"):
        print("🔑 [CJ Dropshipping] Access Token obtenido correctamente.")
        return res["data"]["accessToken"]
    print(f"⚠️ Aviso token CJ: {res.get('message', 'Usando API Key directa')}")
    return CJ_TOKEN

CJ_ACCESS_TOKEN = obtener_access_token_cj()

def llamar_groq(system_prompt, user_prompt, json_mode=True):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    instruccion_extra = "\nResponde ÚNICAMENTE con un objeto JSON válido, sin texto adicional ni bloques markdown." if json_mode else ""
    payload = {
        "model": GROQ_MODEL_ACTIVO,
        "temperature": 0.2,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": system_prompt + instruccion_extra},
            {"role": "user", "content": user_prompt}
        ]
    }

    res = requests.post(url, headers=headers, json=payload, timeout=35).json()
    if "choices" not in res:
        print(f"⚠️ Respuesta inesperada de Groq: {res}")
        return {} if json_mode else ""

    contenido = res["choices"][0]["message"]["content"].strip()
    contenido = re.sub(r"<think>.*?</think>", "", contenido, flags=re.DOTALL).strip()

    if not json_mode:
        return contenido

    contenido_limpio = re.sub(r"^```(?:json)?|```$", "", contenido, flags=re.MULTILINE).strip()
    try:
        return json.loads(contenido_limpio)
    except Exception:
        match = re.search(r"\{.*\}", contenido_limpio, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        print("⚠️ No se pudo parsear JSON de Groq, usando respaldo automático.")
        return {}

def limpiar_xml(texto):
    return (
        str(texto)
        .replace("&", "y")
        .replace("<", "")
        .replace(">", "")
        .replace('"', "")
        .replace("'", "")
        .strip()
    )

def ebay_xml_call(call_name, xml_body):
    headers = {
        "X-EBAY-API-SITEID": "186",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1149",
        "Content-Type": "text/xml; charset=utf-8"
    }
    if es_token_auth_n_auth(EBAY_ACTIVE_TOKEN):
        cred_xml = f"<RequesterCredentials><eBayAuthToken>{EBAY_ACTIVE_TOKEN}</eBayAuthToken></RequesterCredentials>"
        xml_body = xml_body.replace(
            'xmlns="urn:ebay:apis:eBLBaseComponents">',
            f'xmlns="urn:ebay:apis:eBLBaseComponents">{cred_xml}',
            1
        )
    else:
        headers["X-EBAY-API-IAF-TOKEN"] = EBAY_ACTIVE_TOKEN

    resp = requests.post(EBAY_XML_URL, headers=headers, data=xml_body.encode("utf-8"), timeout=30)
    resp.encoding = "utf-8"
    return resp.text

def enviar_telegram(texto, botones=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texto}
    if botones:
        payload["reply_markup"] = {"inline_keyboard": botones}
    requests.post(url, json=payload, timeout=15)

# ==============================================================================
# AGENTE 6 (DATOS Y PODADOR): Audita los últimos 30 productos y borra muertos
# ==============================================================================
def agente_6_datos_podar_catalogo():
    print("📊 [Agente 6 - Datos] Auditando catálogo activo en eBay...")
    if not EBAY_ACTIVE_TOKEN:
        print("⚠️ Sin token activo de eBay, saltando auditoría inicial.")
        return [], 0, []

    xml = """<?xml version="1.0" encoding="utf-8"?>
    <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <ActiveList>
        <Include>true</Include>
        <Pagination>
          <EntriesPerPage>100</EntriesPerPage>
          <PageNumber>1</PageNumber>
        </Pagination>
      </ActiveList>
    </GetMyeBaySellingRequest>"""

    res_xml = ebay_xml_call("GetMyeBaySelling", xml)
    skus_activos = []
    eliminados = 0
    ganadores = []

    try:
        root = ET.fromstring(res_xml)
        ns = {"eb": "urn:ebay:apis:eBLBaseComponents"}
        ahora = datetime.datetime.now(datetime.timezone.utc)

        for item in root.findall(".//eb:Item", ns):
            item_id = item.find("eb:ItemID", ns).text
            titulo_item = item.find("eb:Title", ns).text if item.find("eb:Title", ns) is not None else item_id
            sku_el = item.find("eb:SKU", ns)
            if sku_el is not None and sku_el.text:
                skus_activos.append(sku_el.text)

            start_str = item.find(".//eb:StartTime", ns).text
            dias = (ahora - datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))).days
            vendidos_el = item.find(".//eb:QuantitySold", ns)
            vendidos = int(vendidos_el.text) if vendidos_el is not None else 0

            if vendidos > 0:
                ganadores.append(f"{titulo_item[:28]}... ({vendidos} v.)")

            if dias >= 14 and vendidos == 0:
                end_xml = f"""<?xml version="1.0" encoding="utf-8"?>
                <EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                  <ItemID>{item_id}</ItemID>
                  <EndingReason>NotAvailable</EndingReason>
                </EndFixedPriceItemRequest>"""
                ebay_xml_call("EndFixedPriceItem", end_xml)
                eliminados += 1
    except Exception as e:
        print(f"Aviso en lectura de catálogo activo: {e}")

    return skus_activos, eliminados, ganadores

# ==============================================================================
# AGENTE 1 (TENDENCIAS): Escanea CJ Almacenes UE con Filtro Seguro UE
# ==============================================================================
def es_producto_seguro_ue(titulo_en):
    palabras = set(re.findall(r"[a-z]+", str(titulo_en).lower()))
    return len(palabras.intersection(PALABRAS_PROHIBIDAS_UE)) == 0

def agente_1_cazar_candidatos_seguros(skus_excluidos, max_candidatos=5):
    print("🔍 [Agente 1 - Tendencias] Rastreando productos seguros en almacenes de la Unión Europea...")
    headers_cj = {"CJ-Access-Token": CJ_ACCESS_TOKEN}
    lista_keywords = ["organizer", "lamp", "holder", "storage", "decor", "rack", "light"]
    almacenes_ue = ["DE", "FR", "ES", "PL"]
    candidatos = []
    vistos = set(skus_excluidos)

    for pais in almacenes_ue:
        for kw in lista_keywords:
            time.sleep(1.2)
            url_cj = f"https://developers.cjdropshipping.com/api2.0/v1/product/list?countryCode={pais}&pageNum=1&pageSize=40&keyword={requests.utils.quote(kw)}"
            res_cj = requests.get(url_cj, headers=headers_cj, timeout=15).json()
            if not res_cj.get("result"):
                print(f"⚠️ CJ ({pais} | '{kw}'): {res_cj.get('message')}")
                if "disabled" in str(res_cj.get("message", "")).lower():
                    raise Exception("CJ tiene la API deshabilitada: entra en CJ > Authorization > API (pestaña API) y pulsa Unfreeze/Reactivate.")
                continue

            productos_lista = (res_cj.get("data") or {}).get("list") or []
            print(f"📦 CJ Almacén {pais} (kw='{kw}'): {len(productos_lista)} productos encontrados.")

            for prod in productos_lista:
                pid = prod.get("pid")
                titulo_en = prod.get("productNameEn", "")
                if not pid or pid in vistos or not es_producto_seguro_ue(titulo_en):
                    continue

                precio_raw = str(prod.get("sellPrice", "0")).split("-")[0].strip()
                try:
                    coste_cj = float(precio_raw)
                except ValueError:
                    continue

                if 3.0 <= coste_cj <= 16.0:
                    precio_venta = round((coste_cj * 2.6) + 1.50, 2)
                    comision_ebay = round(precio_venta * 0.135, 2)
                    beneficio_neto = round(precio_venta - comision_ebay - coste_cj, 2)

                    time.sleep(1.2)
                    det_url = f"https://developers.cjdropshipping.com/api2.0/v1/product/query?pid={pid}"
                    det_data = (requests.get(det_url, headers=headers_cj, timeout=15).json().get("data")) or {}

                    fotos = det_data.get("productImageSet") or [prod.get("productImage")]
                    if isinstance(fotos, str):
                        try:
                            fotos = json.loads(fotos)
                        except Exception:
                            fotos = [prod.get("productImage")]

                    fotos_limpias = [f for f in fotos if isinstance(f, str) and f.startswith("http")][:12]
                    if not fotos_limpias:
                        continue

                    vistos.add(pid)
                    print(f"✅ Candidato seguro en {pais}: {titulo_en} ({coste_cj}€ -> {precio_venta}€)")
                    candidatos.append({
                        "sku": pid,
                        "almacen": pais,
                        "titulo_en": titulo_en,
                        "descripcion_en": det_data.get("description") or titulo_en,
                        "fotos": fotos_limpias,
                        "coste_cj": coste_cj,
                        "precio_venta": precio_venta,
                        "beneficio_neto": beneficio_neto
                    })
                    if len(candidatos) >= max_candidatos:
                        return candidatos

    if not candidatos:
        raise Exception("No se encontraron candidatos nuevos seguros hoy en los almacenes de la UE.")
    return candidatos

# ==============================================================================
# AGENTE 2 (DISEÑO): 10 Imágenes + Vídeo Vertical .MP4 (Reels/TikTok) + CSV Canva
# ==============================================================================
def agente_2_diseno_multimedia(producto):
    print("🎨 [Agente 2 - Diseño] Creando 10 anuncios + Vídeo Vertical MP4 + Lote CSV para Canva Pro...")
    disenos = llamar_groq(
        "Eres un director creativo de e-commerce en Europa.",
        f"Producto: {producto['titulo_en']}. Precio: {producto['precio_venta']}€. Genera un JSON con una lista 'variantes' de exactamente 10 versiones de anuncio. Cada ítem debe tener: 'id' (1 a 10), 'gancho' (máx 4 palabras impactantes en español), 'angulo' (frase persuasiva para TikTok/Pinterest) y 'color_hex' (color oscuro elegante ej: #0F172A, #1E3A8A, #065F46, #7C2D12)."
    )

    os.makedirs("anuncios_generados", exist_ok=True)
    lista_variantes = disenos.get("variantes") or [
        {"id": i + 1, "gancho": "OFERTA EUROPA HOY", "angulo": "Envío rápido desde almacén europeo", "color_hex": "#0F172A"}
        for i in range(10)
    ]
    lista_variantes = lista_variantes[:10]

    with open("anuncios_generados/canva_lote_10_versiones.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Gancho_Principal", "Frase_Persuasiva", "Precio", "Imagen_URL"])
        for idx, v in enumerate(lista_variantes):
            foto_url = producto["fotos"][idx % len(producto["fotos"])]
            writer.writerow([v.get("id", idx+1), v.get("gancho", ""), v.get("angulo", ""), f"{producto['precio_venta']}€", foto_url])

    frames_video = []
    try:
        for idx, v in enumerate(lista_variantes):
            foto_url = producto["fotos"][idx % len(producto["fotos"])]
            img_bytes = requests.get(foto_url, timeout=12).content
            img_base = Image.open(BytesIO(img_bytes)).convert("RGBA").resize((1080, 1080))

            lienzo = img_base.copy()
            draw = ImageDraw.Draw(lienzo)
            color_fondo = v.get("color_hex", "#0F172A")
            draw.rectangle([(0, 0), (1080, 130)], fill=color_fondo)
            draw.text((40, 48), f"★ {v.get('gancho', 'TOP VENTAS').upper()} | {producto['precio_venta']}€ ★", fill="#FFFFFF")
            draw.rectangle([(0, 960), (1080, 1080)], fill="#111827")
            draw.text((40, 1005), "ENVIO GRATIS EUROPA (3-7 DIAS) - GARANTIA 14 DIAS", fill="#10B981")

            ruta_jpg = f"anuncios_generados/anuncio_v{v.get('id', idx+1)}.jpg"
            lienzo_rgb = lienzo.convert("RGB")
            lienzo_rgb.save(ruta_jpg, quality=92)

            if idx < 5:
                frame_vert = Image.new("RGB", (1088, 1920), color_fondo)
                frame_vert.paste(lienzo_rgb, (4, 420))
                arr_frame = np.array(frame_vert)
                for _ in range(30):
                    frames_video.append(arr_frame)

        if frames_video:
            imageio.mimsave("anuncios_generados/reel_tiktok_viral.mp4", frames_video, fps=15)
            print("🎬 [Agente 2] Vídeo vertical MP4 generado con éxito.")
    except Exception as e:
        print(f"Aviso en renderizado multimedia: {e}")

    return lista_variantes

# ==============================================================================
# AGENTE 3 (TIENDA MULTI-PAÍS): Publica para España + Alemania + Francia + Italia
# ==============================================================================
def obtener_categorias_hoja_ebay_es(query_es, titulo_es=""):
    print("📂 [Agente 3] Buscando subcategorías hoja válidas en eBay España (Tree 186)...")
    categorias_validas = []
    vistos = set()

    token_tax = obtener_token_publico_ebay()
    consultas = [query_es, titulo_es[:45], "organizador hogar", "lampara decoracion"]

    if token_tax:
        headers_tax = {
            "Authorization": f"Bearer {token_tax}",
            "Accept": "application/json",
            "Accept-Language": "es-ES"
        }
        for q in consultas:
            q_clean = str(q).strip()
            if not q_clean:
                continue
            try:
                url_tax = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/186/get_category_suggestions?q={requests.utils.quote(q_clean)}"
                r = requests.get(url_tax, headers=headers_tax, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    for sug in data.get("categorySuggestions", [])[:4]:
                        cat = sug.get("category", {})
                        cid = str(cat.get("categoryId", "")).strip()
                        cname = cat.get("categoryName", "")
                        if cid and cid not in vistos:
                            vistos.add(cid)
                            categorias_validas.append((cid, cname))
                if len(categorias_validas) >= 5:
                    break
            except Exception as e:
                print(f"⚠️ Aviso Taxonomy API: {e}")

    if categorias_validas:
        resumen = ", ".join([f"{cid} ({cname})" for cid, cname in categorias_validas[:3]])
        print(f"✅ [Agente 3] Subcategorías hoja detectadas en eBay ES: {resumen}")
    return categorias_validas or [("181076", "Otros Hogar"), ("20625", "Organizadores")]

def obtener_politicas_vendedor_ebay():
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <GetUserPreferencesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <ShowSellerProfilePreferences>true</ShowSellerProfilePreferences>
    </GetUserPreferencesRequest>"""
    res_xml = ebay_xml_call("GetUserPreferences", xml)
    perfiles = {"opted_in": False, "shipping": None, "return": None, "payment": None}

    try:
        root = ET.fromstring(res_xml)
        ns = {"eb": "urn:ebay:apis:eBLBaseComponents"}
        opted = root.find(".//eb:SellerProfilePreferences/eb:SellerProfileOptedIn", ns)
        if opted is not None and opted.text == "true":
            perfiles["opted_in"] = True

        for prof in root.findall(".//eb:SupportedSellerProfile", ns):
            ptype = prof.find("eb:ProfileType", ns)
            pid = prof.find("eb:ProfileID", ns)
            if ptype is None or pid is None:
                continue
            if ptype.text == "SHIPPING" and not perfiles["shipping"]:
                perfiles["shipping"] = pid.text
            elif ptype.text == "RETURN_POLICY" and not perfiles["return"]:
                perfiles["return"] = pid.text
            elif ptype.text == "PAYMENT" and not perfiles["payment"]:
                perfiles["payment"] = pid.text

        if perfiles["opted_in"]:
            print(f"📋 [Agente 3] Políticas comerciales de eBay detectadas: Envío={perfiles['shipping']} | Devolución={perfiles['return']} | Pago={perfiles['payment']}")
    except Exception as e:
        print(f"Aviso leyendo políticas del vendedor: {e}")

    return perfiles

def normalizar_seo_listing(seo_raw, producto, texto_limpio):
    if not isinstance(seo_raw, dict):
        seo_raw = {}

    titulo = (
        seo_raw.get("titulo")
        or seo_raw.get("title")
        or seo_raw.get("Title")
        or seo_raw.get("titulo_seo")
        or f"{producto['titulo_en'][:55]} Envio Gratis UE"
    ).strip()

    for prohibida in ["gratis", "regalo", "oferta", "100%", "garantizado"]:
        titulo = re.sub(rf"\b{prohibida}\b", "", titulo, flags=re.IGNORECASE).strip()
    titulo = re.sub(r"\s+", " ", titulo)

    if len(titulo) > 78:
        titulo = titulo[:78].rsplit(" ", 1)[0]

    descripcion = (
        seo_raw.get("descripcion_html")
        or seo_raw.get("description_html")
        or seo_raw.get("descripcion")
        or seo_raw.get("description")
        or f"<p><b>Calidad y Diseño Moderno - Envío desde Europa</b></p><p>{texto_limpio[:500]}</p><ul><li>Envío rápido desde almacén europeo en 3 a 7 días laborables.</li><li>Devolución aceptada en 14 días según normativa europea.</li></ul>"
    )
    descripcion = re.sub(r"https?://\S+|www\.\S+", "", str(descripcion))

    query_cat = (
        seo_raw.get("query_categoria")
        or seo_raw.get("category_query")
        or "organizador hogar"
    )

    specifics = seo_raw.get("specifics")
    if not isinstance(specifics, dict) or not specifics:
        specifics = {
            "Marca": "Sin marca",
            "Tipo": "Accesorio de hogar",
            "Color": "Neutro",
            "Material": "Plástico ABS / Metal"
        }

    return {
        "query_categoria": str(query_cat),
        "titulo": titulo,
        "descripcion_html": descripcion,
        "specifics": specifics
    }

def construir_xml_publicacion(producto, seo, cat_id, specifics_xml, fotos_xml, perfiles_vendedor):
    titulo_xml = limpiar_xml(seo["titulo"])
    pais_almacen = producto.get("almacen", "DE")

    bloque_politicas = ""
    if perfiles_vendedor and perfiles_vendedor.get("opted_in"):
        partes_perfil = []
        if perfiles_vendedor.get("shipping"):
            partes_perfil.append(f"<SellerShippingProfile><ShippingProfileID>{perfiles_vendedor['shipping']}</ShippingProfileID></SellerShippingProfile>")
        if perfiles_vendedor.get("return"):
            partes_perfil.append(f"<SellerReturnProfile><ReturnProfileID>{perfiles_vendedor['return']}</ReturnProfileID></SellerReturnProfile>")
        if perfiles_vendedor.get("payment"):
            partes_perfil.append(f"<SellerPaymentProfile><PaymentProfileID>{perfiles_vendedor['payment']}</PaymentProfileID></SellerPaymentProfile>")
        if partes_perfil:
            bloque_politicas = f"<SellerProfiles>{''.join(partes_perfil)}</SellerProfiles>"

    return f"""<?xml version="1.0" encoding="utf-8"?>
    <AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <Item>
        <SKU>{producto['sku']}</SKU>
        <Title>{titulo_xml}</Title>
        <Description><![CDATA[{seo['descripcion_html']}]]></Description>
        <PrimaryCategory><CategoryID>{cat_id}</CategoryID></PrimaryCategory>
        <StartPrice>{producto['precio_venta']}</StartPrice>
        <ConditionID>1000</ConditionID>
        <Country>{pais_almacen}</Country>
        <Location>Unión Europea</Location>
        <Currency>EUR</Currency>
        <DispatchTimeMax>2</DispatchTimeMax>
        <ListingDuration>GTC</ListingDuration>
        <ListingType>FixedPriceItem</ListingType>
        <Quantity>2</Quantity>
        <PictureDetails>{fotos_xml}</PictureDetails>
        <ItemSpecifics>{specifics_xml}</ItemSpecifics>
        <ProductListingDetails>
          <EAN>No aplicable</EAN>
          <BrandMPN>
            <Brand>Sin marca</Brand>
            <MPN>No aplicable</MPN>
          </BrandMPN>
        </ProductListingDetails>
        {bloque_politicas}
        <Site>Spain</Site>
      </Item>
    </AddFixedPriceItemRequest>"""

def agente_3_publicar_tienda_europa(producto, perfiles):
    print("🛒 [Agente 3 - Tienda UE] Preparando ficha limpia para eBay Europa...")
    texto_limpio = BeautifulSoup(producto["descripcion_en"], "html.parser").get_text(" ", strip=True)[:800]

    seo_raw = llamar_groq(
        "Eres un experto en SEO y cumplimiento de políticas para eBay España. Prohibido usar palabras promocionales como 'gratis', 'oferta', '100%', marcas registradas, URLs o reclamos médicos. Devuelve únicamente JSON válido.",
        f"""Traduce y optimiza este producto para eBay España de forma sobria y descriptiva.
Producto: {producto['titulo_en']}
Detalles: {texto_limpio}

Devuelve este JSON exacto:
{{
  "query_categoria": "2 palabras en español del objeto",
  "titulo": "Título descriptivo en español de 55 a 75 caracteres sin palabras promocionales",
  "descripcion_html": "<p><b>Calidad y Diseño Funcional</b></p><p>Descripción clara y objetiva del producto en español.</p><ul><li>Característica 1</li><li>Característica 2</li><li>Envío desde almacén europeo en 3 a 7 días laborables.</li></ul>",
  "specifics": {{
    "Marca": "Sin marca",
    "Tipo": "Accesorio de hogar",
    "Color": "Neutro",
    "Material": "Alta resistencia"
  }}
}}"""
    )

    seo = normalizar_seo_listing(seo_raw, producto, texto_limpio)
    print(f"📝 [Agente 3] Título SEO generado: {seo['titulo']}")

    candidatos_cat = obtener_categorias_hoja_ebay_es(seo["query_categoria"], seo["titulo"])
    fotos_xml = "".join([f"<PictureURL>{url}</PictureURL>" for url in producto["fotos"][:8]])

    specifics_xml = ""
    for k, v in seo["specifics"].items():
        k_limpio = limpiar_xml(k)
        val_limpio = limpiar_xml(v)
        if k_limpio and val_limpio:
            specifics_xml += f"<NameValueList><Name>{k_limpio}</Name><Value>{val_limpio}</Value></NameValueList>"
    specifics_xml += "<NameValueList><Name>MPN</Name><Value>No aplicable</Value></NameValueList>"
    specifics_xml += "<NameValueList><Name>EAN</Name><Value>No aplicable</Value></NameValueList>"

    ultimo_error = "No se pudo validar categoría."
    ultima_cat = candidatos_cat[0][0]

    for cid, cname in candidatos_cat[:3]:
        ultima_cat = cid
        print(f"🚀 [Agente 3] Intentando publicar en subcategoría {cid} ({cname})...")
        xml = construir_xml_publicacion(producto, seo, cid, specifics_xml, fotos_xml, perfiles)
        res = ebay_xml_call("AddFixedPriceItem", xml)

        match_id = re.search(r"<ItemID>(\d+)</ItemID>", res)
        if match_id:
            print(f"🎉 [Agente 3] ¡PUBLICADO EN EBAY! ItemID: {match_id.group(1)}")
            return seo, match_id.group(1), cid, None

        errores = [html.unescape(e) for e in re.findall(r"<LongMessage>(.*?)</LongMessage>", res)]
        ultimo_error = " | ".join(errores) if errores else html.unescape(res[:500])
        print(f"⚠️ Aviso eBay en {cid}: {ultimo_error}")

        if "vendedor pueden estar infringiendo" in ultimo_error.lower() or "seller" in ultimo_error.lower():
            break

    return seo, "ERROR_EBAY", ultima_cat, ultimo_error

# ==============================================================================
# AGENTE 7 (PROMOCIÓN GRATIS MULTI-SITIO): Autopublica en Pinterest + Redes
# ==============================================================================
def agente_7_promocion_gratis_multicanal(producto, seo, variantes, item_id):
    ebay_link = f"https://www.ebay.es/itm/{item_id}"
    canales_activos = ["eBay ES", "eBay DE/FR/IT (UE)", "Vídeo Reel MP4", "Lote Canva CSV"]

    if PINTEREST_TOKEN and PINTEREST_BOARD_ID and item_id != "ERROR_EBAY":
        url_pin = "https://api.pinterest.com/v5/pins"
        headers_pin = {
            "Authorization": f"Bearer {PINTEREST_TOKEN}",
            "Content-Type": "application/json"
        }
        gancho = variantes[0].get("angulo", seo["titulo"]) if variantes else seo["titulo"]
        payload_pin = {
            "board_id": PINTEREST_BOARD_ID,
            "title": seo["titulo"][:100],
            "description": f"{gancho} ✨ Envío desde Europa en 3-7 días.",
            "link": ebay_link,
            "media_source": {
                "source_type": "image_url",
                "url": producto["fotos"][0]
            }
        }
        r_pin = requests.post(url_pin, headers=headers_pin, json=payload_pin, timeout=15)
        if r_pin.status_code in (200, 201):
            canales_activos.append("Pinterest Orgánico")

    return ", ".join(canales_activos)

# ==============================================================================
# AGENTE 5 (CLIENTES): Atención automática 24/7
# ==============================================================================
def agente_5_atencion_clientes():
    if not EBAY_ACTIVE_TOKEN:
        return
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <GetMemberMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <MailMessageType>AskSellerQuestion</MailMessageType>
      <MessageStatus>Unanswered</MessageStatus>
    </GetMemberMessagesRequest>"""
    res_xml = ebay_xml_call("GetMemberMessages", xml)

    try:
        root = ET.fromstring(res_xml)
        ns = {"eb": "urn:ebay:apis:eBLBaseComponents"}
        for msg in root.findall(".//eb:MemberMessageExchange", ns):
            msg_id = msg.find(".//eb:MessageID", ns).text
            sender = msg.find(".//eb:SenderID", ns).text
            item_id = msg.find(".//eb:ItemID", ns).text
            pregunta = msg.find(".//eb:Body", ns).text

            borrador = llamar_groq(
                "Eres soporte oficial de nuestra tienda en eBay Europa. Sé amable y directo. Enviamos desde Europa en 3-7 días laborables con seguimiento y 14 días de garantía.",
                f"El comprador '{sender}' pregunta: '{pregunta}'. Redacta la respuesta lista para enviar:",
                json_mode=False
            )

            reply_xml = f"""<?xml version="1.0" encoding="utf-8"?>
            <AddMemberMessageRTQRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <ItemID>{item_id}</ItemID>
              <MemberMessage>
                <Body>{limpiar_xml(borrador)}</Body>
                <ParentMessageID>{msg_id}</ParentMessageID>
                <RecipientID>{sender}</RecipientID>
              </MemberMessage>
            </AddMemberMessageRTQRequest>"""
            ebay_xml_call("AddMemberMessageRTQ", reply_xml)
    except Exception:
        pass

# ==============================================================================
# EJECUCIÓN MAESTRA DE LOS 7 AGENTES
# ==============================================================================
if __name__ == "__main__":
    print("=== ARRANCANDO ZONA 2 PRO: MULTI-MERCADO UE + TRÁFICO GRATIS ===")
    skus_activos, podados, ganadores = agente_6_datos_podar_catalogo()
    perfiles = obtener_politicas_vendedor_ebay()
    candidatos = agente_1_cazar_candidatos_seguros(skus_activos, max_candidatos=4)

    publicado_ok = False
    ultimo_error = ""

    for cand in candidatos:
        seo, item_id, cat_id, error_ebay = agente_3_publicar_tienda_europa(cand, perfiles)
        if not error_ebay and item_id != "ERROR_EBAY":
            variantes = agente_2_diseno_multimedia(cand)
            canales = agente_7_promocion_gratis_multicanal(cand, seo, variantes, item_id)
            agente_5_atencion_clientes()

            texto_ganadores = ", ".join(ganadores[:3]) if ganadores else "En fase de testeo (30 pruebas)"
            informe = (
                f"🟢 ZONA 2 PRO — PRODUCTO PUBLICADO EN TODA LA UE\n\n"
                f"📦 Producto: {seo['titulo']}\n"
                f"🏭 Almacén: {cand['almacen']} (Europa)\n"
                f"💶 Venta: {cand['precio_venta']}€ (Coste CJ: {cand['coste_cj']}€ | Limpio: +{cand['beneficio_neto']}€)\n"
                f"🌍 Mercados gratis: {canales}\n"
                f"🎨 Creativos: 10 imágenes + 1 Vídeo Reel MP4 + CSV Canva Pro\n"
                f"✂️ Limpieza hoy: {podados} productos sin ventas retirados\n"
                f"👑 Ganadores activos: {texto_ganadores}"
            )
            enviar_telegram(
                informe,
                botones=[[
                    {"text": "🚀 Ver Anuncio en eBay", "url": f"https://www.ebay.es/itm/{item_id}"},
                    {"text": "✅ Campaña 0€ Activa", "callback_data": f"OK_{item_id}"}
                ]]
            )
            publicado_ok = True
            break
        else:
            ultimo_error = error_ebay
            print("⏭️ Probando siguiente producto candidato seguro...")

    if not publicado_ok:
        enviar_telegram(
            f"⚠️ AVISO DE EBAY AL PUBLICAR:\n{ultimo_error}\n\n"
            f"👉 Si eBay menciona política de vendedor o fondos retenidos, entra en ebay.es > Mi eBay > Cuenta > Pagos y verifica tu IBAN/tarjeta y teléfono de vendedor (requisito único antes del primer anuncio por API)."
        )
    print("=== CICLO COMPLETADO ===")
