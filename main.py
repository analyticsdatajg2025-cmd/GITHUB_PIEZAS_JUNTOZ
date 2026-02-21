import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageFont, ImageOps
from datetime import datetime
import io
import csv

# --- CONFIGURACIÓN DE RUTAS ---
BASE_PATH = os.path.dirname(os.path.realpath(__file__))
OUTPUT_DIR = os.path.join(BASE_PATH, 'output')
TAGS_DIR = os.path.join(BASE_PATH, 'FONDOS', 'TAGS')
FORMATS_DIR = os.path.join(BASE_PATH, 'FONDOS', 'FORMATOS')
FONTS_DIR = os.path.join(BASE_PATH, 'TIPOGRAFIA')
FEED_URL = "https://juntozstgsrvproduction.blob.core.windows.net/juntoz-feeds/google_juntoz_feed.txt"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- CONFIGURACIÓN TÉCNICA DE FORMATOS ---
CONFIG = {
    "PPL": {
        "res": (1080, 1080),
        "img_box": (60, 169, 1017, 797),
        "envio_box": (731, 54, 1023, 139),
        "marca_pos": (117, 880),
        "prod_pos": (117, 914),
        "prod_max_x": 504,
        "rect_gris": (553, 846, 965, 911),
        "rect_morado": (549, 904, 962, 1019),
        "precio_reg_pos": (564, 887),
        "simbolo_reg_pos": (843, 887),
        "valor_reg_pos": (872, 887),
        "cupon_img_box": (794, 940, 949, 997),
        "fonts": {"marca": 40, "prod": 35, "precio": 73, "reg": 30, "cupon_txt": 27}
    },
    "PUSH": {
        "res": (1200, 629),
        "img_box": (43, 30, 707, 601),
        "envio_box": (740, 491, 1028, 574),
        "marca_pos": (757, 168),
        "prod_pos": (757, 205),
        "prod_max_x": 1122,
        "rect_gris": (741, 312, 1119, 370),
        "rect_morado": (740, 362, 1118, 472),
        "precio_reg_pos": (763, 347),
        "simbolo_reg_pos": (1016, 347),
        "valor_reg_pos": (1050, 347),
        "cupon_img_box": (954, 400, 1105, 455),
        "fonts": {"marca": 36, "prod": 31, "precio": 71, "reg": 30, "cupon_txt": 25}
    },
    "STORY": {
        "res": (1080, 1920),
        "img_box": (109, 640, 968, 1581),
        "envio_box": (396, 547, 687, 630),
        "marca_pos": (93, 349),
        "prod_pos": (93, 387),
        "prod_max_x": 492,
        "rect_gris": (524, 314, 984, 371),
        "rect_morado": (521, 365, 984, 496),
        "precio_reg_pos": (559, 346),
        "simbolo_reg_pos": (856, 346),
        "valor_reg_pos": (891, 346),
        "cupon_img_box": (815, 410, 968, 474),
        "fonts": {"marca": 40, "prod": 37, "precio": 85, "reg": 35, "cupon_txt": 30}
    }
}

# --- FUNCIONES DE APOYO ---

def get_feed_data():
    print("Descargando feed de productos (esto puede tardar unos segundos)...")
    response = requests.get(FEED_URL)
    response.encoding = 'utf-8'
    feed_dict = {}
    # El archivo es un TSV (tab separated values)
    reader = csv.DictReader(io.StringIO(response.text), delimiter='\t')
    for row in reader:
        # Guardamos en minúsculas para match flexible
        title = str(row.get('title', '')).strip().lower()
        image = row.get('image_link', '')
        if title:
            feed_dict[title] = image
    return feed_dict

def get_font(name, size):
    path = os.path.join(FONTS_DIR, f"HurmeGeometricSans1 {name}.otf")
    if not os.path.exists(path):
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)

def find_format_image(format_name):
    for ext in ['.jpg', '.JPG', '.png', '.PNG', '.jpeg']:
        path = os.path.join(FORMATS_DIR, f"{format_name}{ext}")
        if os.path.exists(path):
            return path
    return None

def process_img(url, box_size):
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        raise ValueError(f"No se pudo descargar la imagen del feed. Status: {r.status_code}")
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    img.thumbnail((box_size[2]-box_size[0], box_size[3]-box_size[1]), Image.LANCZOS)
    
    datas = img.getdata()
    new_data = []
    for item in datas:
        if item[0] > 240 and item[1] > 240 and item[2] > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

def draw_text_wrapped(draw, text, pos, max_x, font, fill):
    words = str(text).split()
    lines, current_line = [], []
    for word in words:
        current_line.append(word)
        if draw.textbbox(pos, " ".join(current_line), font=font)[2] > max_x:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    lines.append(" ".join(current_line))
    y = pos[1]
    for line in lines:
        draw.text((pos[0], y), line, font=font, fill=fill)
        y += font.size + 4
    return y

def create_piece(row, image_url):
    f_key = row['Formato']
    if f_key not in CONFIG: return None
    c = CONFIG[f_key]
    
    bg_path = find_format_image(f_key)
    if not bg_path:
        print(f"Error: No se encontró el fondo {f_key}")
        return None
        
    canvas = Image.open(bg_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    
    # 1. Imagen Producto (Desde el Link del Feed)
    if image_url:
        p_img = process_img(image_url, c['img_box'])
        w, h = p_img.size
        center_x = c['img_box'][0] + (c['img_box'][2] - c['img_box'][0] - w) // 2
        center_y = c['img_box'][1] + (c['img_box'][3] - c['img_box'][1] - h) // 2
        canvas.paste(p_img, (center_x, center_y), p_img)

    # 2. Tipo Envío
    envio_val = str(row['tipo envio']).strip()
    envio_path = os.path.join(TAGS_DIR, f"{envio_val}.png")
    if envio_val != "NINGUNO" and os.path.exists(envio_path):
        e_img = Image.open(envio_path).convert("RGBA")
        e_img.thumbnail((c['envio_box'][2]-c['envio_box'][0], c['envio_box'][3]-c['envio_box'][1]))
        canvas.paste(e_img, (c['envio_box'][0], c['envio_box'][1]), e_img)

    # 3. Contenedores
    draw.rectangle(c['rect_gris'], fill="#D9D9D9")
    draw.rounded_rectangle(c['rect_morado'], radius=20, fill="#8D3DCB")

    # 4. Textos Precios
    f_reg = get_font("Regular", c['fonts']['reg'])
    f_bold = get_font("Bold", c['fonts']['precio'])
    draw.text(c['precio_reg_pos'], f"{row['Tipo precio regular']}:", font=f_reg, fill="black")
    draw.text(c['simbolo_reg_pos'], "S/", font=f_reg, fill="black")
    draw.text(c['valor_reg_pos'], str(row['Valor precio regular']), font=f_reg, fill="black")

    if row['Tipo precio regular'] == "Precio sin cupón":
        draw.text((c['rect_morado'][0]+20, c['rect_morado'][1]+35), "S/", font=get_font("Regular", 35), fill="white")
        draw.text((c['rect_morado'][0]+65, c['rect_morado'][1]+15), str(row['Precio descuento']), font=f_bold, fill="white")
        draw.text((c['cupon_img_box'][0], c['rect_morado'][1]+5), "Con cupón:", font=get_font("Bold", 20), fill="white")
        val_cupon = str(row['Con cupon']).strip()
        if val_cupon in ["BBVACREDITO", "BCPCREDITO"]:
            tag_path = os.path.join(TAGS_DIR, f"{val_cupon}.png")
            if os.path.exists(tag_path):
                tag_img = Image.open(tag_path).convert("RGBA")
                tag_img.thumbnail((c['cupon_img_box'][2]-c['cupon_img_box'][0], c['cupon_img_box'][3]-c['cupon_img_box'][1]))
                canvas.paste(tag_img, (c['cupon_img_box'][0], c['cupon_img_box'][1]), tag_img)
        else:
            draw.rounded_rectangle(c['cupon_img_box'], radius=10, fill="white")
            draw.text((c['cupon_img_box'][0]+15, c['cupon_img_box'][1]+8), val_cupon, font=get_font("Bold", 22), fill="#8D3DCB")
    else:
        txt = f"S/ {row['Precio descuento']}"
        w_txt = draw.textbbox((0,0), txt, font=f_bold)[2]
        pos_x = c['rect_morado'][0] + (c['rect_morado'][2]-c['rect_morado'][0]-w_txt)//2
        draw.text((pos_x, c['rect_morado'][1]+15), txt, font=f_bold, fill="white")

    # 5. Marca y Producto
    draw.text(c['marca_pos'], str(row['Marca']), font=get_font("Bold", c['fonts']['marca']), fill="black")
    draw_text_wrapped(draw, str(row['Nombre del producto']), c['prod_pos'], c['prod_max_x'], get_font("Regular Oblique", c['fonts']['prod']), "black")

    out_fn = f"{row['SKU']}_{f_key}.png"
    canvas.convert("RGB").save(os.path.join(OUTPUT_DIR, out_fn))
    return out_fn

# --- PROCESO PRINCIPAL ---

def main():
    try:
        # 1. Cargar Feed
        feed = get_feed_data()
        
        # 2. Conectar a Google Sheets
        creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
        creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
        client = gspread.authorize(creds)
        sheet = client.open_by_key("19e1ct-5GhElvCKRthr-5O9t8O3knvVTB2iDvMQo0zzU")
        input_ws = sheet.worksheet("Hoja 1")
        results_ws = sheet.worksheet("Resultados")
        
        data = input_ws.get_all_records()
        new_rows = []
        
        # Para actualizar el Link Imagen en la Hoja 1 (Columna J es la 10)
        updates = []

        for i, row in enumerate(data, start=2): # start=2 por el encabezado
            prod_name = str(row['Nombre del producto']).strip().lower()
            img_url = feed.get(prod_name)
            
            if not img_url:
                print(f"No se encontró imagen para: {prod_name}")
                continue
            
            # Registrar actualización para Columna J (Link imagen)
            updates.append({'range': f'J{i}', 'values': [[img_url]]})
            
            try:
                print(f"Generando: {row['SKU']} ({row['Formato']})")
                fn = create_piece(row, img_url)
                if fn:
                    link_repo = f"https://raw.githubusercontent.com/analyticsdatajg2025-cmd/GITHUB_PIEZAS_JUNTOZ/main/output/{fn}"
                    new_rows.append([datetime.now().strftime("%Y-%m-%d %H:%M"), f"{row['SKU']}_{row['Formato']}", row['Formato'], link_repo])
            except Exception as e:
                print(f"Error en {row['SKU']}: {e}")

        # 3. Ejecutar actualizaciones masivas
        if updates:
            input_ws.batch_update(updates)
        if new_rows:
            results_ws.append_rows(new_rows)
            print(f"Proceso completo. {len(new_rows)} piezas creadas.")

    except Exception as e:
        print(f"Error crítico: {e}")

if __name__ == "__main__":
    main()