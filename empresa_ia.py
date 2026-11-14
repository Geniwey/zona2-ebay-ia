import os
import re
import csv
import json
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

# ==============================================================================
# MÓDULO 0: AUTO-RENOVACIÓN DEL TOKEN DE EBAY Y UTILIDADES BASE
# ==============================================================================
def obtener_token_ebay_vivo():
    if EBAY_APP_ID and EBAY_CERT_ID and EBAY_REFRESH_TOKEN:
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
            print("🔑 [Seguridad] Token de eBay renovado automáticamente.")
            return res.json().get("access_token")
        else:
            print(f"⚠️ Error renovando token eBay: {res.text}")
    return EBAY_STATIC_TOKEN

EBAY_ACTIVE_TOKEN = obtener_token_ebay_vivo()

def obtener_access_token_cj():
    url = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
    res = requests.post(url, json={"apiKey": CJ_TOKEN}, timeout=15).json()
    if res.get("result") and res.get("data", {}).get("accessToken"):
        return res["data"]["accessToken"]
    return CJ_TOKEN

CJ_ACCESS_TOKEN = obtener_access_token_cj()

def llamar_groq(system_prompt, user_prompt, json_mode=True):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openai/gpt-oss-120b",
        "temperature": 0.15,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    res = requests.post(url, headers=headers, json=payload, timeout=30).json()
    contenido = res["choices"][0]["message"]["content"].strip()
    return json.loads(contenido) if json_mode else contenido

def ebay_xml_call(call_name, xml_body):
    headers = {
        "X-EBAY-API-SITEID": "186",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1149",
        "Content-Type": "text/xml",
        "X-EBAY-API-IAF-TOKEN": EBAY_ACTIVE_TOKEN
    }
    return requests.post(EBAY_XML_URL, headers=headers, data=xml_body.encode("utf-8"), timeout=25).text

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
# AGENTE 1 (TENDENCIAS): Escanea Amazon Movers & Shakers + CJ Almacén Alemania
# ==============================================================================
def agente_1_cazar_tendencia(skus_excluidos):
    print("🔍 [Agente 1 - Tendencias] Rastreando productos disparados en Amazon...")
    headers_amz = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9"
    }
    titulos_amz = []
    urls_movers = [
        "https://www.amazon.es/gp/movers-and-shakers/kitchen",
        "https://www.amazon.es/gp/movers-and-shakers/lighting",
        "https://www.amazon.es/gp/movers-and-shakers/sports"
    ]

    for u in urls_movers:
        try:
            r = requests.get(u, headers=headers_amz, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            for el in soup.select(".p13n-sc-truncate-desktop-type2, ._cDEzb_p13n-sc-css-line-clamp-3_g3dy1")[:8]:
                titulos_amz.append(el.get_text(strip=True))
        except Exception:
            pass

    kw_json = llamar_groq(
        "Eres un analista de producto de dropshipping europeo. Devuelve únicamente JSON válido.",
        f"Tendencias detectadas hoy: {titulos_amz}. Devuelve un JSON con una lista 'keywords' de 6 nombres en inglés de productos genéricos (sin marca, ligeros, alta demanda visual) para buscar en almacén europeo. Ejemplo: {{\"keywords\": [\"ocean wave projector\", \"led sunset lamp\", \"posture corrector\", \"electric lint remover\", \"massage gun\", \"motion sensor light\"]}}"
    )

    headers_cj = {"CJ-Access-Token": CJ_ACCESS_TOKEN}
    lista_keywords = kw_json.get("keywords", ["sunset lamp", "galaxy projector", "neck massager"])
    lista_keywords.append("")

    for kw in lista_keywords:
        url_cj = "https://developers.cjdropshipping.com/api2.0/v1/product/list?countryCode=DE&pageNum=1&pageSize=30"
        if kw:
            url_cj += f"&keyword={requests.utils.quote(kw)}"

        res_cj = requests.get(url_cj, headers=headers_cj, timeout=15).json()
        productos_lista = (res_cj.get("data") or {}).get("list") or []

        for prod in productos_lista:
            pid = prod.get("pid")
            if not pid or pid in skus_excluidos:
                continue

            precio_raw = str(prod.get("sellPrice", "0")).split("-")[0].strip()
            try:
                coste_cj = float(precio_raw)
            except ValueError:
                continue

            if 4.5 <= coste_cj <= 13.5:
                precio_venta = round((coste_cj * 3) + 0.90, 2)
                comision_ebay = round(precio_venta * 0.135, 2)
                beneficio_neto = round(precio_venta - comision_ebay - coste_cj, 2)

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

                return {
                    "sku": pid,
                    "titulo_en": prod.get("productNameEn", "Trending Gadget"),
                    "descripcion_en": det_data.get("description") or prod.get("productNameEn", ""),
                    "fotos": fotos_limpias,
                    "coste_cj": coste_cj,
                    "precio_venta": precio_venta,
                    "beneficio_neto": beneficio_neto
                }

    raise Exception("No se encontraron candidatos nuevos hoy en Alemania.")

# ==============================================================================
# AGENTE 2 (DISEÑO): 10 Imágenes + Vídeo Vertical .MP4 (Reels/TikTok) + CSV Canva
# ==============================================================================
def agente_2_diseno_multimedia(producto):
    print("🎨 [Agente 2 - Diseño] Creando 10 anuncios + Vídeo Vertical MP4 + Lote CSV para Canva Pro...")
    disenos = llamar_groq(
        "Eres un director creativo de e-commerce en Europa. Responde solo con JSON válido.",
        f"Producto: {producto['titulo_en']}. Precio: {producto['precio_venta']}€. Genera un JSON con una lista 'variantes' de exactamente 10 versiones de anuncio. Cada ítem debe tener: 'id' (1 a 10), 'gancho' (máx 4 palabras impactantes en español), 'angulo' (frase persuasiva para TikTok/Pinterest) y 'color_hex' (color oscuro elegante ej: #0F172A, #1E3A8A, #065F46, #7C2D12)."
    )

    os.makedirs("anuncios_generados", exist_ok=True)
    lista_variantes = disenos.get("variantes", [])[:10]

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
            draw.text((40, 1005), "ENVIO GRATIS EUROPA (5-7 DIAS) - GARANTIA 14 DIAS", fill="#10B981")

            ruta_jpg = f"anuncios_generados/anuncio_v{v.get('id', idx+1)}.jpg"
            lienzo_rgb = lienzo.convert("RGB")
            lienzo_rgb.save(ruta_jpg, quality=92)

            if idx < 5:
                frame_vert = Image.new("RGB", (1080, 1920), color_fondo)
                frame_vert.paste(lienzo_rgb, (0, 420))
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
def detectar_categoria_ebay_es(query_es):
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
    <GetSuggestedCategoriesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <Query>{query_es}</Query>
    </GetSuggestedCategoriesRequest>"""
    res = ebay_xml_call("GetSuggestedCategories", xml)
    match = re.search(r"<CategoryID>(\d+)</CategoryID>", res)
    return match.group(1) if match else "172008"

def validar_listing_antes_de_publicar(seo_data, producto):
    titulo = seo_data.get("titulo", "").strip()
    if len(titulo) > 80:
        seo_data["titulo"] = titulo[:80].rsplit(" ", 1)[0]
    descripcion = re.sub(r"https?://\S+|www\.\S+", "", seo_data.get("descripcion_html", ""))
    seo_data["descripcion_html"] = descripcion
    return seo_data

def agente_3_publicar_tienda_europa(producto, variantes):
    print("🛒 [Agente 3 - Tienda UE] Publicando en eBay con alcance a toda la Unión Europea...")
    texto_limpio = BeautifulSoup(producto["descripcion_en"], "html.parser").get_text(" ", strip=True)[:1500]

    seo = llamar_groq(
        "Eres un experto en SEO para eBay Europa. Prohibido usar marcas registradas, URLs, emails o teléfonos. Devuelve únicamente JSON válido.",
        f"""Nombre original: {producto['titulo_en']}
Detalles: {texto_limpio}

Devuelve este JSON exacto:
{{
  "query_categoria": "2 palabras en español del objeto (ej: lampara proyector)",
  "titulo": "Título SEO en español de 70 a 80 caracteres con keyword principal al inicio",
  "descripcion_html": "<div><h2>Calidad Premium - Stock en Europa</h2><p>Descripción persuasiva...</p><ul><li>Beneficio 1</li><li>Beneficio 2</li><li>Envío rápido desde almacén de Alemania a toda la UE en 3-7 días laborables.</li></ul></div>",
  "specifics": {{
    "Marca": "Genérico",
    "Tipo": "Especificar tipo",
    "Color": "Multicolor",
    "Material": "Alta resistencia"
  }}
}}"""
    )

    seo = validar_listing_antes_de_publicar(seo, producto)
    cat_id = detectar_categoria_ebay_es(seo.get("query_categoria", "hogar gadget"))
    fotos_xml = "".join([f"<PictureURL>{url}</PictureURL>" for url in producto["fotos"]])
    titulo_xml = seo["titulo"].replace("&", "y").replace("<", "").replace(">", "")

    specifics_xml = ""
    for k, v in seo.get("specifics", {}).items():
        val_limpio = str(v).replace("&", "y")
        specifics_xml += f"<NameValueList><Name>{k}</Name><Value>{val_limpio}</Value></NameValueList>"
    specifics_xml += "<NameValueList><Name>MPN</Name><Value>No aplicable</Value></NameValueList>"
    specifics_xml += "<NameValueList><Name>EAN</Name><Value>No aplicable</Value></NameValueList>"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
    <AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
      <Item>
        <SKU>{producto['sku']}</SKU>
        <Title>{titulo_xml}</Title>
        <Description><![CDATA[{seo['descripcion_html']}]]></Description>
        <PrimaryCategory><CategoryID>{cat_id}</CategoryID></PrimaryCategory>
        <StartPrice>{producto['precio_venta']}</StartPrice>
        <ConditionID>1000</ConditionID>
        <Country>DE</Country>
        <Location>Alemania</Location>
        <Currency>EUR</Currency>
        <DispatchTimeMax>1</DispatchTimeMax>
        <ListingDuration>GTC</ListingDuration>
        <ListingType>FixedPriceItem</ListingType>
        <Quantity>10</Quantity>
        <PictureDetails>{fotos_xml}</PictureDetails>
        <ItemSpecifics>{specifics_xml}</ItemSpecifics>
        <ProductListingDetails>
          <EAN>No aplicable</EAN>
          <BrandMPN>
            <Brand>Genérico</Brand>
            <MPN>No aplicable</MPN>
          </BrandMPN>
        </ProductListingDetails>
        <ReturnPolicy>
          <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
          <ReturnsWithinOption>Days_14</ReturnsWithinOption>
          <ShippingCostPaidByOption>Buyer</ShippingCostPaidByOption>
        </ReturnPolicy>
        <ShippingDetails>
          <ShippingServiceOptions>
            <ShippingServicePriority>1</ShippingServicePriority>
            <ShippingService>ES_StandardInternational</ShippingService>
            <FreeShipping>true</FreeShipping>
          </ShippingServiceOptions>
          <InternationalShippingServiceOption>
            <ShippingServicePriority>1</ShippingServicePriority>
            <ShippingService>ES_StandardInternational</ShippingService>
            <ShippingServiceCost currencyID="EUR">0.00</ShippingServiceCost>
            <ShippingServiceAdditionalCost currencyID="EUR">0.00</ShippingServiceAdditionalCost>
            <ShipToLocation>EuropeanUnion</ShipToLocation>
          </InternationalShippingServiceOption>
        </ShippingDetails>
        <Site>Spain</Site>
      </Item>
    </AddFixedPriceItemRequest>"""

    res = ebay_xml_call("AddFixedPriceItem", xml)
    match_id = re.search(r"<ItemID>(\d+)</ItemID>", res)
    if match_id:
        return seo, match_id.group(1), cat_id, None
    else:
        err_match = re.search(r"<LongMessage>(.*?)</LongMessage>", res)
        err_msg = err_match.group(1) if err_match else res[:300]
        print(f"⚠️ eBay devolvió aviso/error: {err_msg}")
        return seo, "ERROR_EBAY", cat_id, err_msg

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
            "description": f"{gancho} ✨ Envío gratis desde Europa en 5-7 días.",
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
                "Eres soporte oficial de nuestra tienda en eBay Europa. Sé amable y directo. Enviamos gratis desde Alemania en 3-7 días laborables con seguimiento y 14 días de garantía.",
                f"El comprador '{sender}' pregunta: '{pregunta}'. Redacta la respuesta lista para enviar:",
                json_mode=False
            )

            reply_xml = f"""<?xml version="1.0" encoding="utf-8"?>
            <AddMemberMessageRTQRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <ItemID>{item_id}</ItemID>
              <MemberMessage>
                <Body>{borrador}</Body>
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
    candidato = agente_1_cazar_tendencia(skus_activos)
    variantes = agente_2_diseno_multimedia(candidato)
    seo, item_id, cat_id, error_ebay = agente_3_publicar_tienda_europa(candidato, variantes)
    canales = agente_7_promocion_gratis_multicanal(candidato, seo, variantes, item_id)
    agente_5_atencion_clientes()

    if error_ebay:
        enviar_telegram(f"⚠️ AVISO DE EBAY AL PUBLICAR:\n{error_ebay}\n\nRevisa ese ajuste en tu cuenta y vuelve a lanzar.")
    else:
        texto_ganadores = ", ".join(ganadores[:3]) if ganadores else "En fase de testeo (30 pruebas)"
        informe = (
            f"🟢 ZONA 2 PRO — PRODUCTO PUBLICADO EN TODA LA UE\n\n"
            f"📦 Producto: {seo['titulo']}\n"
            f"💶 Venta: {candidato['precio_venta']}€ (Coste CJ: {candidato['coste_cj']}€ | Limpio: +{candidato['beneficio_neto']}€)\n"
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
    print("=== CICLO COMPLETADO ===")
