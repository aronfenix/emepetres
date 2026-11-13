# Last.fm sin conexión en emepetrés

El reproductor guarda las escuchas mientras está sin conexión. La aplicación de Windows conserva una copia local, permite revisarlas y las envía a Last.fm únicamente cuando lo pides. El reproductor no necesita Wi-Fi ni una sesión de Last.fm.

**Estado de esta entrega:** motor, interfaz y pruebas sin envíos reales. La activación necesita tu API key y secreto de una aplicación personal de Last.fm, y tu autorización de cuenta en el navegador. No se han creado cuentas ni aplicaciones Last.fm, no se han usado credenciales reales y no se ha enviado ninguna escucha. La integración con una cuenta real y el comportamiento en un Rocker físico siguen pendientes de comprobar.

## Uso en Windows 11

1. Abre `emepetres-lastfm.exe` del paquete de Windows. La ventana se abre sin conectar a Internet ni buscar tarjetas o reproductores.
2. Puedes introducir tu nombre de cuenta e importar para revisar **sin autorizar todavía**. La cola queda asociada a ese nombre: compruébalo antes de importar. Importar para otra cuenta crea un registro separado; no traslada las escuchas de la primera.
3. Para enviar, introduce en los campos protegidos la **API key** y el **secreto de tu aplicación Last.fm**, obtenidos por ti en [Last.fm API](https://www.last.fm/api/account/create). No son tu contraseña de Last.fm. No los pegues en un chat ni los incluyas en capturas.
4. Pulsa **Autorizar en Last.fm**, permite el acceso en el navegador y vuelve a la ventana para pulsar **Ya he autorizado**. La aplicación usa el nombre de la cuenta devuelto por Last.fm y guarda su sesión cifrada en Windows. Tu contraseña se introduce solamente en la página de Last.fm.
5. En el reproductor, usa **Last.fm → Preparar sincronizacion** cuando quieras preparar el registro. La exportación produce `/.emepetres-scrobbler.log`; aún no envía nada a Internet.
6. Con el reproductor conectado por USB, pulsa **Importar registro…** y elige `.emepetres-scrobbler.log`. También puedes elegir una copia que ya hayas guardado en el PC. La herramienta abre ese archivo solo para lectura, conserva una copia exacta y muestra los estados. Nunca modifica, vacía ni elimina archivos de la tarjeta.
7. Revisa las filas **Para revisar** y confirma la zona horaria cuando corresponda. Selecciona solamente filas cuyo desfase horario sea el mismo.
8. Pulsa **Enviar hasta 50 pendientes** y confirma la cuenta de destino. Un clic procesa un solo lote, en orden de fecha. Si quedan más escuchas, revisa el resultado y pulsa de nuevo para el siguiente lote. No hay tareas de fondo que envíen automáticamente.

La autorización y el envío necesitan conexión a Internet en el PC. Importar, revisar, conservar copias y consultar el historial local funcionan sin conexión.

## Reloj y zona horaria

El exportador escribe `#TZ/UNKNOWN` porque el reloj del reproductor no lleva una zona horaria fiable. Una fecha aparentemente correcta **no equivale a una fecha UTC confirmada**. Por eso esas filas quedan en revisión hasta que confirmes el desfase.

**Confirmar zona horaria…** solicita el desfase del reloj del reproductor respecto a UTC, en minutos. Si estaba ajustado a UTC, introduce `0`. Para UTC+1 introduce `60`; para UTC+2, `120`. Se calcula `UTC = fecha del registro − desfase`. Utiliza el desfase vigente **cuando escuchaste las pistas**, incluido el horario de verano, y revisa por separado los grupos de fechas que tengan desfases diferentes. No se aplica automáticamente la zona actual del PC.

Los registros sin reloj, llamados *timeless*, tienen fecha `0`. Permanecen en revisión: el programa no inventa fechas y el botón de zona horaria no los convierte en escuchas enviables. Las fechas futuras o los valores no válidos también requieren revisión. Si faltan metadatos o una fecha real, conserva el original para investigar; esta versión no incluye un editor que reconstruya esos datos.

## Qué registra el firmware

En la variante emepetrés, el registro está activado por defecto en configuraciones nuevas. Si ya existía una configuración que lo desactivaba, comprueba el ajuste de registro de reproducción.

La variante mantiene su propia familia de archivos `/.rockbox/emepetres_playback.log` y `/.rockbox/emepetres_playback_NNNN.log`. Son distintos de los antiguos registros de Rockbox. La exportación de emepetrés utiliza el argumento interno `-emepetres-export`, no elimina estos registros y regenera `/.emepetres-scrobbler.log`, identificado con `#CLIENT/emepetres`. Escribe primero un archivo temporal y lo renombra al completar la exportación; repetirla no añade copias de todo el historial al mismo archivo. Mientras copia una instantánea delimitada del registro, la grabación de nuevas escuchas permanece activa. El plugin normal conserva sus rutas antiguas independientes.

Se guarda la fecha de inicio de la pista y se cuenta la duración de los bloques de audio consumidos por el mezclador: las pausas, las búsquedas sin salida de audio y las esperas por datos no suman tiempo. Mover la posición no concede tiempo escuchado. La precisión está limitada al tamaño de los bloques y a la notificación del cambio de pista (normalmente decenas de milisegundos); un bloque incompleto al parar no se cuenta. El exportador marca `L` cuando una pista dura más de 30 segundos y se ha escuchado al menos la mitad o cuatro minutos, lo que suceda antes. Las pistas que no alcanzan ese umbral se marcan `S`. Los registros son de metadatos, no de audio.

Se conservan las escuchas repetidas de una misma canción en momentos distintos. Una exportación acumulativa puede volver a incluir filas anteriores: la cola de Windows evita reenviarlas. También puede aparecer primero una fila `S` y después una `L` de la misma sesión; la importación actualiza esa escucha a su estado válido sin reiniciar una que ya esté enviada o sin confirmar. Las pistas sin metadatos utilizables no se convierten automáticamente a partir de sus nombres de archivo.

La retención de los registros y las exportaciones acumulativas hace que ocupen espacio creciente. Esta herramienta no los limpia. El registro sigue dependiendo del funcionamiento del reproductor y de sus puntos de guardado; una pérdida brusca de alimentación puede dejar sin escribir las últimas escuchas. La precisión del reloj y las pruebas en hardware real siguen siendo necesarias.

## Estados y resultados dudosos

| Estado | Significado |
| --- | --- |
| Pendientes | Escuchas válidas, con fecha UTC confirmada; disponibles para el próximo envío explícito. |
| Enviadas | Last.fm confirmó la aceptación, o el usuario resolvió manualmente un caso dudoso. La columna de detalle distingue ambas situaciones. |
| Omitidas | Saltadas `S`, pistas demasiado cortas, rechazo individual de Last.fm o descarte manual. El detalle explica el caso. |
| Para revisar | Zona desconocida, fecha ausente o futura, fila incompleta, codificación dañada o metadatos no válidos. No se envían. |
| Sin confirmar | Se intentó enviar, pero no existe una respuesta completa y verificable. No se reenvían automáticamente. |
| Reintento | Last.fm rechazó expresamente el lote con un error temporal admitido. Otro clic permite probar de nuevo. |
| Autorizar de nuevo | Last.fm indicó una sesión no válida. Vuelve a autorizar la misma cuenta antes de probar otro lote. |
| Rechazadas | Error explícito de configuración, parámetros o permisos. No entran otra vez en la cola de envío. |

No es posible prometer «exactamente una vez» frente a un corte de conexión: Last.fm puede recibir una petición y perderse su respuesta. El programa guarda la intención de envío antes de abrir la petición. Un cierre inesperado, un tiempo de espera agotado, una respuesta cortada o un resultado ambiguo dejan el lote **Sin confirmar**. Cuando vuelve a abrirse la interfaz, recupera así los envíos interrumpidos sin confundirlos con una sincronización que siga activa en otra ventana.

Para resolverlos, comprueba primero tu historial en Last.fm. Selecciona las filas y elige **Ya consta en Last.fm**, **Descartar envío dudoso** o **Permitir reenvío dudoso…**. Son decisiones manuales y quedan anotadas en el historial local. Permitir otro intento puede producir duplicados si Last.fm ya recibió esas escuchas; tampoco envía inmediatamente, sino que exige un próximo clic de envío.

El motor propone reintento para los rechazos explícitos `11` y `16` (servicio temporalmente no disponible) y `29` (límite de peticiones); el `9` exige autorización. Una fila que Last.fm omite con código `4` (fecha futura) o `5` (límite diario) también se conserva para un próximo envío explícito: espera a que llegue la fecha o se restablezca el límite antes de probar. El código individual `3` (fecha demasiado antigua) permanece omitido. No hay bucles de reintento ni temporizadores que envíen estas filas solos.

El error genérico `8`, los errores desconocidos y los fallos de transporte se tratan como inciertos. No se interpreta un HTTP 200 como aceptación por sí solo: se comprueba el resultado de cada fila, sus fechas y los totales del lote. Una respuesta incompleta o contradictoria deja el lote completo sin confirmar. Last.fm puede omitir algunas filas y aceptar otras; en ese caso se conservan los resultados individuales.

Los errores permanentes no tienen un botón de reencolado general en esta versión. Revisa la causa antes de decidir una recuperación del registro; no borres la base de datos para forzar reenvíos de todo el historial.

## Archivos locales y privacidad

Por defecto, los datos están en `%LOCALAPPDATA%\emepetres\Lastfm\`:

| Archivo o carpeta | Contenido |
| --- | --- |
| `listens.sqlite3` | Cola por cuenta, estados, metadatos, referencias al origen e historial de decisiones. |
| `imports/` | Copias exactas de cada versión importada, identificadas por su SHA-256. |
| `backups/` | Copias coherentes de SQLite antes de operaciones importantes y las solicitadas manualmente. |
| `credentials.dpapi` | API key, secreto y sesiones cifrados por DPAPI para la cuenta actual de Windows. |
| `sync.lock` | Archivo auxiliar para impedir que dos procesos sincronicen la misma cola a la vez. |

Los registros y sus copias contienen tu historial musical y rutas locales; no se suben a servicios públicos. No están cifrados por la aplicación. Las credenciales sí se cifran **antes** de escribir cualquier archivo temporal: no existe alternativa de guardado en texto plano. El cifrado depende del usuario de Windows; copiar `credentials.dpapi` a otra cuenta o equipo no es una forma de trasladar la autorización. La memoria del proceso contiene las claves mientras se usan, como en cualquier cliente autenticado.

**Olvidar credenciales** elimina el almacén de este equipo y conserva las escuchas y copias. Para retirar también el acceso en Last.fm, revoca la aplicación desde los ajustes de tu cuenta en su web. No se escriben claves, sesiones, tokens ni respuestas completas del servicio en los mensajes de error de la herramienta.

Conserva `listens.sqlite3` y sus copias si quieres mantener la protección frente a reenvíos. La deduplicación se hace por cuenta y por la fecha original y metadatos de cada escucha. La misma canción con otra fecha sigue siendo otra escucha. No hay una comprobación global de todo lo que ya existe en Last.fm, ni coordinación automática entre dos PC con bases de datos diferentes. Cambiar metadatos, fechas o importar registros transformados puede hacer que una escucha parezca nueva. Las filas sin fecha se conservan por archivo de origen y posición, siempre fuera de la cola de envío.

## Compatibilidad con Rockbox anterior

Se admite importar `.scrobbler.log` y `.scrobbler-timeless.log` con siete u ocho campos separados por tabuladores: artista, álbum, título, número de pista, duración en segundos, `L`/`S`, fecha Unix y MusicBrainz ID opcional. Se admite UTF-8 con o sin BOM. Las filas dañadas se guardan para revisión; una última fila sin salto de línea se considera incompleta y puede completarse al reimportar.

Los registros antiguos de Rockbox pueden usar la fecha de guardado y la posición reproducida, con criterios de umbral configurables. No garantizan las mismas condiciones que el reloj de escucha de emepetrés. La herramienta respeta sus marcas `L`/`S` y exige fecha UTC confirmada, pero no puede reconstruir el momento de inicio ni cuánto tiempo se escuchó realmente a partir de esos archivos. Para nuevas escuchas usa la exportación propia de emepetrés.

## Ejecutar desde el código fuente y comprobarlo

La aplicación usa solamente la biblioteca estándar de Python. Para ejecutarla desde el repositorio en PowerShell, con un Python ya disponible:

```powershell
$env:PYTHONPATH = 'tools/emepetres'
python -m lastfm
```

La vista previa importa una copia y actualiza únicamente los datos locales; no envía ni autoriza:

```powershell
python -m lastfm preview --account TU_CUENTA --import 'C:\ruta\copia\.emepetres-scrobbler.log'
python -m lastfm preview --account TU_CUENTA --status uncertain
```

Para pruebas con datos ficticios puedes elegir una carpeta de datos separada con `--data-dir` antes del subcomando. Los comandos `connect` y `sync` son acciones de red explícitas: el primero autoriza y el segundo envía un único lote de una cuenta ya autorizada. No son necesarios para probar el motor. No pongas credenciales en argumentos de la consola.

```powershell
$env:PYTHONPATH = 'tools/emepetres'
python -m unittest discover -s tools/emepetres/lastfm/tests -v
```

Las pruebas usan registros ficticios y transportes sustituidos: formatos, deduplicación, reimportaciones, cuentas, firmas, lotes, aceptación parcial, fallos de respuesta, interrupciones, bloqueos y almacenamiento DPAPI. La prueba de DPAPI utiliza exclusivamente cadenas de prueba y se omite fuera de Windows. No hacen llamadas a Last.fm ni acceden a música, tarjetas o dispositivos reales.

El empaquetado del ejecutable se realiza en CI; PyInstaller no es necesario para ejecutar el código fuente y no se instala automáticamente en tu equipo. Un resultado correcto de pruebas locales no sustituye a comprobar la compilación publicada ni a una prueba autorizada de envío real.

El 12 de noviembre de 2026 se completó la autorización real en Windows: el usuario creó su aplicación personal y realizó la autorización del navegador. Se verificó en la interfaz «Autorizada en este equipo», con cero escuchas enviadas. Las pruebas automatizadas siguen usando únicamente datos ficticios y no necesitan estas credenciales. El envío real con una escucha auténtica y la comprobación física del reproductor siguen pendientes.

La aplicación incorpora también **Importar del Rocker**: busca únicamente los nombres de registro conocidos en las raíces de las unidades extraíbles, sin recorrer música ni escribir en la tarjeta. Prefiere el registro emepetres y conserva la importación manual. La suite ampliada de 41 pruebas y el empaquetado pasaron en [la ejecución 43392994768](https://github.com/aronfenix/emepetres/actions/runs/43392994768). El ejecutable nuevo se abrió en Windows, conservó la autorización existente y mostró la instrucción esperada al comprobar la tarjeta sin un registro exportado. Todavía no se ha enviado ninguna escucha real.

## Referencias de protocolo

- [Last.fm: Scrobbling 2.0](https://www.last.fm/api/scrobbling): condiciones de escucha, resultados individuales y errores.
- [Last.fm: Authentication specification](https://www.last.fm/api/authspec): `auth.getToken`, autorización en navegador, `auth.getSession` y firma MD5 del protocolo.
- [Last.fm: track.scrobble](https://www.last.fm/api/show/track.scrobble): parámetros, límites de 50 entradas y respuestas.

Las solicitudes se envían exclusivamente por HTTPS al endpoint moderno `https://ws.audioscrobbler.com/2.0/`, como POST con formulario UTF-8. La firma sigue el protocolo Last.fm: nombres ordenados por ASCII, valores sin codificar en URL, exclusión de `format`, `callback` y la propia firma, y secreto añadido antes del MD5. No se aceptan redirecciones de transporte que puedan reenviar una sesión a otro endpoint.
