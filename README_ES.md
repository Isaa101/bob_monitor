# BOB reservas — GitHub Actions gratis

Monitor de disponibilidad de BOB Alchimia a Spicchi para **1 a 8 personas**.

- Comprueba aproximadamente cada 5 minutos.
- Envía notificaciones por ntfy.
- No realiza reservas automáticamente.
- No necesita que tu ordenador esté encendido.
- Está preparado para un repositorio **público** de GitHub usando runners estándar.

## Archivos

```text
.github/
  workflows/
    bob-monitor.yml
    keepalive.yml
    test-ntfy.yml
bob_monitor.py
config.json
requirements.txt
state.json
.gitignore
README_ES.md
```

## 1. Crear el repositorio

En GitHub crea un repositorio nuevo, por ejemplo:

`bob-reservas-monitor`

IMPORTANTE: para usar los runners estándar de GitHub Actions sin consumir minutos facturables, déjalo **Public**.

El código será visible públicamente, pero este paquete NO contiene tu topic privado de ntfy.

## 2. Subir los archivos

Sube todos los archivos y carpetas de este paquete al repositorio.

La carpeta `.github/workflows/` debe conservar exactamente ese nombre y esa estructura.

## 3. Crear el Secret de ntfy

Dentro del repositorio ve a:

**Settings → Secrets and variables → Actions → New repository secret**

Nombre:

```text
NTFY_TOPIC
```

Valor:

```text
TU_TOPIC_PRIVADO_DE_NTFY
```

Pon únicamente el nombre del topic. No pongas `https://ntfy.sh/`.

El Secret no queda escrito en el código público.

## 4. Permisos del workflow

Ve a:

**Settings → Actions → General**

Busca **Workflow permissions**.

Selecciona:

**Read and write permissions**

y guarda.

Esto permite que el monitor actualice `state.json` para recordar qué huecos ya ha visto.

## 5. Probar ntfy

Ve a:

**Actions → Probar notificacion ntfy → Run workflow**

Pulsa **Run workflow**.

Deberías recibir:

`BOB monitor: prueba OK`

## 6. Probar una comprobación completa

Ve a:

**Actions → BOB reservas monitor → Run workflow**

Abre la ejecución y después el job `monitor`.

En `Comprobar disponibilidad BOB` deberías ver:

```text
1 persona: sin huecos detectados
2 personas: sin huecos detectados
3 personas: sin huecos detectados
...
8 personas: sin huecos detectados
Estado guardado correctamente.
```

Si hay una fecha disponible, aparecerá la fecha y recibirás una notificación.

## 7. Ya puedes apagar el ordenador

El workflow `BOB reservas monitor` está programado aproximadamente cada 5 minutos.

GitHub no garantiza que los workflows programados comiencen exactamente a la hora indicada. En momentos de carga puede haber retrasos.

## Por qué existe keepalive.yml

GitHub desactiva automáticamente los workflows programados de repositorios públicos que no tienen actividad durante 60 días.

`keepalive.yml` se ejecuta una vez al mes y modifica `.bob-keepalive`, creando un commit de actividad antes de llegar a los 60 días.

Si ese workflow mensual falla o se desactiva por algún motivo, habrá que volver a activarlo manualmente desde la pestaña Actions.

## Cómo evita avisos repetidos

`state.json` contiene únicamente:

- las combinaciones de fecha/número de personas actualmente detectadas;
- la fecha de la última actualización.

Cuando una combinación nueva aparece, ntfy avisa.

Cuando desaparece, se elimina del estado.

Si más adelante vuelve a aparecer, se considera una nueva oportunidad y vuelve a avisarte.

## Seguridad

Nunca pongas tu `NTFY_TOPIC` directamente en:

- `config.json`
- `bob_monitor.py`
- README
- `state.json`

Déjalo únicamente como GitHub Repository Secret.

## Frecuencia

El workflow usa:

```yaml
cron: "2-59/5 * * * *"
```

Eso ejecuta la comprobación aproximadamente en los minutos:

2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52 y 57 de cada hora.

## Si GitHub da un error al guardar state.json

Comprueba de nuevo:

**Settings → Actions → General → Workflow permissions → Read and write permissions**

## Ejecutarlo también en tu PC

Esta misma versión funciona localmente. Como ya instalaste Playwright y Chromium:

```powershell
python bob_monitor.py --once
```

Para la ejecución local necesitarías que `config.json` contenga temporalmente tu topic o definir `NTFY_TOPIC` como variable de entorno. Para el funcionamiento 24/7 en GitHub, no hace falta ejecutar nada en tu PC.
