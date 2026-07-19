# Arquitectura

## 1. Introducción

Agent-Orchestra es un sistema de múltiples agentes diseñado para ayudar a programar en proyectos con React, TypeScript y Vite. Su objetivo es dividir tareas complejas en pasos más simples que los agentes pueden resolver de forma coordinada, segura y ordenada.

El diseño busca ser simple y directo: se evita que los agentes se llamen entre sí sin control, manteniendo un flujo de trabajo claro y fácil de seguir.

---

## 2. Patrón Orchestrator-Workers

El sistema usa un modelo donde un agente central (el Orquestador) coordina a otros agentes especializados (los Subagentes o Workers). Esta relación tiene un solo nivel: ningún subagente puede darle trabajo a otro subagente. Todas las órdenes vienen del Orquestador.

Esto trae dos grandes beneficios:
1. El flujo de trabajo es muy predecible y fácil de revisar. Cada paso viene del Orquestador.
2. Se evita el riesgo de crear ciclos infinitos o confusos, algo común en sistemas donde los agentes se llaman entre sí libremente.

Para el Orquestador, usar un subagente es igual que usar cualquier otra herramienta: le da una orden y recibe un resultado claro.

---

## 3. Rol del Orquestador

El Orquestador es el único que se comunica directamente con el usuario. Recibe la tarea, la divide en pasos y decide a qué subagente llamar en cada momento, dándole toda la información que necesita.

El Orquestador no modifica archivos ni ejecuta comandos en la terminal por su cuenta; solo delega el trabajo. El Orquestador decide *qué* hacer, y los subagentes se encargan de *cómo* hacerlo.

Un flujo normal de trabajo se ve así:
1. Pide al **Explorador** que revise el estado actual del código.
2. Si hay dudas, pide al **Investigador** que busque información técnica.
3. Pide al **Implementador** que escriba o modifique el código.
4. Pide al **Testeador** que pruebe que todo funcione.
5. Pide al **Revisor** que confirme si el trabajo final cumple con lo que pidió el usuario.

Si un subagente se traba o falla, el Orquestador no se rinde de inmediato. Primero intenta explicar mejor la orden o usar otro subagente. Solo se detiene y le avisa al usuario si ya probó todas las opciones lógicas.

---

## 4. Roles de los Subagentes

### 4.1 Explorador
Se encarga de entender cómo está organizado el proyecto. Lee las carpetas y archivos importantes para conocer las reglas del código y las herramientas instaladas. Si descubre algo útil para el futuro, lo guarda en la memoria del proyecto.

### 4.2 Investigador
Su trabajo es buscar información técnica. Primero busca en los documentos oficiales guardados en el sistema y, si no encuentra lo que necesita, busca en internet. Al responder, siempre aclara de dónde sacó la información.

### 4.3 Implementador
Es quien realmente modifica el código. Antes de cambiar un archivo, lo lee para no borrar nada por accidente. Puede crear, editar y borrar archivos, y siempre avisa exactamente qué modificó.

### 4.4 Testeador
Se encarga de probar que todo funcione. Ejecuta comandos en la terminal, como pruebas automáticas, revisiones de código o iniciar servidores. Si encuentra errores, muestra los mensajes exactos para ayudar a corregirlos. También guarda comandos útiles para usarlos después.

### 4.5 Revisor
Revisa los archivos modificados para asegurarse de que cumplen con lo que pidió el usuario originalmente. Si todo está bien, aprueba el trabajo. Si falta algo o hay errores, avisa qué hay que arreglar.

---

## 5. Manejo de la Memoria y el Estado

El sistema recuerda las cosas en tres niveles diferentes:

### 5.1 Memoria a corto plazo (Contexto del agente)
Mientras un agente está trabajando en un paso, recuerda los mensajes y herramientas que va usando. Esta memoria se borra apenas termina su turno. Sirve para que el agente piense sin ensuciar la memoria global.

### 5.2 Estado de la Tarea
Es un registro que el Orquestador actualiza paso a paso. Guarda qué pidió el usuario, qué hizo cada agente, qué archivos se modificaron y si hubo problemas. Esto se guarda en un archivo, por lo que si cortas el trabajo, puedes retomarlo más tarde desde donde te quedaste.

### 5.3 Memoria del Proyecto
Es la memoria a largo plazo que sobrevive entre diferentes tareas. Aquí los agentes guardan cosas importantes del proyecto, como:
- Cómo está organizado el código.
- Reglas de programación a seguir.
- Dependencias o paquetes instalados.
- Comandos útiles.
- Historial de decisiones y errores arreglados.
Para no marearlos, cada agente solo recibe la parte de esta memoria que necesita para su trabajo.

---

## 6. Sistema de Búsqueda de Información (RAG)

### 6.1 Fuentes de información
El sistema tiene guardada la documentación oficial de React, TypeScript y Vite, que son las tecnologías principales que usa.

### 6.2 División de documentos
Para buscar mejor, los documentos largos se dividen en partes más pequeñas (chunks) usando los títulos originales del texto. Así, cada parte tiene sentido por sí sola y es más fácil de encontrar.

### 6.3 Búsqueda
Los textos se convierten en números (vectores) usando un modelo inteligente de OpenAI (`text-embedding-3-small`) y se guardan en una base de datos local llamada ChromaDB. Cuando el Investigador necesita saber algo, busca aquí primero usando significados y conceptos en lugar de palabras exactas.

---

## 7. Manejo de Errores

El sistema está preparado para no rendirse fácil. Si algo sale mal, los agentes intentan entender el problema y buscar otra solución antes de fallar.

Reglas clave:
- **No inventar nada**: Si los agentes no saben algo o no tienen información, deben decir que están bloqueados en lugar de inventar respuestas.
- **Límite de intentos**: Para evitar quedarse pensando para siempre, cada agente tiene un límite máximo de 20 intentos por turno. Si llega al límite, se detiene y pide ayuda al usuario.

---

## 8. Seguridad y Control (El Despachador)

Cada vez que un agente quiere usar una herramienta (como leer un archivo o ejecutar un comando), pasa por un "guardia de seguridad" llamado Despachador.

### 8.1 Permisos
El Despachador revisa si el agente tiene permiso para hacer lo que pide. Por ejemplo, se asegura de que solo modifiquen archivos dentro de la carpeta del proyecto, o frena comandos peligrosos en la terminal.

### 8.2 Monitoreo
Lleva un registro de qué agente usó qué herramienta y cuánto tiempo tardó. Esto es útil para saber qué está haciendo el sistema en todo momento.

### 8.3 Detección de repeticiones (Bucles)
El Despachador se da cuenta si un agente está haciendo lo mismo una y otra vez sin lograr nada nuevo (por ejemplo, leer el mismo archivo 3 veces seguidas). Si esto pasa, lo frena y le pide que intente otra cosa.

### 8.4 Permisos por agente
Cada agente solo tiene acceso a las herramientas que necesita para su rol. Por ejemplo, el Explorador no tiene la herramienta para borrar archivos.

---

## 9. Modos de Uso

Puedes usar el sistema de tres formas:

- **Modo Normal**: El Orquestador hace todo el trabajo de forma automática de principio a fin.
- **Modo Plan**: El Orquestador hace una lista de los pasos que va a seguir y te pregunta si estás de acuerdo antes de empezar a trabajar.
- **Modo Supervisión**: El sistema hace pausas y te pide permiso cada vez que va a modificar un archivo o ejecutar un comando en la terminal. Ideal para cambios delicados.
