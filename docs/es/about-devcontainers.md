# 🐳 Dev Container — Guía rápida

## ¿Qué es un Dev Container?

Un Dev Container es un entorno de desarrollo aislado que se ejecuta dentro de Docker.

En lugar de que cada miembro del equipo tenga que instalar y configurar manualmente Python, librerías y herramientas, el proyecto define todo en:

    .devcontainer/
    ├── Dockerfile
    └── devcontainer.json

Esto permite que todos trabajemos con el mismo entorno.

    Tu ordenador
         │
         ▼
      Docker
         │
         ▼
    Dev Container
         │
         ├── Python
         ├── alpaca-py
         ├── dependencias
         └── herramientas del proyecto

El código sigue estando en nuestro proyecto/Git.
El container proporciona principalmente el entorno donde ejecutamos el código.


---

#  Primera vez: abrir el proyecto

## 1. Clonar el repositorio

Desde una terminal:

    git clone https://github.com/Makeos-op/Alpaca-AI-Trading-Agents-Hackathon.git
    cd Alpaca-AI-Trading-Agents-Hackathon


## 2. Abrirlo con VS Code / VS Codium

Con VS Code:

    code .

Con VS Codium:

    codium .


## 3. Abrir dentro del Dev Container

El editor debería mostrar una notificación como:

    Reopen in Container

Si no aparece:

1. Abrir la Command Palette (`Ctrl + Shift + P`).
2. Buscar:

       Dev Containers: Reopen in Container

3. Ejecutarlo.

La primera vez puede tardar porque Docker tiene que construir la imagen.


---

#  ¿Cómo sé que estoy dentro?

En la esquina inferior izquierda debería aparecer algo parecido a:

    Dev Container: Hackathon Devcontainer

También podemos abrir una terminal integrada y comprobar:

    python --version

Y:

    pip show alpaca-py

Si estos comandos funcionan, estamos trabajando dentro del container.


---

#  Trabajar normalmente

Una vez dentro del container, trabajamos normalmente.

Por ejemplo:

    python src/main.py

Para comprobar el estado de Git:

    git status

Para preparar cambios:

    git add .

Para hacer un commit:

    git commit -m "Add market analyst"

Para subir los cambios:

    git push

No necesitamos instalar Python ni las dependencias del proyecto directamente en nuestra máquina.


---

# Añadir dependencias

Las dependencias de Python se mantienen en:

    requirements.txt

Por ejemplo:

    alpaca-py
    pandas
    numpy

No basta con hacer:

    pip install pandas

porque ese cambio solo existiría en nuestro container actual.

Debemos añadir la dependencia a:

    requirements.txt

y después reconstruir el container.


---

# ¿Cuándo reconstruir el container?

Si modificamos:

    .devcontainer/Dockerfile

o:

    .devcontainer/devcontainer.json

o añadimos nuevas dependencias a:

    requirements.txt

debemos reconstruir el container.

Desde VS Code / VS Codium:

    Ctrl + Shift + P

Buscar:

    Dev Containers: Rebuild Container

Y ejecutarlo.


## Si solo modificamos código Python

Por ejemplo:

    src/agents/market_analyst.py

NO hace falta reconstruir el container.

Simplemente guardamos el archivo y ejecutamos el código normalmente.


---

# API Keys

Las API keys NUNCA deben subirse a Git.

Utilizaremos un archivo local:

    .env

Por ejemplo:

    ALPACA_API_KEY=...
    ALPACA_SECRET_KEY=...

El archivo `.env` debe estar incluido en `.gitignore`.

Podemos mantener un archivo:

    .env.example

Sin las claves reales:

    ALPACA_API_KEY=
    ALPACA_SECRET_KEY=

Cada miembro del equipo configura sus propias credenciales.


---

# Git y ramas

No trabajemos directamente sobre `main`.

Antes de empezar una tarea, crear una rama:

    git switch -c feature/my-agent

Por ejemplo:

    git switch -c feature/market-analyst

Después de trabajar:

    git status

    git add .

    git commit -m "Add market analyst"

    git push -u origin feature/market-analyst

Después hacemos el Pull Request correspondiente.


---

# Errores comunes

## "No encuentro Python"

Comprobar que estamos dentro del Dev Container.

Desde la Command Palette:

    Dev Containers: Reopen in Container


## "Instalé una librería pero mi compañero no la tiene"

Probablemente hiciste:

    pip install paquete

pero no añadiste la dependencia a:

    requirements.txt

Añádela al archivo y reconstruye el container.


## "Modifiqué el Dockerfile y no veo los cambios"

Hay que reconstruir el container:

    Dev Containers: Rebuild Container


## "¿Tengo que usar Docker manualmente?"

El Dev Container se encarga de utilizar Docker por nosotros, asi que NO (normalmente).
---
# Importante 

Si algo es necesario para TODOS los miembros del equipo, no lo solucionemos únicamente instalándolo manualmente en nuestro container.

Debemos añadirlo a la configuración del proyecto:
    .devcontainer/Dockerfile

De esta manera, cualquier miembro del equipo puede reconstruir el container y obtener exactamente el mismo entorno.
