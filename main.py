import os
import tempfile
import requests
import boto3
from fastapi import FastAPI, HTTPException, status, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

app = FastAPI(title="Cotizador Web de Vehículos")

# Configurar estáticos y plantillas HTML
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------------------------------------------------------
# MODELOS DE DATOS
# ------------------------------------------------------------------
class PeritajeCostosDTO(BaseModel):
    reparacion_mecanica: float = Field(default=0.0, ge=0)
    reparacion_carroceria: float = Field(default=0.0, ge=0)
    reemplazo_cubiertas: float = Field(default=0.0, ge=0)
    deuda_patentes: float = Field(default=0.0, ge=0)
    deuda_multas: float = Field(default=0.0, ge=0)
    costos_gestoria_varios: float = Field(default=0.0, ge=0)

class DatosClienteDTO(BaseModel):
    nombre: str
    telefono: str

class DatosVehiculoDTO(BaseModel):
    marca: str
    modelo: str
    version: str
    anio: int
    kilometraje: int
    patente: Optional[str] = "N/D"

class CotizacionIntegralRequest(BaseModel):
    datos_agencia_nombre: str = "Usados Seleccionados"
    cliente: DatosClienteDTO
    vehiculo: DatosVehiculoDTO
    precio_referencia_mercado: float
    peritaje: PeritajeCostosDTO = Field(default_factory=PeritajeCostosDTO)
    porcentaje_margen_agencia: float = 12.0
    ajuste_kilometraje_pct: float = 0.0
    enviar_whatsapp: bool = True

# ------------------------------------------------------------------
# LÓGICA DE NEGOCIO, PDF, S3 Y WHATSAPP
# ------------------------------------------------------------------
def calcular_oferta_toma(precio_base: float, peritaje: PeritajeCostosDTO, margen_pct: float, ajuste_km_pct: float) -> Dict[str, Any]:
    descuento_peritaje = (
        peritaje.reparacion_mecanica + peritaje.reparacion_carroceria +
        peritaje.reemplazo_cubiertas + peritaje.deuda_patentes +
        peritaje.deuda_multas + peritaje.costos_gestoria_varios
    )
    monto_ajuste_km = precio_base * (ajuste_km_pct / 100.0)
    precio_base_ajustado = precio_base + monto_ajuste_km
    valor_post_peritaje = precio_base_ajustado - descuento_peritaje
    monto_margen = valor_post_peritaje * (margen_pct / 100.0)
    precio_toma_final = max(0.0, valor_post_peritaje - monto_margen)

    return {
        "precio_referencia_mercado": round(precio_base, 2),
        "ajuste_km_monto": round(monto_ajuste_km, 2),
        "descuento_peritaje_total": round(descuento_peritaje, 2),
        "monto_margen_agencia": round(monto_margen, 2),
        "precio_toma_final": round(precio_toma_final, 2)
    }

def generar_pdf_local(path_salida: str, req: CotizacionIntegralRequest, calc: Dict[str, Any]):
    doc = SimpleDocTemplate(path_salida, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = []
    styles = getSampleStyleSheet()

    PRIMARY_COLOR = colors.HexColor("#1E293B")
    ACCENT_COLOR = colors.HexColor("#2563EB")
    BG_LIGHT = colors.HexColor("#F8FAFC")

    title_style = ParagraphStyle('T1', fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=PRIMARY_COLOR)
    sub_style = ParagraphStyle('T2', fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor("#64748B"), alignment=2)
    heading_style = ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=PRIMARY_COLOR, spaceAfter=6)
    cell_label = ParagraphStyle('CL', fontName='Helvetica-Bold', fontSize=9, textColor=PRIMARY_COLOR)
    cell_val = ParagraphStyle('CV', fontName='Helvetica', fontSize=9, textColor=PRIMARY_COLOR)
    cell_val_r = ParagraphStyle('CVR', fontName='Helvetica', fontSize=9, textColor=PRIMARY_COLOR, alignment=2)

    story.append(Table([[Paragraph(f"<b>{req.datos_agencia_nombre}</b>", title_style), Paragraph("<b>COTIZACIÓN DE TOMA</b>", sub_style)]], colWidths=[11*cm, 7*cm]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=12))

    story.append(Paragraph("Resumen de Evaluación", heading_style))
    info_data = [
        [Paragraph("Cliente:", cell_label), Paragraph(req.cliente.nombre, cell_val), Paragraph("Vehículo:", cell_label), Paragraph(f"{req.vehiculo.marca} {req.vehiculo.modelo}", cell_val)],
        [Paragraph("Teléfono:", cell_label), Paragraph(req.cliente.telefono, cell_val), Paragraph("Versión:", cell_label), Paragraph(req.vehiculo.version, cell_val)],
        [Paragraph("Patente:", cell_label), Paragraph(req.vehiculo.patente, cell_val), Paragraph("Año / KM:", cell_label), Paragraph(f"{req.vehiculo.anio} | {req.vehiculo.kilometraje:,} km", cell_val)]
    ]
    info_table = Table(info_data, colWidths=[2.5*cm, 6.5*cm, 2.5*cm, 6.5*cm])
    info_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), BG_LIGHT), ('PADDING', (0,0), (-1,-1), 5)]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Desglose Comercial", heading_style))
    rows = [
        [Paragraph("<b>Concepto</b>", cell_label), Paragraph("<b>Monto (ARS)</b>", cell_val_r)],
        [Paragraph("Valor Referencia Mercado", cell_val), Paragraph(f"$ {calc['precio_referencia_mercado']:,.2f}", cell_val_r)],
        [Paragraph(f"Ajuste por Kilometraje ({req.ajuste_kilometraje_pct}%)", cell_val), Paragraph(f"$ {calc['ajuste_km_monto']:,.2f}", cell_val_r)],
        [Paragraph("Deducción Total por Peritaje/Deudas", cell_val), Paragraph(f"- $ {calc['descuento_peritaje_total']:,.2f}", cell_val_r)],
        [Paragraph("Margen Operativo Comercial", cell_val), Paragraph(f"- $ {calc['monto_margen_agencia']:,.2f}", cell_val_r)]
    ]
    table_d = Table(rows, colWidths=[12*cm, 6*cm])
    table_d.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")), ('PADDING', (0,0), (-1,-1), 5)]))
    story.append(table_d)
    story.append(Spacer(1, 15))

    off_lbl = ParagraphStyle('OL', fontName='Helvetica-Bold', fontSize=10, textColor=colors.white, alignment=1)
    off_val = ParagraphStyle('OV', fontName='Helvetica-Bold', fontSize=20, textColor=colors.white, alignment=1)
    offer_table = Table([[Paragraph("OFERTA FINAL DE TOMA", off_lbl)], [Paragraph(f"$ {calc['precio_toma_final']:,.2f} ARS", off_val)]], colWidths=[18*cm])
    offer_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), ACCENT_COLOR), ('PADDING', (0,0), (-1,-1), 10)]))
    story.append(offer_table)

    doc.build(story)

def subir_a_s3(path_local: str, filename_s3: str) -> str:
    bucket_name = os.getenv("AWS_S3_BUCKET_NAME", "mi-bucket-cotizaciones")
    s3_client = boto3.client('s3')
    s3_key = f"cotizaciones/{filename_s3}"
    s3_client.upload_file(
        Filename=path_local,
        Bucket=bucket_name,
        Key=s3_key,
        ExtraArgs={'ContentType': 'application/pdf', 'ContentDisposition': f'inline; filename="{filename_s3}"'}
    )
    return s3_client.generate_presigned_url('get_object', Params={'Bucket': bucket_name, 'Key': s3_key}, ExpiresIn=86400)

def enviar_mensaje_whatsapp(numero_telefono: str, nombre_cliente: str, url_pdf: str):
    token = os.getenv("META_WHATSAPP_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        return
    num_limpio = numero_telefono.replace("+", "").replace(" ", "").replace("-", "")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": num_limpio,
        "type": "template",
        "template": {
            "name": "envio_cotizacion_auto",
            "language": {"code": "es_AR"},
            "components": [
                {"type": "header", "parameters": [{"type": "document", "document": {"link": url_pdf, "filename": "Cotizacion.pdf"}}]},
                {"type": "body", "parameters": [{"type": "text", "text": nombre_cliente}]}
            ]
        }
    }
    requests.post(f"https://graph.facebook.com/v18.0/{phone_number_id}/messages", headers=headers, json=payload)

def procesar_pdf_s3_whatsapp_async(req: CotizacionIntegralRequest, calc: Dict[str, Any]):
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
        filename_s3 = f"Cotizacion_{req.vehiculo.marca}_{req.vehiculo.modelo}_{req.cliente.nombre.replace(' ', '_')}.pdf"
        generar_pdf_local(pdf_path, req, calc)
        url_s3 = subir_a_s3(pdf_path, filename_s3)
        if req.enviar_whatsapp and url_s3:
            enviar_mensaje_whatsapp(req.cliente.telefono, req.cliente.nombre, url_s3)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    except Exception as e:
        print(f"Error procesando tareas en segundo plano: {e}")

# ------------------------------------------------------------------
# RUTAS WEB Y API
# ------------------------------------------------------------------
@app.get("/")
async def cargar_interfaz_web(request: Request):
    """Sirve el formulario HTML en la raíz del navegador"""
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/v1/cotizaciones/procesar-completo")
async def procesar_cotizacion_integral(payload: CotizacionIntegralRequest, background_tasks: BackgroundTasks):
    resultado_calculo = calcular_oferta_toma(
        precio_base=payload.precio_referencia_mercado,
        peritaje=payload.peritaje,
        margen_pct=payload.porcentaje_margen_agencia,
        ajuste_km_pct=payload.ajuste_kilometraje_pct
    )
    background_tasks.add_task(procesar_pdf_s3_whatsapp_async, payload, resultado_calculo)
    return {
        "estado": "exito",
        "mensaje": "Cotización calculada y enviada a procesamiento.",
        "resumen": resultado_calculo
    }
