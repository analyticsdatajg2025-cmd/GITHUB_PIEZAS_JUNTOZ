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
        "precio_reg_pos": (564, 867), 
        "simbolo_reg_pos": (843, 867),
        "valor_reg_pos": (872, 867),
        "cupon_img_box": (794, 940, 949, 997),
        "fonts": {"marca": 40, "prod": 32, "precio": 73, "reg": 30, "cupon_txt": 27}
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
        "precio_reg_pos": (763, 327),
        "simbolo_reg_pos": (1016, 327),
        "valor_reg_pos": (1050, 327),
        "cupon_img_box": (954, 400, 1105, 455),
        "fonts": {"marca": 36, "prod": 28, "precio": 71, "reg": 30, "cupon_txt": 25}
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
        "precio_reg_pos": (559, 326),
        "simbolo_reg_pos": (856, 326),
        "valor_reg_pos": (891, 326),
        "cupon_img_box": (815, 410, 968, 474),
        "fonts": {"marca": 40, "prod": 35, "precio": 85, "reg": 35, "cupon_txt": 30}
    }
}

def get_feed_data():
    print("Descargando feed de productos...")
    response = requests.get(FEED_URL)
    response.encoding = 'utf-8'
    feed_dict = {}
    reader = csv.DictReader(io.StringIO(response.text), delimiter='\t')
    for row in reader:
        title = str(row.get('title', '')).strip().lower()
        image = row.get('image_link', '')
        if title: feed_dict[title] = image
    return feed_dict

def get_font(name, size):
    path = os.path.join(FONTS_DIR, f"HurmeGeometricSans1 {name}.otf")
    if not os.path.exists(path): return ImageFont.load_default()
    return ImageFont.truetype(path, size)

def find_format_image(format_name):
    for ext in ['.jpg', '.JPG', '.png', '.PNG', '.jpeg']:
        path = os.path.join(FORMATS_DIR, f"{format_name}{ext}")
        if os.path.exists(path): return path
    return None

def process_img(url, box_size):
    r = requests.get(url, timeout=15)
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    img.thumbnail((box_size[2]-box_size[0], box_size[3]-box_size[1]), Image.LANCZOS)
    datas = img.getdata()
    new_data = [(255, 255, 255, 0) if d[0]>240 and d[1]>240 and d[2]>240 else d for d in datas]
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
    if not bg_path: return None
    canvas = Image.open(bg_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    
    # --- LOGICA DINÁMICA DE OFFSET PARA CUPÓN EXTRA ---
    # Si hay cupón extra, subimos los bloques 25px para que no choquen abajo
    y_offset = 0
    cupon_ps = str(row.get('Cupon con PS', '')).strip()
    usa_cupon_extra = False
    
    if str(row['Tipo precio regular']) == "Precio sin cupón" and \
       str(row['Con cupon']).strip() in ["BCPCREDITO", "BBVACREDITO"] and cupon_ps != "":
        y_offset = -25
        usa_cupon_extra = True

    if image_url:
        p_img = process_img(image_url, c['img_box'])
        w, h = p_img.size
        canvas.paste(p_img, (c['img_box'][0] + (c['img_box'][2]-c['img_box'][0]-w)//2, c['img_box'][1] + (c['img_box'][3]-c['img_box'][1]-h)//2), p_img)

    envio_val = str(row['tipo envio']).strip()
    envio_path = os.path.join(TAGS_DIR, f"{envio_val}.png")
    if envio_val != "NINGUNO" and os.path.exists(envio_path):
        e_img = Image.open(envio_path).convert("RGBA")
        e_img.thumbnail((c['envio_box'][2]-c['envio_box'][0], c['envio_box'][3]-c['envio_box'][1]))
        canvas.paste(e_img, (c['envio_box'][0], c['envio_box'][1]), e_img)

    # 3. Contenedores con Offset
    rg = c['rect_gris']
    draw.rounded_rectangle([rg[0], rg[1]+y_offset, rg[2], rg[3]+y_offset], radius=15, fill="#F7F7F7")
    draw.rectangle([rg[0], (rg[1]+rg[3])//2+y_offset, rg[2], rg[3]+y_offset], fill="#F7F7F7")
    
    rm = c['rect_morado']
    draw.rounded_rectangle([rm[0], rm[1]+y_offset, rm[2], rm[3]+y_offset], radius=20, fill="#8D3DCB")

    # 4. Textos Precios con Offset
    f_reg = get_font("Regular", c['fonts']['reg'])
    base_size = c['fonts']['precio']
    f_bold_price = get_font("Bold", base_size)

    draw.text((c['precio_reg_pos'][0], c['precio_reg_pos'][1]+y_offset), f"{row['Tipo precio regular']}:", font=f_reg, fill="8D3DCB")
    draw.text((c['simbolo_reg_pos'][0], c['simbolo_reg_pos'][1]+y_offset), "S/", font=f_reg, fill="8D3DCB")
    draw.text((c['valor_reg_pos'][0], c['valor_reg_pos'][1]+y_offset), str(row['Valor precio regular']), font=f_reg, fill="8D3DCB")

    if row['Tipo precio regular'] == "Precio sin cupón":
        price_str = str(row['Precio descuento'])
        max_col_w = (c['cupon_img_box'][0] - c['rect_morado'][0]) - 80
        while draw.textbbox((0,0), price_str, font=f_bold_price)[2] > max_col_w and base_size > 30:
            base_size -= 2
            f_bold_price = get_font("Bold", base_size)

        f_bold_small = get_font("Bold", int(base_size * 0.55))
        draw.text((c['rect_morado'][0]+22, c['rect_morado'][1]+15+y_offset), "S/", font=f_bold_small, fill="white")
        draw.text((c['rect_morado'][0]+68, c['rect_morado'][1]+15+y_offset), price_str, font=f_bold_price, fill="white")
        draw.text((c['cupon_img_box'][0], c['rect_morado'][1]+5+y_offset), "Con cupón:", font=get_font("Bold", 20), fill="white")
        
        val_cupon = str(row['Con cupon']).strip()
        if val_cupon in ["BBVACREDITO", "BCPCREDITO"]:
            tag_path = os.path.join(TAGS_DIR, f"{val_cupon}.png")
            if os.path.exists(tag_path):
                tag_img = Image.open(tag_path).convert("RGBA")
                tag_img.thumbnail((c['cupon_img_box'][2]-c['cupon_img_box'][0], c['cupon_img_box'][3]-c['cupon_img_box'][1]))
                canvas.paste(tag_img, (c['cupon_img_box'][0], c['cupon_img_box'][1]+y_offset), tag_img)
        else:
            draw.rounded_rectangle([c['cupon_img_box'][0], c['cupon_img_box'][1]+y_offset, c['cupon_img_box'][2], c['cupon_img_box'][3]+y_offset], radius=10, fill="white")
            f_cupon = get_font("Bold", 22)
            bbox = draw.textbbox((0, 0), val_cupon, font=f_cupon)
            tx = c['cupon_img_box'][0] + (c['cupon_img_box'][2]-c['cupon_img_box'][0]-(bbox[2]-bbox[0]))//2
            ty = c['cupon_img_box'][1] + (c['cupon_img_box'][3]-c['cupon_img_box'][1]-(bbox[3]-bbox[1]))//2 - 2
            draw.text((tx, ty+y_offset), val_cupon, font=f_cupon, fill="#8D3DCB")
            
        # --- DIBUJO DEL CUPÓN EXTRA (PS) ---
        if usa_cupon_extra:
            # Creamos un contenedor blanco debajo del morado
            # Centrado respecto al contenedor morado
            extra_w = 280
            extra_h = 35
            center_morado_x = (rm[0] + rm[2]) // 2
            extra_x1 = center_morado_x - (extra_w // 2)
            extra_y1 = rm[3] + y_offset # Pegado al borde inferior del morado (que ya tiene offset)
            extra_x2 = extra_x1 + extra_w
            extra_y2 = extra_y1 + extra_h
            
            # Dibujamos contenedor blanco con esquinas inferiores redondeadas
            draw.rounded_rectangle([extra_x1, extra_y1, extra_x2, extra_y2], radius=12, fill="white")
            # Aplanamos las esquinas superiores dibujando un pequeño rectangulo arriba
            draw.rectangle([extra_x1, extra_y1, extra_x2, extra_y1 + 10], fill="white")
            
            txt_extra = f"Cupón: {cupon_ps}"
            f_extra = get_font("Bold", 20)
            bbox_ex = draw.textbbox((0,0), txt_extra, font=f_extra)
            tex = extra_x1 + (extra_w - (bbox_ex[2]-bbox_ex[0])) // 2
            tey = extra_y1 + (extra_h - (bbox_ex[3]-bbox_ex[1])) // 2 - 2
            draw.text((tex, tey), txt_extra, font=f_extra, fill="#8D3DCB")

    else:
        # Centrado General
        price_str = str(row['Precio descuento'])
        max_full_w = (c['rect_morado'][2] - c['rect_morado'][0]) - 100
        while draw.textbbox((0,0), price_str, font=f_bold_price)[2] > max_full_w and base_size > 40:
            base_size -= 2
            f_bold_price = get_font("Bold", base_size)

        f_bold_small = get_font("Bold", int(base_size * 0.55))
        w_p = draw.textbbox((0,0), price_str, font=f_bold_price)[2]
        w_s = draw.textbbox((0,0), "S/", font=f_bold_small)[2]
        st_x = rm[0] + (rm[2]-rm[0]-(w_p+w_s+5))//2
        draw.text((st_x, rm[1]+15+y_offset), "S/", font=f_bold_small, fill="white")
        draw.text((st_x+w_s+5, rm[1]+15+y_offset), price_str, font=f_bold_price, fill="white")

    draw.text(c['marca_pos'], str(row['Marca']), font=get_font("Bold", c['fonts']['marca']), fill="#8D3DCB")
    draw_text_wrapped(draw, str(row['Nombre del producto']), c['prod_pos'], c['prod_max_x'], get_font("Regular Oblique", c['fonts']['prod']), "#8D3DCB")

    val_ps = str(row.get('Cupon con PS', '')).strip() if str(row.get('Cupon con PS', '')).strip() else "SINPS"
    id_safe = f"{row['SKU']}_{f_key}_{row['Tipo precio regular']}_{row['tipo envio']}_{val_ps}".replace(" ", "_")
    out_fn = f"{id_safe}.png"
    canvas.convert("RGB").save(os.path.join(OUTPUT_DIR, out_fn))
    return out_fn

def main():
    try:
        feed = get_feed_data()
        creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
        creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
        client = gspread.authorize(creds)
        sheet = client.open_by_key("19e1ct-5GhElvCKRthr-5O9t8O3knvVTB2iDvMQo0zzU")
        input_ws = sheet.worksheet("Hoja 1")
        results_ws = sheet.worksheet("Resultados")
        
        existing_ids = results_ws.col_values(2)
        data = input_ws.get_all_records()
        new_rows, updates = [], []

        for i, row in enumerate(data, start=2):
            if not row['SKU']: continue
            val_ps = str(row.get('Cupon con PS', '')).strip() if str(row.get('Cupon con PS', '')).strip() else "SINPS"
            id_pieza = f"{row['SKU']}_{row['Formato']}_{row['Tipo precio regular']}_{row['tipo envio']}_{val_ps}".replace(" ", "_")
            if id_pieza in existing_ids: continue

            prod_name = str(row['Nombre del producto']).strip().lower()
            img_url = feed.get(prod_name)
            if not img_url: continue
            
            updates.append({'range': f'J{i}', 'values': [[img_url]]})
            try:
                fn = create_piece(row, img_url)
                if fn:
                    link_repo = f"https://raw.githubusercontent.com/analyticsdatajg2025-cmd/GITHUB_PIEZAS_JUNTOZ/main/output/{fn}"
                    new_rows.append([datetime.now().strftime("%Y-%m-%d %H:%M"), id_pieza, row['Formato'], link_repo])
            except Exception as e:
                print(f"Error en {row['SKU']}: {e}")

        if updates: input_ws.batch_update(updates)
        if new_rows:
            results_ws.append_rows(new_rows)
            print(f"Proceso completo. {len(new_rows)} piezas creadas.")

    except Exception as e:
        print(f"Error crítico: {e}")

if __name__ == "__main__":
    main()