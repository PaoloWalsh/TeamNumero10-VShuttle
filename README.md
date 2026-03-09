# V-SHUTTLE — Safety Driver Interface

Dashboard touch per il Safety Driver di una navetta a guida autonoma. Il sistema invia gli scenari rilevati dai sensori a un backend di valutazione e mostra in tempo reale la decisione dell'algoritmo (GO / STOP / OVERRIDE), con gestione del timeout e fallback di sicurezza automatico.

---

## Stack tecnologico

| Layer | Tecnologie |
|---|---|
| **Frontend** | Vite · HTML5 · CSS3 · Vanilla JavaScript (ES6+) |
| **Backend** | Python · FastAPI · Uvicorn |

---

## Come funziona

1. **Carica dataset** — Il driver carica un file `.json` contenente l'array degli scenari da simulare.
2. **Avvia il loop** — Ogni 4 secondi, lo scenario successivo viene inviato in POST all'endpoint `/api/evaluate`.
3. **Risposta backend:**
   - `GO` o `STOP` → l'UI si aggiorna con colore e barra di confidenza, il loop prosegue.
   - `OVERRIDE_REQUIRED` → il loop si ferma e parte un countdown di **2 secondi**.
4. **Intervento umano** — Il driver può premere **OVERRIDE** o **CONFERMA** entro i 2 secondi per riprendere il ciclo.
5. **Fallback di sicurezza** — Se il timer scade senza risposta, il sistema imposta automaticamente **STOP** e avanza allo scenario successivo.

---

## Struttura del progetto

```
v-shuttle/
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── main.js
│   └── scenarios.json      # dataset di esempio
├── backend/
│   ├── main.py             # app FastAPI
│   └── requirements.txt
└── README.md
```

---

## Installazione e avvio

### Frontend

Richiede **Node.js ≥ 18**.

```bash
cd frontend

# 1. Installa le dipendenze
npm install

# 2. Avvia il dev server (http://localhost:5173)
npm run dev
```


### Backend

Richiede **Python ≥ 3.10**.

```bash
cd backend

# 1. (Opzionale ma consigliato) Crea un virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# 2. Installa le dipendenze
pip install fastapi uvicorn pydantic

# oppure se esiste il requirements.txt
pip install -r requirements.txt

# 3. Avvia il server
uvicorn main:app --reload
```

L'endpoint atteso dal frontend è:

```
POST http://localhost:8000/api/evaluate
Content-Type: application/json
```

---

## Note

- Il frontend gira su `localhost:5173` e il backend su `localhost:8000`. Assicurati che il backend abbia **CORS abilitato** per accettare richieste dal dev server Vite.
- Se il backend non risponde, il sistema applica automaticamente **STOP** per garantire la sicurezza.
