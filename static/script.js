document.getElementById('cotizadorForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const payload = {
        datos_agencia_nombre: "Simone Usados Seleccionados",
        cliente: {
            nombre: document.getElementById('clienteNombre').value,
            telefono: document.getElementById('clienteTelefono').value
        },
        vehiculo: {
            marca: document.getElementById('vehiculoMarca').value,
            modelo: document.getElementById('vehiculoModelo').value,
            version: document.getElementById('vehiculoVersion').value,
            anio: parseInt(document.getElementById('vehiculoAnio').value),
            kilometraje: parseInt(document.getElementById('vehiculoKm').value),
            patente: document.getElementById('vehiculoPatente').value
        },
        precio_referencia_mercado: parseFloat(document.getElementById('precioReferencia').value),
        porcentaje_margen_agencia: parseFloat(document.getElementById('margenAgencia').value),
        ajuste_kilometraje_pct: parseFloat(document.getElementById('ajusteKm').value),
        peritaje: {
            reparacion_mecanica: parseFloat(document.getElementById('repMecanica').value || 0),
            reparacion_carroceria: parseFloat(document.getElementById('repCarroceria').value || 0),
            reemplazo_cubiertas: parseFloat(document.getElementById('repCubiertas').value || 0),
            deuda_patentes: parseFloat(document.getElementById('deudaPatentes').value || 0),
            deuda_multas: parseFloat(document.getElementById('deudaMultas').value || 0)
        },
        enviar_whatsapp: document.getElementById('enviarWhatsapp').checked
    };

    try {
        const response = await fetch('/api/v1/cotizaciones/procesar-completo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            document.getElementById('resultadoBox').classList.remove('d-none');
            document.getElementById('montoFinal').innerText = `$ ${data.resumen.precio_toma_final.toLocaleString('es-AR', {minimumFractionDigits: 2})}`;
            document.getElementById('mensajeEstado').innerText = data.mensaje;
        } else {
            alert('Error: ' + JSON.stringify(data.detail));
        }
    } catch (error) {
        console.error(error);
        alert('Ocurrió un error al enviar la cotización.');
    }
});